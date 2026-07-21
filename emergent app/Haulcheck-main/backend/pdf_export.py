"""PDF export: compliance summary reports + merging uploaded files into one pack."""
import io
import base64
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image as RLImage,
)
from pypdf import PdfWriter, PdfReader
from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os as _os

# A Unicode TTF font that has ✓ (U+2713) and ✗ (U+2717) glyphs for the condition column.
_SYMBOL_FONT = "Helvetica"
for _fp in ("/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
    try:
        if _os.path.exists(_fp):
            _name = "SheetSymbol"
            pdfmetrics.registerFont(TTFont(_name, _fp))
            _SYMBOL_FONT = _name
            break
    except Exception:
        pass

STATUS_COLORS = {
    "valid": colors.HexColor("#16a34a"),
    "due_soon": colors.HexColor("#d97706"),
    "expired": colors.HexColor("#dc2626"),
    "unknown": colors.HexColor("#94a3b8"),
}
STATUS_LABEL = {"valid": "Valid", "due_soon": "Due soon", "expired": "Expired", "unknown": "—"}

DARK = colors.HexColor("#0f172a")
SLATE = colors.HexColor("#475569")
LINE = colors.HexColor("#e2e8f0")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Brand", fontName="Helvetica-Bold", fontSize=9, textColor=SLATE, spaceAfter=2, leading=11))
    ss.add(ParagraphStyle("BigTitle", fontName="Helvetica-Bold", fontSize=24, textColor=DARK, spaceAfter=4, leading=27))
    ss.add(ParagraphStyle("Sub", fontName="Helvetica", fontSize=10, textColor=SLATE, spaceAfter=2, leading=13))
    ss.add(ParagraphStyle("Heading", fontName="Helvetica-Bold", fontSize=13, textColor=DARK, spaceBefore=16, spaceAfter=8, leading=16))
    ss.add(ParagraphStyle("Cell", fontName="Helvetica", fontSize=8.5, textColor=DARK, leading=11))
    ss.add(ParagraphStyle("CellHead", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white, leading=10))
    return ss


def _logo_flowable(logo_bytes, max_w_mm=48, max_h_mm=24):
    try:
        im = Image.open(io.BytesIO(logo_bytes))
        iw, ih = im.size
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        lb = io.BytesIO()
        im.save(lb, format="PNG")
        lb.seek(0)
        ratio = min((max_w_mm * mm) / iw, (max_h_mm * mm) / ih)
        logo = RLImage(lb, width=iw * ratio, height=ih * ratio)
        logo.hAlign = "LEFT"
        return logo
    except Exception:
        return None


def build_report_pdf(title, subtitle, meta_pairs, sections, logo_bytes=None, authority=None):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm, title=title)
    ss = _styles()
    story = []
    if logo_bytes:
        lf = _logo_flowable(logo_bytes)
        if lf:
            story.append(lf)
            story.append(Spacer(1, 8))
    brand = "HAULCHECK · COMPLIANCE" + (f" · {authority}" if authority else "")
    story.append(Paragraph(brand, ss["Brand"]))
    story.append(Paragraph(title, ss["BigTitle"]))
    if subtitle:
        story.append(Paragraph(subtitle, ss["Sub"]))
    gen = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    story.append(Paragraph(f"Generated {gen}", ss["Sub"]))
    if meta_pairs:
        story.append(Spacer(1, 6))
        rows = [[Paragraph(f"<b>{k}</b>", ss["Cell"]), Paragraph(str(v or "—"), ss["Cell"])] for k, v in meta_pairs]
        t = Table(rows, colWidths=[45 * mm, 133 * mm])
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)

    for sec in sections:
        story.append(Paragraph(sec["heading"], ss["Heading"]))
        if sec.get("type") == "kv":
            pairs = sec.get("pairs", [])
            if not pairs:
                story.append(Paragraph("No data recorded.", ss["Sub"]))
                continue
            rows = [[Paragraph(f"<b>{k}</b>", ss["Cell"]), Paragraph(str(v or "—"), ss["Cell"])] for k, v in pairs]
            t = Table(rows, colWidths=[50 * mm, 128 * mm])
            t.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(t)
            continue

        cols = sec["columns"]
        rows = sec.get("rows", [])
        if not rows:
            story.append(Paragraph("No records.", ss["Sub"]))
            continue
        head = [Paragraph(c, ss["CellHead"]) for c in cols]
        data = [head]
        status_styles = []
        for i, r in enumerate(rows, start=1):
            cells = [Paragraph(str(c if c not in (None, "") else "—"), ss["Cell"]) for c in r["cells"]]
            st = r.get("status")
            if st:
                cells.append(Paragraph(f'<font color="#{STATUS_COLORS.get(st, SLATE).hexval()[2:]}"><b>{STATUS_LABEL.get(st, st)}</b></font>', ss["Cell"]))
            data.append(cells)
        ncols = len(data[0])
        avail = 178 * mm
        col_widths = [avail / ncols] * ncols
        t = Table(data, colWidths=col_widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ]
        t.setStyle(TableStyle(style + status_styles))
        story.append(t)

    doc.build(story)
    return buf.getvalue()


