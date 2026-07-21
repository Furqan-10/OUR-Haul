"""Section builders for downloadable compliance PDF reports.

Each builder takes already-fetched (and status-enriched) lists plus a region
and returns (title, subtitle, meta_pairs, sections) ready for build_report_pdf.
"""
from datetime import datetime, timezone


def _terms(region):
    ie = (region or "UK").upper() in ("IE", "IRELAND", "RSA")
    return {
        "vehicle_test": "CVRT Due" if ie else "MOT Due",
        "road_tax": "Motor Tax Due" if ie else "Vehicle Tax Due",
        "currency": "€" if ie else "£",
        "authority": "RSA (Ireland)" if ie else "DVSA (UK)",
    }


def _defect_status(d):
    if d.get("status") == "rectified" or d.get("rectified_date"):
        return "valid"
    if d.get("severity") in ("major", "safety_critical"):
        return "expired"
    return "due_soon"


def _yn(v):
    return "Yes" if v else "No"


def vehicles_report(vehicles, region):
    t = _terms(region)
    rows = []
    for v in sorted(vehicles, key=lambda x: (x.get("registration") or "")):
        rows.append({
            "cells": [
                v.get("registration"), v.get("type") or "—",
                " ".join([x for x in [v.get("make"), v.get("model")] if x]) or "—",
                v.get("mot_due") or "—", v.get("service_due") or "—", v.get("tax_due") or "—",
                "VOR" if v.get("vor") else "—",
            ],
            "status": v.get("mot_status") or "unknown",
        })
    sections = [{
        "heading": "Vehicles",
        "columns": ["Reg", "Type", "Make / Model", t["vehicle_test"], "Service Due", t["road_tax"], "VOR"],
        "rows": rows,
    }]
    return "Fleet — Vehicles", f"{len(rows)} vehicle(s) on file", sections


def trailers_report(trailers, region):
    t = _terms(region)
    rows = []
    for tr in sorted(trailers, key=lambda x: (x.get("trailer_number") or "")):
        rows.append({
            "cells": [
                tr.get("trailer_number"), tr.get("type") or "—",
                tr.get("mot_due") or "—", tr.get("service_due") or "—",
                "VOR" if tr.get("vor") else "—",
            ],
            "status": tr.get("mot_status") or "unknown",
        })
    sections = [{
        "heading": "Trailers",
        "columns": ["Trailer No", "Type", t["vehicle_test"], "Service Due", "VOR"],
        "rows": rows,
    }]
    return "Fleet — Trailers", f"{len(rows)} trailer(s) on file", sections


def drivers_report(drivers, region):
    rows = []
    for d in sorted(drivers, key=lambda x: (x.get("name") or "")):
        rows.append({
            "cells": [
                d.get("name"), d.get("licence_number") or "—",
                d.get("licence_expiry") or "—", d.get("cpc_expiry") or "—",
                d.get("tacho_card_expiry") or "—", d.get("penalty_points") or 0,
            ],
            "status": d.get("licence_status") or "unknown",
        })
    sections = [{
        "heading": "Drivers",
        "columns": ["Name", "Licence No", "Licence Exp", "CPC Exp", "Tacho Card Exp", "Points"],
        "rows": rows,
    }]
    return "Drivers — Licence & CPC", f"{len(rows)} driver(s) on file", sections


def defects_report(defects, region):
    rows = []
    for d in sorted(defects, key=lambda x: (x.get("defect_date") or x.get("created_at") or ""), reverse=True):
        rows.append({
            "cells": [
                d.get("defect_date") or (d.get("created_at") or "")[:10],
                d.get("vehicle_reg"), d.get("reported_by") or "—",
                d.get("category") or "General", (d.get("severity") or "minor").replace("_", " "),
                "Rectified" if (d.get("rectified_date") or d.get("status") == "rectified") else "Open",
            ],
            "status": _defect_status(d),
        })
    sections = [{
        "heading": "Defect Reports",
        "columns": ["Date", "Vehicle", "Reported by", "Category", "Severity", "State"],
        "rows": rows,
    }]
    return "Defect Reports", f"{len(rows)} defect(s) logged", sections


def service_report(records, region):
    t = _terms(region)
    cur = t["currency"]
    rows = []
    for s in sorted(records, key=lambda x: (x.get("service_date") or ""), reverse=True):
        rows.append({
            "cells": [
                s.get("service_date") or "—", s.get("vehicle_reg"),
                s.get("service_type") or "Service", s.get("odometer") or "—",
                s.get("provider") or "—", f"{cur}{s.get('cost') or 0}",
                s.get("next_service_due") or "—",
            ],
            "status": s.get("status") or "unknown",
        })
    sections = [{
        "heading": "Service Records",
        "columns": ["Date", "Vehicle", "Type", "Odometer", "Provider", "Cost", "Next Due"],
        "rows": rows,
    }]
    return "Vehicles Service Records", f"{len(rows)} service record(s)", sections


