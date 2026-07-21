"""Deterministic .ddd digital-tachograph decoding + EU 561/2006 drivers' hours checks.

Pure logic (no DB / FastAPI coupling) extracted from server.py.
"""
from datetime import datetime, timezone, timedelta


def parse_ddd_last_timestamp(data: bytes):
    # Digital tacho TimeReal = uint32 seconds since 1970-01-01 UTC. Scan for the
    # most recent plausible timestamp (best-effort read of last activity/download).
    lo = int(datetime(2005, 1, 1, tzinfo=timezone.utc).timestamp())
    hi = int(datetime.now(timezone.utc).timestamp()) + 2 * 86400
    scan = data[:5_000_000]
    best = None
    for i in range(0, len(scan) - 3):
        val = int.from_bytes(scan[i:i + 4], "big")
        if lo <= val <= hi and (best is None or val > best):
            best = val
    if best:
        return datetime.fromtimestamp(best, tz=timezone.utc).date().isoformat()
    return None


_DDD_EXTS = ("ddd", "tgd", "c1b", "v1b", "dtc", "esm", "dtg", "tgz")
_ACT_NAMES = {0: "rest", 1: "available", 2: "work", 3: "driving"}


def _mins_hhmm(m):
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def _mins_dur(m):
    return f"{int(m) // 60}h {int(m) % 60:02d}m"


def parse_ddd(data: bytes):
    """Best-effort decode of a driver-card .ddd file into daily activity records.

    Walks the cyclic CardActivityDailyRecord buffer: each record is
    prevLen(2) recLen(2) date(TimeReal 4) presence(2) distance(2) then N*ActivityChangeInfo(2).
    ActivityChangeInfo bits: aa=activity(12-11), time=minutes-from-midnight(10-0).
    """
    lo = int(datetime(2005, 1, 1, tzinfo=timezone.utc).timestamp())
    hi = int(datetime.now(timezone.utc).timestamp()) + 2 * 86400
    n = len(data)
    days = {}
    pos = 0
    while pos < n - 12:
        rec_len = int.from_bytes(data[pos + 2:pos + 4], "big")
        date_val = int.from_bytes(data[pos + 4:pos + 8], "big")
        if 12 <= rec_len <= 8000 and (rec_len - 12) % 2 == 0 and lo <= date_val <= hi and pos + rec_len <= n:
            aci_bytes = data[pos + 12:pos + rec_len]
            acis = [int.from_bytes(aci_bytes[k:k + 2], "big") for k in range(0, len(aci_bytes), 2)]
            times = [a & 0x07FF for a in acis]
            if acis and all(t <= 1440 for t in times) and times == sorted(times):
                distance = int.from_bytes(data[pos + 10:pos + 12], "big")
                if distance > 2000:  # implausible daily distance -> false-positive record
                    pos += 1
                    continue
                segs = [(a & 0x07FF, (a >> 11) & 0x03) for a in acis]
                totals = {"driving": 0, "work": 0, "available": 0, "rest": 0}
                seg_list = []
                for i2, (t, act) in enumerate(segs):
                    end = segs[i2 + 1][0] if i2 + 1 < len(segs) else 1440
                    dur = max(0, end - t)
                    name = _ACT_NAMES[act]
                    totals[name] += dur
                    seg_list.append({"start": t, "activity": name, "dur": dur})
                date_iso = datetime.fromtimestamp(date_val, tz=timezone.utc).date().isoformat()
                days[date_val] = {
                    "date": date_iso, "distance_km": distance,
                    "driving_min": totals["driving"], "work_min": totals["work"],
                    "available_min": totals["available"], "rest_min": totals["rest"],
                    "segments": seg_list,
                }
                pos += rec_len
                continue
        pos += 1
    if not days:
        return {"found": False, "days": []}
    # Drop stray false-positive records far older than the newest record (card holds ~1 year).
    newest = max(days)
    cutoff = newest - 500 * 86400
    ordered = [days[k] for k in sorted(days) if k >= cutoff]
    return {"found": True, "days": ordered, "start": ordered[0]["date"], "end": ordered[-1]["date"]}


