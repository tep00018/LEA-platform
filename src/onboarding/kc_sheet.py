"""The KC model as a spreadsheet (XLSX) for teachers who prefer to edit in Excel.

Export: an "Objectives" sheet, one row per granular objective, with the ID columns and
the source excerpt locked (the sheet is protected without a password; it is a guard
against slips, not security), 200 empty unlocked rows for new objectives, and a "Read me"
sheet with the rules. Import reads it back into rows; LEA validates them before anything
becomes a draft.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.worksheet.datavalidation import DataValidation

from src.onboarding.kc_model import BLOOM, THRESHOLD_RANGE

COLUMNS = [  # (header, row field, width, locked for existing rows)
    ("GO ID", "go_id", 16, True),
    ("Week", "week", 7, False),
    ("Week title", "week_title", 28, False),
    ("LO ID", "lo_id", 12, True),
    ("Learning objective", "lo_title", 50, False),
    ("Short title", "lo_short_title", 24, False),
    ("Objective name", "skill_name", 32, False),
    ("Description", "description", 60, False),
    ("Bloom level", "cognitive_level", 12, False),
    ("Mastery threshold", "mastery_threshold", 10, False),
    ("Keywords", "keywords", 30, False),
    ("Prerequisites (GO IDs)", "prerequisites", 30, False),
    ("Other prerequisites", "prerequisite_notes", 30, False),
    ("Split from (GO ID)", "split_from", 16, False),
    ("Merged from (GO IDs)", "merged_from", 22, False),
    ("Source excerpt", "provenance", 50, True),
]
LISTS = {"keywords", "prerequisites", "prerequisite_notes", "merged_from"}
EMPTY_ROWS = 200

README = [
    "How to edit this KC model",
    "",
    "One row is one granular objective. Rows with the same LO ID (or, for a new learning objective, the same week and "
    "learning objective text) belong to one learning objective.",
    "Don't change the GO ID or LO ID columns: LEA assigns IDs. Leave them blank for new rows.",
    "To add an objective: fill in a row at the bottom with the GO ID blank. To add it to an existing learning "
    "objective, copy that objective's LO ID into the row.",
    "To remove an objective: delete its row. Its ID is retired, never reused, and students' mastery on it is kept but "
    "no longer counted.",
    "To split an objective: delete its row and add the new parts with its GO ID in 'Split from'. Students keep their "
    "mastery on each part.",
    "To merge objectives: delete their rows and add one new row listing their GO IDs in 'Merged from', separated by "
    "commas. Students get the average of their mastery.",
    f"Bloom level: one of {', '.join(BLOOM)}. Mastery threshold: {THRESHOLD_RANGE[0]} to {THRESHOLD_RANGE[1]}.",
    "Keywords, prerequisites and 'Merged from' are comma-separated. Prerequisites are GO IDs from this sheet; "
    "'Other prerequisites' is free text for anything that isn't an objective here.",
    "Importing shows every change and any problem before it becomes a draft. Nothing is published until you publish.",
]


def export_xlsx(rows: List[Dict[str, Any]], course: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Objectives"
    header_fill = PatternFill("solid", fgColor="2E5A47")
    locked_fill = PatternFill("solid", fgColor="E2E9E0")
    for c, (header, _, width, _) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=c, value=header)
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), header_fill
        ws.column_dimensions[cell.column_letter].width = width
    for r, row in enumerate(rows, 2):
        for c, (_, field, _, locked) in enumerate(COLUMNS, 1):
            value = row.get(field)
            if field == "provenance":
                value = (value or {}).get("excerpt", "") if isinstance(value, dict) else ""
            elif field in LISTS:
                value = ", ".join(value or [])
            cell = ws.cell(row=r, column=c, value=value)
            cell.protection = Protection(locked=locked)
            cell.alignment = Alignment(wrap_text=field in ("description", "lo_title", "provenance"), vertical="top")
            if locked:
                cell.fill = locked_fill
    for r in range(len(rows) + 2, len(rows) + 2 + EMPTY_ROWS):
        for c, (_, field, _, _) in enumerate(COLUMNS, 1):
            ws.cell(row=r, column=c).protection = Protection(locked=field in ("go_id", "provenance"))
    last = len(rows) + 1 + EMPTY_ROWS
    levels = DataValidation(type="list", formula1='"' + ",".join(BLOOM) + '"', allow_blank=True)
    levels.add(f"I2:I{last}")
    threshold = DataValidation(type="decimal", operator="between", formula1=str(THRESHOLD_RANGE[0]),
                               formula2=str(THRESHOLD_RANGE[1]), allow_blank=True)
    threshold.add(f"J2:J{last}")
    ws.add_data_validation(levels)
    ws.add_data_validation(threshold)
    ws.freeze_panes = "B2"
    ws.protection.sheet = True
    ws.protection.formatRows = ws.protection.insertRows = ws.protection.deleteRows = False
    ws.protection.formatColumns = ws.protection.autoFilter = ws.protection.sort = False

    notes = wb.create_sheet("Read me")
    notes.column_dimensions["A"].width = 120
    for i, line in enumerate([f"{course}: KC model"] + README, 1):
        cell = notes.cell(row=i, column=1, value=line)
        cell.alignment = Alignment(wrap_text=True)
        if i <= 2:
            cell.font = Font(bold=True, size=13 if i == 1 else 11)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def import_xlsx(data: bytes) -> List[Dict[str, Any]]:
    """Rows from an exported (and edited) sheet. Raises ValueError with a readable message
    if it isn't one."""
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception:
        raise ValueError("That isn't an Excel (.xlsx) file.") from None
    if "Objectives" not in wb.sheetnames:
        raise ValueError("The workbook has no 'Objectives' sheet. Start from an exported file.")
    ws = wb["Objectives"]
    headers = [str(c.value or "").strip() for c in ws[1]]
    index = {header: headers.index(header) for header, *_ in COLUMNS if header in headers}
    missing = [h for h, *_ in COLUMNS if h not in index and h != "Source excerpt"]
    if missing:
        raise ValueError(f"Missing column(s): {', '.join(missing)}. Start from an exported file.")
    rows = []
    for values in ws.iter_rows(min_row=2, values_only=True):
        if not any(v not in (None, "") for v in values):
            continue
        row: Dict[str, Any] = {}
        for header, field, *_ in COLUMNS:
            if field == "provenance" or header not in index:
                continue
            value = values[index[header]] if index[header] < len(values) else None
            if field in LISTS:
                row[field] = [p.strip() for p in str(value or "").split(",") if p.strip()]
            elif field in ("week",):
                row[field] = int(value) if isinstance(value, (int, float)) or str(value or "").strip().isdigit() else value
            elif field == "mastery_threshold":
                row[field] = value
            else:
                row[field] = str(value).strip() if value is not None else ""
        row["go_id"] = row.get("go_id") or None
        row["lo_id"] = row.get("lo_id") or None
        row["split_from"] = row.get("split_from") or None
        rows.append(row)
    if not rows:
        raise ValueError("The sheet has no objectives.")
    return rows