def wheel_report(audits, region):
    rows = []
    for w in sorted(audits, key=lambda x: (x.get("audit_date") or ""), reverse=True):
        rows.append({
            "cells": [
                w.get("audit_date") or "—", w.get("vehicle_reg"),
                (w.get("result") or "pass").title(), w.get("torque_setting") or "—",
                w.get("checked_by") or "—", w.get("next_due") or "—",
            ],
            "status": w.get("status") or "unknown",
        })
    sections = [{
        "heading": "Wheel Security Audits",
        "columns": ["Date", "Vehicle", "Result", "Torque", "Checked by", "Next Due"],
        "rows": rows,
    }]
    return "Wheel Security Audits", f"{len(rows)} audit(s)", sections


def walkaround_report(checks, region):
    rows = []
    for w in sorted(checks, key=lambda x: (x.get("check_date") or ""), reverse=True):
        found = w.get("result") == "defects_found"
        cl = w.get("checklist") or []
        checks_str = f"{sum(1 for c in cl if c.get('ok'))}/{len(cl)}" if cl else "—"
        rows.append({
            "cells": [
                w.get("check_date") or "—", w.get("vehicle_reg"),
                w.get("driver_name") or "—",
                "Defects found" if found else "Nil defect",
                checks_str, w.get("defects_noted") or "—",
                _yn(w.get("rectified")) if found else "—",
            ],
            "status": ("valid" if (not found or w.get("rectified")) else "due_soon"),
        })
    sections = [{
        "heading": "Daily Walkaround Checks",
        "columns": ["Date", "Vehicle", "Driver", "Result", "Checks", "Defects noted", "Rectified"],
        "rows": rows,
    }]
    return "Daily Walkaround Checks", f"{len(rows)} check(s)", sections


_WK_DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _weekly_stats(w):
    days = w.get("days") or {}
    recorded = sum(1 for k in _WK_DAY_KEYS if (days.get(k) or {}).get("checklist"))
    defects = sum(1 for k in _WK_DAY_KEYS for c in ((days.get(k) or {}).get("checklist") or []) if not c.get("ok", True))
    return recorded, defects


def weekly_walkaround_report(checks, region):
    rows = []
    for w in sorted(checks, key=lambda x: (x.get("week_start") or ""), reverse=True):
        recorded, defects = _weekly_stats(w)
        ms, mf = w.get("mileage_start"), w.get("mileage_finish")
        try:
            total = str(int(str(mf).replace(",", "")) - int(str(ms).replace(",", "")))
        except Exception:
            total = "—"
        rows.append({
            "cells": [
                w.get("week_start") or "—", w.get("vehicle_reg") or "—",
                w.get("driver_name") or "—", f"{recorded}/7",
                (f"{defects} defect(s)" if defects else "Nil defect"), total,
            ],
            "status": ("due_soon" if defects else "valid"),
        })
    sections = [{
        "heading": "Weekly Walkaround Checks",
        "columns": ["Week commencing", "Vehicle", "Driver", "Days recorded", "Defects", "Total mi"],
        "rows": rows,
    }]
    return "Weekly Walkaround Checks", f"{len(rows)} weekly sheet(s)", sections


def pmi_report(schedules, records, region):
    sched_rows = []
    for p in sorted(schedules, key=lambda x: (x.get("vehicle_reg") or "")):
        fw = p.get("frequency_weeks", 6)
        sched_rows.append({
            "cells": [
                p.get("vehicle_reg"),
                ("One-off / interim" if not fw or fw <= 0 else f"Every {fw} weeks"),
                p.get("next_due") or "—", p.get("inspector") or "—",
            ],
            "status": p.get("status") or "unknown",
        })
    rec_rows = []
    for r in sorted(records, key=lambda x: (x.get("inspection_date") or ""), reverse=True):
        rec_rows.append({
            "cells": [
                r.get("inspection_date") or "—", r.get("vehicle_reg"),
                (r.get("result") or "pass").upper(), r.get("inspector") or "—",
                r.get("notes") or "—",
            ],
            "status": "expired" if r.get("result") == "fail" else "valid",
        })
    sections = [
        {"heading": "PMI Schedules", "columns": ["Vehicle", "Frequency", "Next Due", "Inspector"], "rows": sched_rows},
        {"heading": "Inspection Records", "columns": ["Date", "Vehicle", "Result", "Inspector", "Notes"], "rows": rec_rows},
    ]
    return "PMI Inspections", f"{len(sched_rows)} schedule(s) · {len(rec_rows)} record(s)", sections


