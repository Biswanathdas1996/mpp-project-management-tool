"""Exports: PDF (MVP), Excel and PPTX (v1) — all rendered from the same dashboard payload."""
from __future__ import annotations

import io
from datetime import date
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

STATUS_COLORS = {"completed": "#2563eb", "on_track": "#16a34a", "delay": "#d97706", "critical_delay": "#dc2626",
                 "not_started": "#94a3b8"}
STATUS_LABEL = {"completed": "Completed", "on_track": "On Track", "delay": "Delay", "critical_delay": "Critical Delay",
                "not_started": "Not Started"}


def _f(v, suffix="", nd=1):
    return "—" if v is None else f"{v:.{nd}f}{suffix}"


# ----------------------------------------------------------------------------------------------- charts
def _gantt_png(dash: dict[str, Any]) -> bytes | None:
    items = dash["gantt"]["items"]
    if not items:
        return None
    fig, ax = plt.subplots(figsize=(10, max(2.2, 0.32 * len(items) + 1)), dpi=150)
    for i, it in enumerate(reversed(items)):
        s, f = date.fromisoformat(it["start"]), date.fromisoformat(it["finish"])
        width = max((f - s).days, 1)
        col = STATUS_COLORS.get(it["status"], "#94a3b8")
        ax.barh(i, width, left=mdates.date2num(s), color=col, alpha=0.28, height=0.6)
        ax.barh(i, width * (it["percent_complete"] or 0) / 100, left=mdates.date2num(s), color=col, height=0.6)
        ax.text(mdates.date2num(f) + 2, i, f"{it['percent_complete']:.0f}%", va="center", fontsize=7)
    ax.set_yticks(range(len(items)))
    ax.set_yticklabels([f"{it['number']:02d} {it['name'][:38]}" for it in reversed(items)], fontsize=7)
    ax.axvline(mdates.date2num(date.fromisoformat(dash["gantt"]["today"])), color="#dc2626", lw=1.2)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    plt.setp(ax.get_xticklabels(), fontsize=7, rotation=45)
    ax.grid(axis="x", alpha=0.25)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _trend_png(dash: dict[str, Any]) -> bytes | None:
    pts = [p for p in dash["trend"]["points"] if p["actual"] is not None]
    if not pts:
        return None
    fig, ax = plt.subplots(figsize=(10, 3), dpi=150)
    xs = [date.fromisoformat(p["as_of"]) for p in pts]
    ax.plot(xs, [p["planned"] for p in pts], marker="o", color="#64748b", label="Planned", lw=1.6, ls="--")
    ax.plot(xs, [p["actual"] for p in pts], marker="o", color="#2563eb", label="Actual", lw=2)
    ax.set_ylim(0, 100)
    ax.set_ylabel("% complete", fontsize=8)
    ax.legend(fontsize=8, frameon=False)
    ax.grid(alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    plt.setp(ax.get_xticklabels(), fontsize=7)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _tracks_png(dash: dict[str, Any]) -> bytes | None:
    tr = dash["tracks"]
    if not tr:
        return None
    fig, ax = plt.subplots(figsize=(10, max(2, 0.35 * len(tr) + 0.8)), dpi=150)
    names = [f"{t['label']} {t['name'][:30]}" for t in reversed(tr)]
    ax.barh(names, [t["planned"] for t in reversed(tr)], color="#cbd5e1", height=0.7, label="Planned")
    ax.barh(names, [t["actual"] for t in reversed(tr)], color=[STATUS_COLORS.get(t["status"], "#2563eb")
                                                                for t in reversed(tr)], height=0.4, label="Actual")
    ax.set_xlim(0, 100)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _summary_lines(dash: dict[str, Any]) -> list[tuple[str, str, str]]:
    c = dash["cards"]
    tl = c["active_track_timeline"]
    nm = c["next_milestone"]
    return [
        ("Program Completion", _f(c["program_completion"]["value"], "%"), c["program_completion"].get("tag") or ""),
        ("Active Tracks", f"{c['active_tracks']['value'] or 0}/{c['active_tracks']['total'] or 0}",
         f"{c['active_tracks']['pending'] or 0} tracks pending activation"),
        ("Total Milestones", str(c["total_milestones"]["value"] or 0),
         f"across {c['total_milestones'].get('tracks_covered') or 0} tracks"),
        ("On Track", str(c["on_track"]["value"] or 0), "milestones progressing"),
        ("Not Started", str(c["not_started"]["value"] or 0), "milestones pending"),
        ("Decisions Required", str(c["decisions_required"]["value"] or 0),
         f"{c['decisions_required']['high_priority']} high-priority for Committee"),
        ("High Risks", str(c["high_risks"]["value"] or 0), f"of {c['high_risks']['tracked']} tracked - need mitigation"),
        ("Active Track Timeline", f"{tl.get('value') or '—'} months",
         f"month {tl.get('month', '—')} of {tl.get('of_months', '—')} - {tl.get('elapsed_pct', 0)}% elapsed"
         if tl.get("available") else ""),
        ("Next Milestone", nm.get("name") or "—",
         f"starts {date.fromisoformat(nm['start']).strftime('%B %Y')}" if nm.get("start") else ""),
    ]


# ----------------------------------------------------------------------------------------------- PDF
def export_pdf(dash: dict[str, Any], kpis: list[dict[str, Any]], logos: dict[str, bytes | None]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    buf = io.BytesIO()
    h = dash["header"]
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title=h["title"], author="PMA")
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=18, spaceAfter=2, textColor=colors.HexColor("#0f172a"))
    H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4,
                        textColor=colors.HexColor("#1e3a8a"))
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=8, leading=10)
    cell = ParagraphStyle("c", parent=ss["Normal"], fontSize=7.5, leading=9)
    story: list[Any] = []

    head_cells: list[Any] = []
    if logos.get("client_logo"):
        head_cells.append(Image(io.BytesIO(logos["client_logo"]), width=22 * mm, height=14 * mm, kind="proportional"))
    else:
        head_cells.append(Paragraph(f"<b>{h['client_name'] or ''}</b>", small))
    head_cells.append([Paragraph(h["title"], H1),
                       Paragraph(f"{h['subtitle'] or ''} &nbsp; | &nbsp; As of {h['as_of']}"
                                 f"{' &nbsp; | &nbsp; ' + h['location'] if h.get('location') else ''}", small)])
    if logos.get("vendor_logo"):
        head_cells.append(Image(io.BytesIO(logos["vendor_logo"]), width=22 * mm, height=14 * mm, kind="proportional"))
    else:
        head_cells.append(Paragraph("", small))
    t = Table([head_cells], colWidths=[30 * mm, None, 30 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [t, Spacer(1, 4)]

    ks = dash["kpi_strip"]
    strip = Table([[f"Tracks: {ks['tracks']}", f"Active: {ks['active']}", f"Avg Progress: {ks['avg_progress']}%",
                    f"Milestones: {ks['milestones']}"]], colWidths=[None] * 4)
    strip.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eff6ff")),
                               ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                               ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bfdbfe"))]))
    story += [strip, Spacer(1, 6), Paragraph("Executive Overview", H2)]

    lines = _summary_lines(dash)
    rows = []
    for i in range(0, len(lines), 3):
        rows.append([Paragraph(f"<font size=7 color='#64748b'>{n.upper()}</font><br/><font size=14><b>{v}</b></font>"
                               f"<br/><font size=7>{cap}</font>", small) for n, v, cap in lines[i:i + 3]])
    kt = Table(rows, colWidths=[None] * 3)
    kt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.append(kt)

    if dash.get("ai_summary"):
        c = dash["ai_summary"]["content"]
        story += [Paragraph("AI Executive Summary (AI-generated narrative; figures from KPI engine)", H2),
                  Paragraph(f"<b>{c.get('headline', '')}</b>", small), Paragraph(c.get("summary", ""), small)]

    tsum = dash["trend"]["summary"]
    story += [Paragraph("Progress Trend", H2),
              Paragraph(f"Programme planned to date {_f(tsum['planned'], '%')} - Actual {_f(tsum['actual'], '%')} - "
                        f"{_f(tsum['behind_pts'], ' pts')} {'behind' if (tsum['behind_pts'] or 0) >= 0 else 'ahead of'} plan - "
                        f"{dash['trend'].get('cycle_label', 'weekly')} reporting cycle - "
                        f"{dash['trend']['cycles_reported']} cycles reported - roll-up covers "
                        f"{tsum['tracks_covered']} of {tsum['tracks_total']} tracks", small)]
    png = _trend_png(dash)
    if png:
        story.append(Image(io.BytesIO(png), width=250 * mm, height=75 * mm))

    story += [PageBreak(), Paragraph("Delivery Tracks Overview", H2)]
    trows = [["Track", "Name", "Status", "Actual %", "Planned %", "Variance", "Start", "Finish"]]
    for tr in dash["tracks"]:
        trows.append([tr["label"], Paragraph(tr["name"], cell), STATUS_LABEL.get(tr["status"], tr["status"]),
                      _f(tr["actual"], "%"), _f(tr["planned"], "%"), f"{tr['variance']:+.1f} pts",
                      tr["start"] or "", tr["finish"] or ""])
    story.append(_table(trows, [18 * mm, 80 * mm, 26 * mm, 20 * mm, 20 * mm, 22 * mm, 24 * mm, 24 * mm]))
    png = _tracks_png(dash)
    if png:
        story.append(Image(io.BytesIO(png), width=230 * mm, height=min(110, 9 * len(dash["tracks"]) + 20) * mm))

    story += [PageBreak(), Paragraph("Milestones", H2)]
    mrows = [["#", "Milestone", "Track", "Timeline", "Status", "Health", "Progress", "Variance"]]
    for m in dash["milestones"]:
        mrows.append([f"{m['number']:02d}", Paragraph(m["name"], cell), f"{m['track_number'] or 0:02d}",
                      f"{m['start'] or ''} – {m['finish'] or ''}", STATUS_LABEL.get(m["status"], m["status"]),
                      (m["health"] or {}).get("label", ""), _f(m["percent_complete"], "%"),
                      f"{m['variance_pts']:+.1f} pts"])
    story.append(_table(mrows, [10 * mm, 90 * mm, 14 * mm, 46 * mm, 26 * mm, 28 * mm, 18 * mm, 20 * mm],
                        status_col=4))
    png = _gantt_png(dash)
    if png:
        story += [PageBreak(), Paragraph("Timeline", H2),
                  Image(io.BytesIO(png), width=250 * mm, height=min(165, 8 * len(dash["gantt"]["items"]) + 25) * mm)]

    story += [PageBreak(), Paragraph("Key Support &amp; Decisions", H2)]
    drows = [["Title", "Description", "Priority", "Status", "Owner", "Needed by"]]
    for d in dash["decisions"]:
        drows.append([Paragraph(d["title"], cell), Paragraph(d["description"] or "", cell), d["priority"], d["status"],
                      d["owner"] or "", d["needed_by"] or ""])
    story.append(_table(drows, [55 * mm, 105 * mm, 20 * mm, 22 * mm, 34 * mm, 24 * mm]))
    story.append(Paragraph("Risk Register", H2))
    rrows = [["Severity", "Title", "Description", "Mitigation", "Owner", "Due"]]
    for r in dash["risks"]:
        rrows.append([r["severity"], Paragraph(r["title"], cell), Paragraph(r["description"] or "", cell),
                      Paragraph(r["mitigation"] or "", cell), r["owner"] or "", r["due_date"] or ""])
    story.append(_table(rrows, [20 * mm, 50 * mm, 75 * mm, 75 * mm, 22 * mm, 20 * mm]))
    att = dash["attention"]["derived"] + dash["attention"]["items"]
    story.append(Paragraph("Attention", H2))
    arows = [["Severity", "Item", "Detail", "Due"]]
    for a in att:
        arows.append([a["severity"], Paragraph(a["title"], cell), Paragraph(a.get("description") or "", cell),
                      a.get("due_date") or ""])
    story.append(_table(arows, [22 * mm, 80 * mm, 140 * mm, 24 * mm]))

    avail = [k for k in kpis if k["available"] and not k.get("reference")]
    if avail:
        story += [PageBreak(), Paragraph("Extended KPIs", H2)]
        krows = [["Category", "KPI", "Value", "Formula (v)"]]
        for k in avail:
            krows.append([k["category"], Paragraph(k["name"], cell), Paragraph(k["display"] or "", cell),
                          Paragraph(f"{k['formula']} (v{k['version']})", cell)])
        story.append(KeepTogether(_table(krows, [24 * mm, 60 * mm, 50 * mm, 130 * mm])))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        txt = f"{h['title']} · Snapshot v{dash['snapshot']['version_no']} · As of {h['as_of']}"
        if h.get("support_email"):
            txt += f" · Contact us: {h['support_email']}"
        canvas.drawString(14 * mm, 8 * mm, txt)
        canvas.drawRightString(landscape(A4)[0] - 14 * mm, 8 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _table(rows, widths, status_col: int | None = None):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    t = Table(rows, colWidths=widths, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
             ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0"))]
    if status_col is not None:
        inv = {v: k for k, v in STATUS_LABEL.items()}
        for i, r in enumerate(rows[1:], start=1):
            col = STATUS_COLORS.get(inv.get(r[status_col], ""), None)
            if col:
                style.append(("TEXTCOLOR", (status_col, i), (status_col, i), colors.HexColor(col)))
    t.setStyle(TableStyle(style))
    return t


# ----------------------------------------------------------------------------------------------- Excel
def export_excel(dash: dict[str, Any], kpis: list[dict[str, Any]], tasks: list[dict[str, Any]],
                 diffs: list[dict[str, Any]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    hdr_fill = PatternFill("solid", fgColor="1E3A8A")
    hdr_font = Font(color="FFFFFF", bold=True)

    def sheet(title, header, rows, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title[:31]
        ws.append(header)
        for c in ws[1]:
            c.fill, c.font = hdr_fill, hdr_font
            c.alignment = Alignment(vertical="center")
        for r in rows:
            ws.append(r)
        for i, col in enumerate(header, start=1):
            width = max([len(str(col))] + [len(str(r[i - 1])) for r in rows[:300] if i - 1 < len(r) and r[i - 1] is not None])
            ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 60)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        return ws

    h = dash["header"]
    ov = sheet("Overview", ["Metric", "Value", "Caption"], [list(x) for x in _summary_lines(dash)], first=True)
    ov.insert_rows(1, 2)
    ov["A1"] = h["title"]
    ov["A1"].font = Font(bold=True, size=14)
    ov["A2"] = f"As of {h['as_of']} · Snapshot v{dash['snapshot']['version_no']}"
    sheet("Tracks", ["Track", "Name", "Status", "Actual %", "Planned %", "Variance pts", "Start", "Finish", "Source"],
          [[t["label"], t["name"], STATUS_LABEL.get(t["status"]), t["actual"], t["planned"], t["variance"], t["start"],
            t["finish"], t["source_label"]] for t in dash["tracks"]])
    sheet("Milestones", ["#", "Milestone", "Track", "Start", "Finish", "Baseline finish", "Status", "Health",
                         "Progress %", "Planned %", "Variance pts", "Slippage days"],
          [[m["number"], m["name"], m["track_number"], m["start"], m["finish"], m["baseline_finish"],
            STATUS_LABEL.get(m["status"]), (m["health"] or {}).get("label"), m["percent_complete"],
            m["planned_percent"], m["variance_pts"], m["slippage_days"]] for m in dash["milestones"]])
    sheet("Trend", ["Cycle", "As of", "Planned %", "Actual %"],
          [[p["cycle"], p["as_of"], p["planned"], p["actual"]] for p in dash["trend"]["points"]])
    sheet("KPIs", ["Code", "KPI", "Category", "Phase", "Available", "Value", "Display", "Formula", "Version", "Reason"],
          [[k["code"], k["name"], k["category"], k["phase"], k["available"], k["value"], k["display"], k["formula"],
            k["version"], k["reason"]] for k in kpis])
    sheet("Decisions", ["Title", "Kind", "Priority", "Status", "Owner", "Needed by", "Description"],
          [[d["title"], d["kind"], d["priority"], d["status"], d["owner"], d["needed_by"], d["description"]]
           for d in dash["decisions"]])
    sheet("Risks", ["Severity", "Title", "Status", "Owner", "Due", "Description", "Mitigation"],
          [[r["severity"], r["title"], r["status"], r["owner"], r["due_date"], r["description"], r["mitigation"]]
           for r in dash["risks"]])
    sheet("Attention", ["Severity", "Title", "Source", "Due", "Detail"],
          [[a["severity"], a["title"], a.get("source"), a.get("due_date"), a.get("description")]
           for a in dash["attention"]["derived"] + dash["attention"]["items"]])
    sheet("What changed", ["Change", "Task UID", "Task", "Match", "Start Δ d", "Finish Δ d", "Progress Δ",
                           "Old status", "New status"],
          [[d["change_type"], d["task_unique_id"] or d["base_unique_id"], d["task_name"], d["match_method"],
            d["start_delta_days"], d["finish_delta_days"], d["progress_delta"], d["old_status"], d["new_status"]]
           for d in diffs])
    sheet("Tasks", ["UID", "ID", "WBS", "Name", "Level", "Summary", "Milestone", "Start", "Finish", "Baseline start",
                    "Baseline finish", "% complete", "Planned %", "Duration d", "Total slack d", "Critical", "Resources"],
          [[t["unique_id"], t["task_id"], t["wbs"], t["name"], t["outline_level"], t["is_summary"], t["is_milestone"],
            t["start"], t["finish"], t["baseline_start"], t["baseline_finish"], t["percent_complete"],
            t["planned_percent"], t["duration_days"], t["total_slack_days"], t["is_critical"],
            ", ".join(t["resource_names"] or [])] for t in tasks])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------------------------- PPTX
def export_pptx(dash: dict[str, Any], logos: dict[str, bytes | None]) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Emu, Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    h = dash["header"]
    navy = RGBColor(0x1E, 0x3A, 0x8A)

    def title(slide, text, sub=None):
        tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(10.5), Inches(0.9)).text_frame
        tb.text = text
        tb.paragraphs[0].runs[0].font.size = Pt(26)
        tb.paragraphs[0].runs[0].font.bold = True
        tb.paragraphs[0].runs[0].font.color.rgb = navy
        if sub:
            p = tb.add_paragraph()
            p.text = sub
            p.runs[0].font.size = Pt(12)
            p.runs[0].font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
        if logos.get("client_logo"):
            slide.shapes.add_picture(io.BytesIO(logos["client_logo"]), Inches(11.4), Inches(0.3), height=Inches(0.8))

    def table(slide, rows, top=1.4, widths=None):
        nrows, ncols = len(rows), len(rows[0])
        shape = slide.shapes.add_table(nrows, ncols, Inches(0.5), Inches(top), Inches(12.3),
                                       Inches(min(5.6, 0.32 * nrows + 0.3)))
        tbl = shape.table
        if widths:
            for i, w in enumerate(widths):
                tbl.columns[i].width = Emu(int(Inches(12.3) * w / sum(widths)))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                cell = tbl.cell(r, c)
                cell.text = "" if v is None else str(v)
                for p in cell.text_frame.paragraphs:
                    for run in p.runs:
                        run.font.size = Pt(10 if r else 11)
                        run.font.bold = r == 0

    s = prs.slides.add_slide(blank)
    title(s, h["title"], f"{h['subtitle'] or ''}   ·   As of {h['as_of']}")
    lines = _summary_lines(dash)
    for i, (n, v, cap) in enumerate(lines):
        x, y = 0.5 + (i % 3) * 4.15, 1.6 + (i // 3) * 1.85
        box = s.shapes.add_shape(1, Inches(x), Inches(y), Inches(3.95), Inches(1.65))
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor(0xF8, 0xFA, 0xFC)
        box.line.color.rgb = RGBColor(0xE2, 0xE8, 0xF0)
        tf = box.text_frame
        tf.text = n.upper()
        tf.paragraphs[0].runs[0].font.size = Pt(10)
        tf.paragraphs[0].runs[0].font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
        p = tf.add_paragraph()
        p.text = str(v)
        p.runs[0].font.size = Pt(24 if len(str(v)) < 14 else 14)
        p.runs[0].font.bold = True
        p.runs[0].font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
        p = tf.add_paragraph()
        p.text = cap
        p.runs[0].font.size = Pt(10)
        p.runs[0].font.color.rgb = RGBColor(0x47, 0x55, 0x69)

    if dash.get("ai_summary"):
        c = dash["ai_summary"]["content"]
        s = prs.slides.add_slide(blank)
        title(s, "Executive Summary", "AI-generated narrative · figures from the deterministic KPI engine")
        tf = s.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(12.3), Inches(5.5)).text_frame
        tf.word_wrap = True
        tf.text = c.get("headline", "")
        tf.paragraphs[0].runs[0].font.bold = True
        tf.paragraphs[0].runs[0].font.size = Pt(18)
        for part in [c.get("summary", "")] + [f"• {x}" for x in c.get("highlights", []) + c.get("concerns", [])]:
            p = tf.add_paragraph()
            p.text = part
            p.runs[0].font.size = Pt(13)

    for heading, png, sub in (("Progress Trend", _trend_png(dash), None), ("Delivery Tracks", _tracks_png(dash), None),
                              ("Timeline", _gantt_png(dash), None)):
        if png:
            s = prs.slides.add_slide(blank)
            title(s, heading, sub)
            s.shapes.add_picture(io.BytesIO(png), Inches(0.6), Inches(1.4), width=Inches(12.1))

    ms = dash["milestones"]
    for i in range(0, max(len(ms), 1), 14):
        s = prs.slides.add_slide(blank)
        title(s, "Milestones" + (f" ({i // 14 + 1})" if len(ms) > 14 else ""))
        rows = [["#", "Milestone", "Track", "Timeline", "Status", "Health", "Progress", "Variance"]]
        for m in ms[i:i + 14]:
            rows.append([f"{m['number']:02d}", m["name"][:60], f"{m['track_number'] or 0:02d}",
                         f"{m['start']} – {m['finish']}", STATUS_LABEL.get(m["status"]),
                         (m["health"] or {}).get("label"), f"{m['percent_complete']:.0f}%", f"{m['variance_pts']:+.1f}"])
        table(s, rows, widths=[0.5, 4.5, 0.7, 2.4, 1.3, 1.4, 0.9, 0.9])

    s = prs.slides.add_slide(blank)
    title(s, "Key Support & Decisions")
    rows = [["Title", "Priority", "Status", "Owner", "Needed by"]] + \
        [[d["title"][:70], d["priority"], d["status"], d["owner"] or "", d["needed_by"] or ""] for d in dash["decisions"][:14]]
    table(s, rows, widths=[6, 1.2, 1.3, 2, 1.5])
    s = prs.slides.add_slide(blank)
    title(s, "Risk Register")
    rows = [["Severity", "Risk", "Mitigation", "Owner", "Due"]] + \
        [[r["severity"], r["title"][:60], (r["mitigation"] or "")[:80], r["owner"] or "", r["due_date"] or ""]
         for r in dash["risks"][:14]]
    table(s, rows, widths=[1.1, 4, 4.5, 1.6, 1.2])
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
