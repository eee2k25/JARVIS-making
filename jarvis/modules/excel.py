"""MS Excel automation — openpyxl file engine + Excel.Application COM app engine.

File engine (cross-platform): create, open, read sheet inventories, write
ranges, append rows, set formulas, cell formatting, charts, save — real
.xlsx artifacts via the Open XML format.
App engine (Windows + MS Excel): open the workbook in the real Excel UI and
export to PDF through Excel.Application. Shadows to dry-run logs elsewhere.
"""

from __future__ import annotations

from pathlib import Path

from ..exceptions import ActionError
from ..logging_setup import get_logger
from .office import OfficeModule

log = get_logger("jarvis.excel")

_CHART_KINDS = {"bar", "line", "pie"}


class ExcelModule(OfficeModule):
    name = "excel"
    progid = "Excel.Application"
    file_module = "openpyxl"
    app_label = "MS Excel"

    # ── engine plumbing ──────────────────────────────────────────────────
    def _xl(self):
        self.require_real()
        import openpyxl

        return openpyxl

    def _ensure_wb(self):
        if self._doc is None:
            self._doc = self._xl().Workbook()
        return self._doc

    def _ws(self, sheet: str | None = None):
        wb = self._ensure_wb()
        if sheet is None:
            return wb.active
        if sheet not in wb.sheetnames:
            raise ActionError(f"excel: no sheet named {sheet!r} "
                              f"(have: {wb.sheetnames})")
        return wb[sheet]

    # ── file engine: lifecycle ───────────────────────────────────────────
    def create(self, path: str | None = None, title: str | None = None,
               sheet: str | None = None) -> dict:
        """Rebuild a fresh workbook (blueprint semantics: replace, not append)."""
        if self.dry_run:
            return self.shadow("create", path=path, title=title, sheet=sheet)
        wb = self._xl().Workbook()
        wb.active.title = sheet or "Sheet1"
        if title:
            wb.properties.title = title
        self._doc = wb
        self._path = Path(path) if path else None
        return {"created": str(self._path) if self._path else "(unsaved)",
                "title": title, "sheet": wb.active.title}

    def open(self, path: str) -> dict:
        if self.dry_run:
            return self.shadow("open", path=path)
        p = Path(path).expanduser()
        if not p.exists():
            raise ActionError(f"excel: workbook not found: {p}")
        self._doc = self._xl().load_workbook(str(p))
        self._path = p
        return {"opened": str(p), "sheets": self._doc.sheetnames}

    def save(self, path: str | None = None) -> dict:
        if self.dry_run:
            return self.shadow("save", path=path)
        if self._doc is None:
            raise ActionError("excel.save: no workbook open or created")
        p = self._target_path(path, suffix=".xlsx")
        p.parent.mkdir(parents=True, exist_ok=True)
        self._doc.save(str(p))
        self._path = p
        log.info("saved %s (%d bytes)", p, p.stat().st_size)
        return {"saved": str(p), "bytes": p.stat().st_size}

    # ── file engine: inspection ──────────────────────────────────────────
    def read(self, sheet: str | None = None, max_rows: int = 50) -> dict:
        """Sheet inventory: dims, rows, and every formula cell."""
        if self.dry_run:
            return self.shadow("read", sheet=sheet, max_rows=max_rows)
        ws = self._ws(sheet)
        wb = self._ensure_wb()
        rows: list[list] = []
        formulas: dict[str, str] = {}
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row or 1, max_rows)):
            values = []
            for cell in row:
                value = cell.value
                if isinstance(value, str) and value.startswith("="):
                    formulas[cell.coordinate] = value
                values.append(value)
            rows.append(values)
        return {
            "path": str(self._path) if self._path else None,
            "title": wb.properties.title or "",
            "sheets": wb.sheetnames,
            "active": ws.title,
            "max_row": ws.max_row or 0,
            "max_column": ws.max_column or 0,
            "rows": rows,
            "formulas": formulas,
        }

    # ── file engine: editing ─────────────────────────────────────────────
    def write(self, start: str = "A1", rows: list[list] | None = None,
              sheet: str | None = None) -> dict:
        """Write a 2-D block anchored at the start cell (e.g. start='B3')."""
        if self.dry_run:
            return self.shadow("write", start=start, rows=rows, sheet=sheet)
        if not rows:
            raise ActionError("excel.write: rows must be a non-empty block")
        from openpyxl.utils.cell import coordinate_to_tuple

        try:
            row0, col0 = coordinate_to_tuple(start)
        except Exception as exc:
            raise ActionError(f"excel.write: bad anchor cell {start!r}") from exc
        ws = self._ws(sheet)
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                if value is not None:
                    ws.cell(row=row0 + i, column=col0 + j, value=value)
        return {"wrote": f"{len(rows)}x{max(len(r) for r in rows)}",
                "start": start, "sheet": ws.title}

    def append_rows(self, rows: list[list] | None = None,
                    sheet: str | None = None) -> dict:
        if self.dry_run:
            return self.shadow("append_rows", rows=rows, sheet=sheet)
        if not rows:
            raise ActionError("excel.append_rows: rows must be non-empty")
        ws = self._ws(sheet)
        for row in rows:
            ws.append(list(row))
        return {"appended": len(rows), "max_row": ws.max_row, "sheet": ws.title}

    def set_formula(self, cell: str, formula: str,
                    sheet: str | None = None) -> dict:
        if self.dry_run:
            return self.shadow("set_formula", cell=cell, formula=formula,
                               sheet=sheet)
        if not formula.startswith("="):
            formula = "=" + formula
        ws = self._ws(sheet)
        try:
            ws[cell] = formula
        except Exception as exc:
            raise ActionError(f"excel.set_formula: bad cell {cell!r}") from exc
        return {"formula_cell": cell, "formula": formula, "sheet": ws.title}

    def format(self, target: str = "A1", bold: bool | None = None,
               italic: bool | None = None, number_format: str | None = None,
               fill: str | None = None, col_width: float | None = None,
               sheet: str | None = None) -> dict:
        """Style a range: font flags, number format, solid fill, column widths.

        fill accepts an ARGB/RGB hex string such as 'FF2060' or '2060FFAA'.
        """
        if self.dry_run:
            return self.shadow("format", target=target, bold=bold, italic=italic,
                               number_format=number_format, fill=fill,
                               col_width=col_width, sheet=sheet)
        from copy import copy

        from openpyxl.styles import PatternFill
        from openpyxl.utils.cell import get_column_letter, range_boundaries

        try:
            min_col, min_row, max_col, max_row = range_boundaries(target)
        except Exception as exc:
            raise ActionError(f"excel.format: bad range {target!r}") from exc
        ws = self._ws(sheet)
        for row in ws.iter_rows(min_row=min_row, max_row=max_row,
                                min_col=min_col, max_col=max_col):
            for cell in row:
                if bold is not None or italic is not None:
                    font = copy(cell.font)
                    if bold is not None:
                        font.bold = bool(bold)
                    if italic is not None:
                        font.italic = bool(italic)
                    cell.font = font
                if number_format:
                    cell.number_format = number_format
                if fill:
                    cell.fill = PatternFill("solid", fgColor=fill)
        if col_width:
            for col in range(min_col, max_col + 1):
                ws.column_dimensions[get_column_letter(col)].width = float(col_width)
        return {"formatted": target, "sheet": ws.title, "bold": bold,
                "number_format": number_format, "fill": fill}

    def add_chart(self, kind: str = "bar", title: str = "",
                  data_ref: str = "", cats_ref: str = "",
                  anchor: str = "F2", sheet: str | None = None) -> dict:
        """Attach a bar/line/pie chart from range refs like 'B1:B5'."""
        if self.dry_run:
            return self.shadow("add_chart", kind=kind, title=title,
                               data_ref=data_ref, cats_ref=cats_ref,
                               anchor=anchor, sheet=sheet)
        kind = kind.lower()
        if kind not in _CHART_KINDS:
            raise ActionError(f"excel.add_chart: kind must be one of "
                              f"{sorted(_CHART_KINDS)}")
        if not data_ref:
            raise ActionError("excel.add_chart: data_ref is required")
        from openpyxl.chart import BarChart, LineChart, PieChart, Reference
        from openpyxl.utils.cell import range_boundaries

        ws = self._ws(sheet)

        def ref(spec: str) -> Reference:
            min_col, min_row, max_col, max_row = range_boundaries(spec)
            return Reference(ws, min_col=min_col, min_row=min_row,
                             max_col=max_col, max_row=max_row)

        chart = {"bar": BarChart, "line": LineChart, "pie": PieChart}[kind]()
        chart.add_data(ref(data_ref), titles_from_data=True)
        if cats_ref:
            chart.set_categories(ref(cats_ref))
        if title:
            chart.title = title
        ws.add_chart(chart, anchor)
        return {"chart": kind, "title": title, "data_ref": data_ref,
                "anchor": anchor, "sheet": ws.title}

    # ── app engine: real MS Excel (COM) ──────────────────────────────────
    def export_pdf(self, path: str | None = None) -> dict:
        """Export the active worksheet to PDF through real MS Excel."""
        target = self._target_path(path).with_suffix(".pdf")
        sh = self.app_shadow("export_pdf", path=str(target))
        if sh is not None:
            return sh
        if self._path is None:
            raise ActionError("excel.export_pdf: save the workbook first")
        app = self._app()
        app.Visible = False
        wb = app.Workbooks.Open(self._abs(self._path))
        try:
            wb.ExportAsFixedFormat(0, self._abs(target))  # 0 = xlTypePDF
        finally:
            wb.Close(False)
        return {"exported_pdf": str(target), "bytes": target.stat().st_size}

    def launch(self, path: str | None = None) -> dict:
        """Open the workbook in the real MS Excel application window."""
        p = self._target_path(path, suffix=".xlsx")
        sh = self.app_shadow("launch", path=str(p))
        if sh is not None:
            return sh
        app = self._app()
        app.Visible = True
        app.Workbooks.Open(self._abs(p))
        return {"launched": str(p), "app": self.progid}