def pmi_history_report(schedule, records, region):
    """Per-schedule inspection history."""
    fw = schedule.get("frequency_weeks", 6)
    rows = []
    for r in sorted(records, key=lambda x: (x.get("inspection_date") or ""), reverse=True):
        cl = r.get("checklist") or []
        defects = sum(1 for c in cl if not c.get("ok"))
        rows.append({
            "cells": [
                r.get("inspection_date") or "—", (r.get("result") or "pass").upper(),
                r.get("inspector") or "—", r.get("rectified_by") or "—",
                (f"{defects} defect(s)" if defects else ("0 defects" if cl else "—")),
                r.get("notes") or "—", len(r.get("attachments") or []) or "—",
            ],
            "status": "expired" if r.get("result") == "fail" else "valid",
        })
    sections = [
        {"type": "kv", "heading": "Schedule", "pairs": [
            ("Vehicle", schedule.get("vehicle_reg")),
            ("Frequency", "One-off / interim" if not fw or fw <= 0 else f"Every {fw} weeks"),
            ("Next due", schedule.get("next_due") or "—"),
            ("Default inspector", schedule.get("inspector") or "—"),
        ]},
        {"heading": "Inspection History", "columns": ["Date", "Result", "Inspector", "Rectified by", "Defects", "Notes", "Files"], "rows": rows},
    ]
    return f"PMI History — {schedule.get('vehicle_reg')}", f"{len(rows)} inspection(s) recorded", sections


def _short(text, limit=220):
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= limit:
        return t or "—"
    # prefer a clean cut at the first sentence end, else hard cut
    dot = t.find(". ")
    if 40 <= dot <= limit:
        return t[:dot + 1]
    return t[:limit].rsplit(" ", 1)[0] + "…"


def tacho_report(analyses, region):
    rows = []
    for a in sorted(analyses, key=lambda x: (x.get("created_at") or ""), reverse=True):
        rows.append({
            "cells": [
                (a.get("created_at") or "")[:10], a.get("driver_name") or "—",
                a.get("period") or "—", a.get("total_infringements", 0),
                _short(a.get("summary")),
            ],
            "status": ("expired" if (a.get("total_infringements") or 0) > 0 else "valid"),
        })
    sections = [{
        "heading": "Tacho Infringement Analyses",
        "columns": ["Analysed", "Driver", "Period", "Infringements", "Summary"],
        "rows": rows,
    }]
    return "Tacho Analyses", f"{len(rows)} analysis/analyses", sections


def audit_pack(data, region):
    """Full compliance audit pack combining every domain into one report."""
    t = _terms(region)
    counts = {k: len(v) for k, v in data.items()}
    sections = [{
        "type": "kv", "heading": "Overview", "pairs": [
            ("Vehicles", counts.get("vehicles", 0)),
            ("Trailers", counts.get("trailers", 0)),
            ("Drivers", counts.get("drivers", 0)),
            ("PMI schedules", counts.get("pmi", 0)),
            ("PMI records", counts.get("pmi_records", 0)),
            ("Open defects", sum(1 for d in data.get("defects", []) if not (d.get("rectified_date") or d.get("status") == "rectified"))),
            ("Service records", counts.get("service", 0)),
            ("Wheel audits", counts.get("wheel", 0)),
            ("Daily checks", counts.get("walkaround", 0)),
            ("Weekly checks", counts.get("weekly_walkaround", 0)),
            ("Tacho analyses", counts.get("tacho", 0)),
        ],
    }]
    sections += vehicles_report(data.get("vehicles", []), region)[2]
    sections += trailers_report(data.get("trailers", []), region)[2]
    sections += drivers_report(data.get("drivers", []), region)[2]
    sections += pmi_report(data.get("pmi", []), data.get("pmi_records", []), region)[2]
    sections += defects_report(data.get("defects", []), region)[2]
    sections += service_report(data.get("service", []), region)[2]
    sections += wheel_report(data.get("wheel", []), region)[2]
    sections += walkaround_report(data.get("walkaround", []), region)[2]
    sections += weekly_walkaround_report(data.get("weekly_walkaround", []), region)[2]
    sections += tacho_report(data.get("tacho", []), region)[2]
    gen = datetime.now(timezone.utc).strftime("%d %b %Y")
    return "Fleet Audit Report", f"Full operator compliance snapshot · {gen}", sections