def detect_ddd_infringements(decoded, driver_name, region):
    """Deterministic EU 561/2006 drivers' hours checks against decoded .ddd activity."""
    is_ie = (region or "UK").upper() in ("IE", "IRELAND", "RSA")
    authority = "RSA" if is_ie else "DVSA"
    infr = []
    for day in decoded["days"]:
        date = day["date"]
        cont = 0            # continuous driving since last qualifying break
        partial15 = False   # had a >=15m break toward a 15+30 split
        flagged = False
        for seg in day["segments"]:
            act, dur = seg["activity"], seg["dur"]
            if act == "driving":
                cont += dur
                if cont > 270 and not flagged:
                    infr.append({
                        "type": "Continuous driving without break",
                        "datetime": f"{date} {_mins_hhmm(seg['start'])}",
                        "rule": "EU 561/2006 Art.7 — max 4.5h driving before a 45-min break",
                        "severity": "serious",
                        "detail": f"Continuous driving reached {_mins_dur(cont)} without a qualifying 45-minute break (may be split 15+30).",
                        "action": "Remind driver of break requirements; retain record; review working-time.",
                    })
                    flagged = True
            elif act == "rest":
                if dur >= 45 or (dur >= 30 and partial15):
                    cont = 0
                    partial15 = False
                    flagged = False
                elif dur >= 15:
                    partial15 = True
        d = day["driving_min"]
        if d > 600:
            infr.append({
                "type": "Daily driving limit exceeded", "datetime": date,
                "rule": "EU 561/2006 Art.6(1) — daily driving 9h (max 10h twice weekly)",
                "severity": "very_serious",
                "detail": f"Total driving {_mins_dur(d)} exceeds the absolute 10h daily maximum.",
                "action": "Investigate immediately — prohibition / graduated fixed penalty risk.",
            })
        elif d > 540:
            infr.append({
                "type": "Extended daily driving (over 9h)", "datetime": date,
                "rule": "EU 561/2006 Art.6(1) — over 9h permitted max twice per week",
                "severity": "minor",
                "detail": f"Driving {_mins_dur(d)} exceeds 9h — allowed only twice per week; verify weekly count.",
                "action": "Confirm the driver had no more than two 10h days this week.",
            })
    # Daily rest — proper rolling analysis across the whole timeline (merges rest across midnight
    # and treats unrecorded gaps as rest). A daily rest of >=9h must begin within 24h of duty starting.
    segs_abs = []
    for day in decoded["days"]:
        try:
            base = datetime.fromisoformat(day["date"]).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        for s in day["segments"]:
            if s["activity"] != "rest" and s["dur"] > 0:
                start = base + timedelta(minutes=s["start"])
                end = base + timedelta(minutes=s["start"] + s["dur"])
                segs_abs.append((start, end))
    segs_abs.sort()
    shifts = []
    for s, e in segs_abs:
        if shifts and (s - shifts[-1][1]) < timedelta(hours=9):
            shifts[-1][1] = max(shifts[-1][1], e)
        else:
            shifts.append([s, e])
    for s, e in shifts:
        span = e - s
        hrs = span.total_seconds() / 3600
        if span > timedelta(hours=24):
            infr.append({
                "type": "Possible missing record / card removed", "datetime": s.date().isoformat(),
                "rule": "Reg (EU) 165/2014 — driver card must record all activity; gaps require a manual/printout entry",
                "severity": "minor",
                "detail": f"A {hrs:.0f}h continuous duty span ({s.strftime('%d %b %H:%M')} to {e.strftime('%d %b %H:%M')}) with no 9h+ rest usually means the card was removed or records are missing — review manually.",
                "action": "Check for a manual entry / printout covering this gap.",
            })
        elif span > timedelta(hours=15):
            infr.append({
                "type": "Insufficient daily rest", "datetime": s.date().isoformat(),
                "rule": "EU 561/2006 Art.8 — a daily rest (11h, reduced 9h) must begin within 24h of duty starting",
                "severity": "serious",
                "detail": f"Duty period ran {hrs:.1f}h ({s.strftime('%d %b %H:%M')} to {e.strftime('%d %b %H:%M')}) without a qualifying daily rest inside the 24-hour window.",
                "action": "Investigate rostering; ensure a full/compensating rest is taken.",
            })
    for i in range(1, len(shifts)):
        rest = shifts[i][0] - shifts[i - 1][1]
        if timedelta(hours=9) <= rest < timedelta(hours=11):
            hrs = rest.total_seconds() / 3600
            infr.append({
                "type": "Reduced daily rest", "datetime": shifts[i][0].date().isoformat(),
                "rule": "EU 561/2006 Art.8 — reduced daily rest (9-11h) allowed max 3x between weekly rests",
                "severity": "minor",
                "detail": f"Daily rest of {hrs:.1f}h taken before duty on {shifts[i][0].strftime('%d %b')}.",
                "action": "Confirm no more than three reduced daily rests between weekly rests.",
            })
    total_driving = sum(x["driving_min"] for x in decoded["days"])
    summary = (
        f"Decoded {len(decoded['days'])} day(s) of activity ({decoded['start']} to {decoded['end']}) directly from the "
        f".ddd digital tachograph file. Total driving {_mins_dur(total_driving)}. "
        f"{len(infr)} potential infringement(s) detected under {authority}-enforced EU 561/2006 drivers' hours rules. "
        "Rest-related items are indicative and should be reviewed alongside weekly rest and any manual entries."
    )
    return {
        "driver_name": driver_name, "period": f"{decoded['start']} to {decoded['end']}",
        "summary": summary, "total_infringements": len(infr), "infringements": infr, "confidence": 0.9,
    }
