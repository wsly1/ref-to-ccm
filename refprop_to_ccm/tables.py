from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .models import CoolantCalculation, CoolantRow, LiquidProperties, LiquidRow, VaporRow


PROPERTY_HEADERS = [
    "Temperature (C)",
    "Density (kg/m3)",
    "Equivalent Specific Heat (J/kg-K)",
    "Equivalent Thermal Conductivity (W/m-K)",
    "Equivalent Dynamic Viscosity (Pa-s)",
    "Enthalpy (J/kg)",
]

COOLANT_TABLE_TITLE = "防冻液物性参数"
COOLANT_TABLE_HEADERS = (
    "温度",
    "密度（kg/m3）",
    "比热(J/kg.K)",
    "导热系数(W/m.K)",
    "动力粘度（kg/m·s）",
)
COOLANT_COLUMN_WIDTHS = (
    (1, 1, 14.0),
    (2, 2, 14.0),
    (3, 3, 18.0),
    (4, 4, 18.0),
    (5, 5, 18.0),
    (6, 6, 18.0),
)


def write_liquid_json(path: Path, liquid: LiquidProperties) -> None:
    path.write_text(json.dumps(liquid.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")


def write_summary_json(path: Path, summary: dict) -> None:
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def write_vapor_csv(path: Path, rows: list[VaporRow]) -> None:
    _write_property_csv(path, rows)


def write_liquid_csv(path: Path, rows: list[LiquidRow]) -> None:
    _write_property_csv(path, rows)


def write_coolant_xlsx(
    path: Path,
    row: CoolantRow,
    calculation: CoolantCalculation | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", _content_types_xml())
        workbook.writestr("_rels/.rels", _root_rels_xml())
        workbook.writestr("docProps/app.xml", _app_xml())
        workbook.writestr("docProps/core.xml", _core_xml())
        workbook.writestr("xl/workbook.xml", _workbook_xml())
        workbook.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
        workbook.writestr("xl/styles.xml", _styles_xml())
        workbook.writestr("xl/worksheets/sheet1.xml", _coolant_sheet_xml(row, calculation))


def _write_property_csv(path: Path, rows: list[VaporRow] | list[LiquidRow]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(PROPERTY_HEADERS)
        for row in rows:
            writer.writerow(
                [
                    f"{row.temperature_c:.8g}",
                    f"{row.density_kg_per_m3:.10g}",
                    f"{row.equivalent_specific_heat_j_per_kg_k:.10g}",
                    f"{row.equivalent_thermal_conductivity_w_per_m_k:.10g}",
                    f"{row.equivalent_dynamic_viscosity_pa_s:.10g}",
                    f"{row.enthalpy_j_per_kg:.10g}",
                ]
            )


def _coolant_sheet_xml(row: CoolantRow, calculation: CoolantCalculation | None) -> str:
    calculated = calculation or CoolantCalculation(
        row=row,
        solve_mode="heat",
        volume_flow_l_min=0.0,
        mass_flow_kg_s=0.0,
        single_plate_mass_flow_kg_s=0.0,
        inlet_temperature_c=0.0,
        outlet_temperature_c=0.0,
        heat_transfer_w=0.0,
    )
    header_cells = [
        _inline_str_cell("A15", COOLANT_TABLE_HEADERS[0], style=2),
        _inline_str_cell("B15", COOLANT_TABLE_HEADERS[1], style=2),
        _inline_str_cell("C15", COOLANT_TABLE_HEADERS[2], style=2),
        _inline_str_cell("D15", COOLANT_TABLE_HEADERS[3], style=2),
        _inline_str_cell("E15", COOLANT_TABLE_HEADERS[4], style=2),
        _blank_cell("F15", style=2),
    ]
    value_cells = [
        _number_cell("A16", row.temperature_c, style=2),
        _number_cell("B16", row.density_kg_per_m3, style=2),
        _number_cell("C16", row.specific_heat_j_per_kg_k, style=2),
        _number_cell("D16", row.thermal_conductivity_w_per_m_k, style=2),
        _number_cell("E16", row.dynamic_viscosity_kg_per_m_s, style=2),
        _blank_cell("F16", style=2),
    ]
    flow_cells = [
        _inline_str_cell("A17", "体积流量 (L/min)", style=2),
        _number_cell("B17", calculated.volume_flow_l_min, style=2),
        _inline_str_cell("C17", "质量流量 (kg/s)", style=2),
        _number_cell("D17", calculated.mass_flow_kg_s, style=2),
        _inline_str_cell("E17", "单片质量流量 (kg/s)", style=2),
        _number_cell("F17", calculated.single_plate_mass_flow_kg_s, style=2),
    ]
    thermal_cells = [
        _inline_str_cell("A18", "入口温度", style=2),
        _number_cell("B18", calculated.inlet_temperature_c, style=2),
        _inline_str_cell("C18", "出口温度", style=2),
        _number_cell("D18", calculated.outlet_temperature_c, style=2),
        _inline_str_cell("E18", "计算换热量", style=2),
        _number_cell("F18", calculated.heat_transfer_w, style=2),
    ]
    rows = {
        14: [
            _inline_str_cell("A14", COOLANT_TABLE_TITLE, style=1),
            _blank_cell("B14", style=1),
            _blank_cell("C14", style=1),
            _blank_cell("D14", style=1),
            _blank_cell("E14", style=1),
            _blank_cell("F14", style=1),
        ],
        15: header_cells,
        16: value_cells,
        17: flow_cells,
        18: thermal_cells,
    }
    sheet_rows = "".join(
        f'<row r="{index}">{"".join(cells)}</row>' for index, cells in rows.items()
    )
    columns_xml = "".join(
        f'<col min="{min_col}" max="{max_col}" width="{width}" customWidth="1"/>'
        for min_col, max_col, width in COOLANT_COLUMN_WIDTHS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="A14:F18"/>'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultColWidth="9" defaultRowHeight="13.5"/>'
        '<cols>'
        f"{columns_xml}"
        '</cols>'
        '<sheetData>'
        f"{sheet_rows}"
        "</sheetData>"
        '<mergeCells count="1"><mergeCell ref="A14:F14"/></mergeCells>'
        "</worksheet>"
    )


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _app_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Microsoft Excel</Application>"
        "</Properties>"
    )


def _core_xml() -> str:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:creator>refprop-to-ccm</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _workbook_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )


def _workbook_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="宋体"/></font>'
        '<font><b/><sz val="11"/><name val="宋体"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFF4B382"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


def _inline_str_cell(cell_ref: str, value: str, style: int | None = None) -> str:
    style_attr = _style_attr(style)
    return f'<c r="{cell_ref}"{style_attr} t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def _number_cell(cell_ref: str, value: float, style: int | None = None) -> str:
    return f'<c r="{cell_ref}"{_style_attr(style)}><v>{format(value, ".15g")}</v></c>'


def _blank_cell(cell_ref: str, style: int | None = None) -> str:
    return f'<c r="{cell_ref}"{_style_attr(style)}/>'


def _style_attr(style: int | None) -> str:
    if style is None:
        return ""
    return f' s="{style}"'