def build_letter_pdf(company, recipient_name, recipient_address, subject, body, date_str, doc_type, signoff_name="", signoff_role="", logo_bytes=None):
    """Formal company letter. company: dict from operator details. body: plain text, \n\n = paragraphs."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm,
                            leftMargin=22 * mm, rightMargin=22 * mm, title=subject or doc_type)
    ss = _styles()
    if "Letter" not in ss:
        ss.add(ParagraphStyle("Letter", fontName="Helvetica", fontSize=10.5, textColor=DARK, leading=15, spaceAfter=10))
        ss.add(ParagraphStyle("LetterHead", fontName="Helvetica-Bold", fontSize=15, textColor=DARK, leading=18, spaceAfter=1))
        ss.add(ParagraphStyle("LetterMeta", fontName="Helvetica", fontSize=9, textColor=SLATE, leading=12))
        ss.add(ParagraphStyle("LetterSubject", fontName="Helvetica-Bold", fontSize=11, textColor=DARK, leading=14, spaceBefore=6, spaceAfter=10))
    story = []
    if logo_bytes:
        lf = _logo_flowable(logo_bytes)
        if lf:
            story.append(lf)
            story.append(Spacer(1, 8))
    cname = (company or {}).get("company_name") or "Company Name"
    story.append(Paragraph(cname, ss["LetterHead"]))
    head_bits = []
    if (company or {}).get("address"):
        head_bits.append(company["address"].replace("\n", ", "))
    if (company or {}).get("operator_licence_number"):
        head_bits.append(f"O-Licence {company['operator_licence_number']}")
    if (company or {}).get("company_number"):
        head_bits.append(f"Co. No. {company['company_number']}")
    if head_bits:
        story.append(Paragraph(" &nbsp;·&nbsp; ".join(head_bits), ss["LetterMeta"]))
    story.append(Spacer(1, 4))
    story.append(Table([[""]], colWidths=[166 * mm], style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1, DARK)])))
    story.append(Spacer(1, 12))
    story.append(Paragraph(date_str, ss["LetterMeta"]))
    story.append(Spacer(1, 10))
    if recipient_name:
        story.append(Paragraph(f"<b>{recipient_name}</b>", ss["Letter"]))
    if recipient_address:
        for line in recipient_address.split("\n"):
            if line.strip():
                story.append(Paragraph(line.strip(), ss["LetterMeta"]))
    story.append(Spacer(1, 8))
    if subject:
        story.append(Paragraph(f"Re: {subject}", ss["LetterSubject"]))
    story.append(Paragraph(f"Dear {recipient_name or 'Sir/Madam'},", ss["Letter"]))
    for para in (body or "").split("\n\n"):
        p = para.strip().replace("\n", "<br/>")
        if p:
            story.append(Paragraph(p, ss["Letter"]))
    story.append(Spacer(1, 16))
    story.append(Paragraph("Yours sincerely,", ss["Letter"]))
    story.append(Spacer(1, 18))
    if signoff_name:
        story.append(Paragraph(f"<b>{signoff_name}</b>", ss["Letter"]))
    if signoff_role:
        story.append(Paragraph(signoff_role, ss["LetterMeta"]))
    doc.build(story)
    return buf.getvalue()




# DVSA HGV inspection manual (TM) reference numbers, in the exact order of the 67-point PMI checklist.
PMI_TM_NUMBERS = [
    "1", "2", "18", "9", "10", "8", "11", "7", "16/69", "6", "29", "29", "53", "17/43",
    "13", "14", "4", "5", "12", "15", "21/22", "19",
    "22", "3", "27", "25", "24", "26", "31", "32", "45", "35", "33", "45", "68", "16/70",
    "20", "53", "34", "53", "46", "43", "36", "50/51/54/55", "50/51/54/55", "52", "44", "53",
    "49", "47", "33", "30", "48", "48", "56/59", "57", "", "59", "60/61", "28", "58", "", "", "",
    "37/38", "39/40", "41/42",
]


def build_pmi_sheet_pdf(operator, record, region, logo_bytes=None):
    """Full itemised PMI/HGV inspection sheet for a single completed inspection (matches the paper HCV sheet)."""
    is_ie = region == "IE"
    authority = "RSA" if is_ie else "DVSA"
    doc_title = "COMMERCIAL VEHICLE ROADWORTHINESS INSPECTION" if is_ie else "VEHICLE INSPECTION REPORT (HGV)"
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm,
                            leftMargin=12 * mm, rightMargin=12 * mm, title=doc_title)
    ss = _styles()
    if "SheetLabel" not in ss:
        ss.add(ParagraphStyle("SheetLabel", fontName="Helvetica-Bold", fontSize=7.5, textColor=SLATE, leading=9))
        ss.add(ParagraphStyle("SheetVal", fontName="Helvetica", fontSize=9, textColor=DARK, leading=11))
        ss.add(ParagraphStyle("SheetCell", fontName="Helvetica", fontSize=7.5, textColor=DARK, leading=9))
        ss.add(ParagraphStyle("SheetCellB", fontName="Helvetica-Bold", fontSize=7.5, textColor=DARK, leading=9))
        ss.add(ParagraphStyle("SheetHeadCell", fontName="Helvetica-Bold", fontSize=7, textColor=colors.white, leading=9))
        ss.add(ParagraphStyle("SheetNote", fontName="Helvetica-Oblique", fontSize=7.5, textColor=SLATE, leading=10))
        ss.add(ParagraphStyle("SectionBar", fontName="Helvetica-Bold", fontSize=8.5, textColor=colors.white, leading=11))

    story = []
    if logo_bytes:
        lf = _logo_flowable(logo_bytes, max_w_mm=40, max_h_mm=18)
        if lf:
            story.append(lf)
            story.append(Spacer(1, 4))
    story.append(Paragraph(f"HAULCHECK · {authority} COMPLIANCE", ss["Brand"]))
    story.append(Paragraph(doc_title, ss["BigTitle"]))
    story.append(Spacer(1, 6))

    def kv(label, value):
        return [Paragraph(label, ss["SheetLabel"]), Paragraph(str(value or "—"), ss["SheetVal"])]

    header_rows = [
        kv("Operator", (operator or {}).get("company_name")) + kv("Odometer Reading", record.get("odometer") or record.get("mileage")),
        kv("Name of Inspector", record.get("inspector")) + kv("Vehicle Reg / Fleet No.", record.get("vehicle_reg")),
        kv("Vehicle Make / Model", record.get("make_model")) + kv("Date", record.get("inspection_date")),
    ]
    ht = Table(header_rows, colWidths=[34 * mm, 55 * mm, 34 * mm, 63 * mm])
    ht.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(ht)
    story.append(Spacer(1, 8))

    checklist = record.get("checklist") or []
    col_widths = [11 * mm, 15 * mm, 70 * mm, 15 * mm, 46 * mm, 29 * mm]
    head = [Paragraph(c, ss["SheetHeadCell"]) for c in
            ["Check", "TM no.", "Item inspected", "Cond.", "Description of Defect", "Rectified by"]]

    current_section = None
    data = []
    defect_items = []
    for idx, c in enumerate(checklist):
        sec = c.get("section") or ""
        if sec != current_section:
            current_section = sec
            data.append([Paragraph(sec, ss["SectionBar"]), "", "", "", "", ""])
        tm = PMI_TM_NUMBERS[idx] if idx < len(PMI_TM_NUMBERS) else ""
        ok = c.get("ok", True)
        cond = (Paragraph(f'<font name="{_SYMBOL_FONT}" size="11" color="#16a34a">\u2713</font>', ss["SheetCell"]) if ok
                else Paragraph(f'<font name="{_SYMBOL_FONT}" size="11" color="#dc2626">\u2717</font>', ss["SheetCellB"]))
        note = c.get("note") or ""
        if not ok:
            defect_items.append((idx + 1, c.get("item"), note))
        data.append([
            Paragraph(str(idx + 1), ss["SheetCell"]), Paragraph(tm, ss["SheetCell"]),
            Paragraph(c.get("item") or "", ss["SheetCell"]), cond,
            Paragraph(note, ss["SheetCell"]),
            Paragraph(record.get("rectified_by") or "" if not ok else "", ss["SheetCell"]),
        ])

    section_rows = [i for i, row in enumerate(data) if row[1] == ""]
    ct = Table([head] + data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for si in section_rows:
        r = si + 1  # +1 because head row is row 0
        style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#334155")))
        style.append(("SPAN", (0, r), (-1, r)))
    ct.setStyle(TableStyle(style))
    story.append(ct)
    story.append(Spacer(1, 8))

    # Brake performance summary
    bt = record.get("brake_test_type", "none")
    brake_bits = [f"Test type: {bt if bt and bt != 'none' else 'Not performed'}"]
    if not is_ie:
        brake_bits.append("Laden" if record.get("laden") else "Unladen")
    for lbl, key in [("Service", "service_brake_pct"), ("Secondary", "secondary_brake_pct"), ("Parking", "parking_brake_pct")]:
        v = record.get(key)
        if v:
            brake_bits.append(f"{lbl} {v}%")
    story.append(Paragraph("Brake Performance", ss["Heading"]))
    story.append(Paragraph(" &nbsp;·&nbsp; ".join(brake_bits), ss["SheetVal"]))
    story.append(Spacer(1, 8))

    # Action taken on defects found
    story.append(Paragraph("Action Taken on Defects Found", ss["Heading"]))
    if defect_items:
        drows = [[Paragraph(h, ss["SheetHeadCell"]) for h in ["Check", "Item", "Defect", "Rectification action / Rectified by"]]]
        for num, item, note in defect_items:
            drows.append([
                Paragraph(str(num), ss["SheetCell"]), Paragraph(item or "", ss["SheetCell"]),
                Paragraph(note or "", ss["SheetCell"]),
                Paragraph(record.get("rectified_by") or "", ss["SheetCell"]),
            ])
        dt = Table(drows, colWidths=[11 * mm, 55 * mm, 65 * mm, 55 * mm], repeatRows=1)
        dt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(dt)
    else:
        story.append(Paragraph("No defects recorded — vehicle serviceable.", ss["SheetVal"]))
    if record.get("notes"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Notes:</b> {record.get('notes')}", ss["SheetCell"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "I certify that all defects have been satisfactorily repaired and the vehicle is now fit for service.",
        ss["SheetNote"]))
    story.append(Spacer(1, 10))

    # Declaration / signature
    result = (record.get("result") or "pass").upper()

    def _sig_cell(data_url):
        if data_url and isinstance(data_url, str) and "base64," in data_url:
            try:
                raw = base64.b64decode(data_url.split("base64,", 1)[1])
                im = Image.open(io.BytesIO(raw))
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                lb = io.BytesIO()
                im.save(lb, format="PNG")
                lb.seek(0)
                iw, ih = im.size
                ratio = min((55 * mm) / iw, (14 * mm) / ih)
                img = RLImage(lb, width=iw * ratio, height=ih * ratio)
                img.hAlign = "LEFT"
                return img
            except Exception:
                pass
        return Paragraph("Signature: ______________________", ss["SheetCell"])

    sig_rows = [
        [Paragraph("<b>Inspection carried out by</b>", ss["SheetCell"]), Paragraph("<b>Defects rectified by</b>", ss["SheetCell"])],
        [Paragraph(f"Name: {record.get('inspector') or ''}", ss["SheetCell"]), Paragraph(f"Name: {record.get('rectified_by') or ''}", ss["SheetCell"])],
        [_sig_cell(record.get("inspector_signature")), _sig_cell(record.get("rectifier_signature"))],
        [Paragraph("Position: ______________________", ss["SheetCell"]), Paragraph("Position: ______________________", ss["SheetCell"])],
        [Paragraph(f"Date: {record.get('inspection_date') or ''}", ss["SheetCell"]), Paragraph("Date: ______________________", ss["SheetCell"])],
    ]
    stt = Table(sig_rows, colWidths=[89 * mm, 89 * mm])
    stt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(Paragraph(f"Overall result: <b>{result}</b>", ss["SheetVal"]))
    story.append(Spacer(1, 4))
    story.append(stt)
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "All inspections must be conducted by a Suitably Qualified Person — one who is suitably qualified by academic "
        "qualifications or experience (or both) to carry out inspections, maintenance and repairs on this category of vehicle.",
        ss["SheetNote"]))
    doc.build(story)
    return buf.getvalue()


WALKAROUND_SECTIONS = [
    ("INTERNAL CHECKS", ["Mirrors and glass", "Windscreen wipers and washers", "Front view", "Warning lamps",
                         "Steering", "Horn", "Brakes and air build-up", "Height marker", "Seatbelts"]),
    ("EXTERNAL CHECKS", ["Lights and indicators", "Fuel/oil leaks", "Battery security and condition",
                         "Diesel exhaust fluid (AdBlue)", "Excessive engine exhaust smoke", "Security of body/wings",
                         "Spray suppression", "Tyres and wheel fixing", "Brake line", "Electrical connections",
                         "Coupling security", "Security of load", "Number plate", "Reflectors and lights", "Markers"]),
]
_WEEK_DAYS = [("mon", "Mon"), ("tue", "Tue"), ("wed", "Wed"), ("thu", "Thu"), ("fri", "Fri"), ("sat", "Sat"), ("sun", "Sun")]


def build_weekly_walkaround_pdf(operator, record, region, logo_bytes=None):
    """One-page weekly driver walkaround sheet — Mon–Sun grid of ✓/✗ per check item."""
    is_ie = region == "IE"
    authority = "RSA" if is_ie else "DVSA"
    doc_title = "WEEKLY VEHICLE WALKAROUND CHECK"
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm,
                            leftMargin=12 * mm, rightMargin=12 * mm, title=doc_title)
    ss = _styles()
    if "WkLabel" not in ss:
        ss.add(ParagraphStyle("WkLabel", fontName="Helvetica-Bold", fontSize=7.5, textColor=SLATE, leading=9))
        ss.add(ParagraphStyle("WkVal", fontName="Helvetica", fontSize=9, textColor=DARK, leading=11))
        ss.add(ParagraphStyle("WkItem", fontName="Helvetica", fontSize=7.8, textColor=DARK, leading=9))
        ss.add(ParagraphStyle("WkHead", fontName="Helvetica-Bold", fontSize=7.5, textColor=colors.white, leading=9, alignment=1))
        ss.add(ParagraphStyle("WkSection", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white, leading=10))
        ss.add(ParagraphStyle("WkNote", fontName="Helvetica-Oblique", fontSize=7.5, textColor=SLATE, leading=10))
        ss.add(ParagraphStyle("WkCell", fontName="Helvetica", fontSize=8, textColor=DARK, leading=10))

    # Build per-day item→ok lookup
    days = record.get("days") or {}
    day_lookup = {}
    for dk, _ in _WEEK_DAYS:
        d = days.get(dk) or {}
        m = {}
        for c in (d.get("checklist") or []):
            m[c.get("item")] = c.get("ok", True)
        day_lookup[dk] = {"map": m, "submitted": bool(d.get("checklist")), "date": d.get("date")}

    story = []
    if logo_bytes:
        lf = _logo_flowable(logo_bytes, max_w_mm=40, max_h_mm=18)
        if lf:
            story.append(lf)
            story.append(Spacer(1, 4))
    company = (operator or {}).get("company_name") or "Fleet Operator"
    story.append(Paragraph(f"HAULCHECK · {authority} COMPLIANCE", ss["Brand"]))
    story.append(Paragraph(company.upper(), ss["BigTitle"]))
    story.append(Paragraph(doc_title, ss["Sub"]))
    story.append(Spacer(1, 6))

    # Mileage total
    def _num(v):
        try:
            return int(str(v).replace(",", "").strip())
        except Exception:
            return None
    ms, mf = _num(record.get("mileage_start")), _num(record.get("mileage_finish"))
    total = str(mf - ms) if (ms is not None and mf is not None and mf >= ms) else "—"

    def kv(label, value):
        return [Paragraph(label, ss["WkLabel"]), Paragraph(str(value or "—"), ss["WkVal"])]

    header_rows = [
        kv("Vehicle registration", record.get("vehicle_reg")) + kv("Week commencing", record.get("week_start")),
        kv("Driver name", record.get("driver_name")) + kv("Mileage start", record.get("mileage_start")),
        kv("Mileage finish", record.get("mileage_finish")) + kv("Total", total),
    ]
    ht = Table(header_rows, colWidths=[34 * mm, 55 * mm, 32 * mm, 65 * mm])
    ht.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(ht)
    story.append(Spacer(1, 5))
    story.append(Paragraph("✓ or ✗ should be recorded for every item each day. If ✗, add details in Fault Reporting / Action Taken below.", ss["WkNote"]))
    story.append(Spacer(1, 5))

    head = [Paragraph("Check item", ss["WkHead"])] + [Paragraph(lbl, ss["WkHead"]) for _, lbl in _WEEK_DAYS]
    data = [head]
    section_rows = []
    for sec_name, items in WALKAROUND_SECTIONS:
        section_rows.append(len(data))
        data.append([Paragraph(sec_name, ss["WkSection"])] + ["" for _ in _WEEK_DAYS])
        for item in items:
            row = [Paragraph(item, ss["WkItem"])]
            for dk, _ in _WEEK_DAYS:
                info = day_lookup[dk]
                if not info["submitted"] or item not in info["map"]:
                    row.append("")
                elif info["map"][item]:
                    row.append(Paragraph(f'<font name="{_SYMBOL_FONT}" size="10" color="#16a34a">\u2713</font>', ss["WkCell"]))
                else:
                    row.append(Paragraph(f'<font name="{_SYMBOL_FONT}" size="10" color="#dc2626">\u2717</font>', ss["WkCell"]))
            data.append(row)

    day_w = 17 * mm
    ct = Table(data, colWidths=[66 * mm] + [day_w] * 7, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for r in section_rows:
        style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#334155")))
        style.append(("SPAN", (0, r), (-1, r)))
    ct.setStyle(TableStyle(style))
    story.append(ct)
    story.append(Spacer(1, 8))

    # Fault reporting / action taken
    story.append(Paragraph("Fault Reporting / Action Taken", ss["Heading"]))
    defect_lines = []
    for dk, lbl in _WEEK_DAYS:
        d = days.get(dk) or {}
        for c in (d.get("checklist") or []):
            if not c.get("ok", True):
                note = c.get("note") or ""
                defect_lines.append(f"<b>{lbl}</b> — {c.get('item')}{(': ' + note) if note else ''}")
    body = record.get("fault_reporting") or ""
    if defect_lines:
        story.append(Paragraph("<br/>".join(defect_lines), ss["WkCell"]))
        story.append(Spacer(1, 3))
    if body:
        story.append(Paragraph(body.replace("\n", "<br/>"), ss["WkCell"]))
    if not defect_lines and not body:
        story.append(Paragraph("No defects reported — vehicle serviceable all week.", ss["WkVal"]))
    story.append(Spacer(1, 12))

    # Driver signature (once for the week)
    def _sig_cell(data_url):
        if data_url and isinstance(data_url, str) and "base64," in data_url:
            try:
                raw = base64.b64decode(data_url.split("base64,", 1)[1])
                im = Image.open(io.BytesIO(raw))
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                lb = io.BytesIO()
                im.save(lb, format="PNG")
                lb.seek(0)
                iw, ih = im.size
                ratio = min((60 * mm) / iw, (16 * mm) / ih)
                img = RLImage(lb, width=iw * ratio, height=ih * ratio)
                img.hAlign = "LEFT"
                return img
            except Exception:
                pass
        return Paragraph("Signature: ______________________", ss["WkCell"])

    sig_rows = [
        [Paragraph(f"Driver name: {record.get('driver_name') or ''}", ss["WkCell"]),
         Paragraph(f"Week commencing: {record.get('week_start') or ''}", ss["WkCell"])],
        [_sig_cell(record.get("driver_signature")), Paragraph("Driver signature", ss["WkNote"])],
    ]
    stt = Table(sig_rows, colWidths=[89 * mm, 89 * mm])
    stt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(stt)
    doc.build(story)
    return buf.getvalue()



def _divider_pdf(title):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=40 * mm, leftMargin=16 * mm, rightMargin=16 * mm)
    ss = _styles()
    doc.build([Paragraph("ATTACHED DOCUMENT", ss["Brand"]), Paragraph(title, ss["BigTitle"])])
    return buf.getvalue()


def _image_to_pdf(data):
    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def concat_pdfs(pdf_list):
    """Concatenate a list of PDF byte-strings into one PDF."""
    writer = PdfWriter()
    for pb in pdf_list:
        if not pb:
            continue
        for page in PdfReader(io.BytesIO(pb)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def merge_pack(summary_bytes, files):
    """files: list of (data_bytes, content_type, filename). Returns merged PDF bytes."""
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(summary_bytes)).pages:
        writer.add_page(page)
    for data, ctype, fname in files:
        pdf_bytes = None
        ct = (ctype or "").lower()
        try:
            if "pdf" in ct or (fname or "").lower().endswith(".pdf"):
                pdf_bytes = data
            elif ct.startswith("image/") or (fname or "").lower().rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "webp", "gif", "bmp"):
                pdf_bytes = _image_to_pdf(data)
            else:
                continue  # skip non-mergeable (txt, ddd, etc.)
            for page in PdfReader(io.BytesIO(_divider_pdf(fname or "Document"))).pages:
                writer.add_page(page)
            for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
                writer.add_page(page)
        except Exception:
            continue
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
