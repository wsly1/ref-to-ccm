from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .inlet_conditions import RefrigerantInletCondition
from .models import CoolantCalculation, CoolantRow, LiquidProperties, LiquidRow, VaporRow


REPORT_TABLE_HEADERS = (
    "报告名称",
    "类型",
    "数值",
    "单位",
)
REPORT_COLUMN_WIDTHS = (
    (1, 1, 24.0),
    (2, 2, 24.0),
    (3, 3, 18.0),
    (4, 4, 14.0),
)


PROPERTY_HEADERS = [
    "Temperature (C)",
    "Density (kg/m^3)",
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
REFRIGERANT_TABLE_TITLE = "制冷剂物性参数"
REFRIGERANT_PROPERTY_HEADERS = (
    "相态",
    "密度(kg/m3)",
    "比热(J/kg.K)",
    "导热系数(W/m.K)",
    "动力粘度(Pa.s)",
    "焓值(J/kg)",
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
    refrigerant: RefrigerantInletCondition | None = None,
    saturated_liquid_row: LiquidRow | None = None,
    saturated_vapor_row: VaporRow | None = None,
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
        workbook.writestr(
            "xl/worksheets/sheet1.xml",
            _coolant_sheet_xml(
                row,
                calculation,
                refrigerant=refrigerant,
                saturated_liquid_row=saturated_liquid_row,
                saturated_vapor_row=saturated_vapor_row,
            ),
        )


def write_report_xlsx(
    path: Path,
    reports: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", _content_types_xml())
        workbook.writestr("_rels/.rels", _root_rels_xml())
        workbook.writestr("docProps/app.xml", _app_xml())
        workbook.writestr("docProps/core.xml", _core_xml())
        workbook.writestr("xl/workbook.xml", _workbook_xml())
        workbook.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
        workbook.writestr("xl/styles.xml", _report_styles_xml())
        workbook.writestr("xl/worksheets/sheet1.xml", _report_sheet_xml(reports))


def _sig4(value: float) -> str:
    return f"{value:.4g}"


def _report_sheet_xml(reports: list[dict[str, object]]) -> str:
    rows_xml: dict[int, list[str]] = {}
    rows_xml[1] = [
        _inline_str_cell("A1", REPORT_TABLE_HEADERS[0], style=1),
        _inline_str_cell("B1", REPORT_TABLE_HEADERS[1], style=1),
        _inline_str_cell("C1", REPORT_TABLE_HEADERS[2], style=1),
        _inline_str_cell("D1", REPORT_TABLE_HEADERS[3], style=1),
    ]
    for idx, report in enumerate(reports, start=2):
        name = str(report.get("name", ""))
        report_type = str(report.get("report_type", ""))
        value = report.get("value")
        units = str(report.get("units", ""))
        if isinstance(value, (int, float)) and value is not None:
            value_cell = _number_cell(f"C{idx}", float(_sig4(float(value))), style=2)
        else:
            raw = str(report.get("raw_value", "N/A"))
            value_cell = _inline_str_cell(f"C{idx}", raw, style=2)
        rows_xml[idx] = [
            _inline_str_cell(f"A{idx}", name, style=2),
            _inline_str_cell(f"B{idx}", report_type, style=2),
            value_cell,
            _inline_str_cell(f"D{idx}", units, style=2),
        ]
    last_row = len(reports) + 1
    dimension_ref = f"A1:D{last_row}"
    columns_xml = "".join(
        f'<col min="{min_col}" max="{max_col}" width="{width}" customWidth="1"/>'
        for min_col, max_col, width in REPORT_COLUMN_WIDTHS
    )
    sheet_rows = "".join(
        f'<row r="{index}">{"".join(cells)}</row>' for index, cells in rows_xml.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension_ref}"/>'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultColWidth="9" defaultRowHeight="13.5"/>'
        '<cols>'
        f"{columns_xml}"
        '</cols>'
        '<sheetData>'
        f"{sheet_rows}"
        "</sheetData>"
        "</worksheet>"
    )


def _report_styles_xml() -> str:
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
        '<fill><patternFill patternType="solid"><fgColor rgb="FFD9E2F3"/><bgColor indexed="64"/></patternFill></fill>'
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


def _coolant_sheet_xml(
    row: CoolantRow,
    calculation: CoolantCalculation | None,
    *,
    refrigerant: RefrigerantInletCondition | None,
    saturated_liquid_row: LiquidRow | None,
    saturated_vapor_row: VaporRow | None,
) -> str:
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
    merge_refs = ["A14:F14"]
    dimension_ref = "A14:F18"

    if (
        refrigerant is not None
        and saturated_liquid_row is not None
        and saturated_vapor_row is not None
    ):
        rows.update(_refrigerant_rows(refrigerant, saturated_liquid_row, saturated_vapor_row))
        merge_refs.append("A25:F25")
        dimension_ref = "A14:F32"

    sheet_rows = "".join(
        f'<row r="{index}">{"".join(cells)}</row>' for index, cells in rows.items()
    )
    columns_xml = "".join(
        f'<col min="{min_col}" max="{max_col}" width="{width}" customWidth="1"/>'
        for min_col, max_col, width in COOLANT_COLUMN_WIDTHS
    )
    merge_cells_xml = "".join(f'<mergeCell ref="{merge_ref}"/>' for merge_ref in merge_refs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension_ref}"/>'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultColWidth="9" defaultRowHeight="13.5"/>'
        '<cols>'
        f"{columns_xml}"
        '</cols>'
        '<sheetData>'
        f"{sheet_rows}"
        "</sheetData>"
        f'<mergeCells count="{len(merge_refs)}">{merge_cells_xml}</mergeCells>'
        "</worksheet>"
    )


def _refrigerant_rows(
    refrigerant: RefrigerantInletCondition,
    saturated_liquid_row: LiquidRow,
    saturated_vapor_row: VaporRow,
) -> dict[int, list[str]]:
    mass_flow_kg_h = refrigerant.total_mass_flow_kg_s * 3600.0
    return {
        25: [
            _inline_str_cell("A25", REFRIGERANT_TABLE_TITLE, style=1),
            _blank_cell("B25", style=1),
            _blank_cell("C25", style=1),
            _blank_cell("D25", style=1),
            _blank_cell("E25", style=1),
            _blank_cell("F25", style=1),
        ],
        26: [
            _inline_str_cell("A26", REFRIGERANT_PROPERTY_HEADERS[0], style=2),
            _inline_str_cell("B26", REFRIGERANT_PROPERTY_HEADERS[1], style=2),
            _inline_str_cell("C26", REFRIGERANT_PROPERTY_HEADERS[2], style=2),
            _inline_str_cell("D26", REFRIGERANT_PROPERTY_HEADERS[3], style=2),
            _inline_str_cell("E26", REFRIGERANT_PROPERTY_HEADERS[4], style=2),
            _inline_str_cell("F26", REFRIGERANT_PROPERTY_HEADERS[5], style=2),
        ],
        27: _refrigerant_property_row("27", "饱和液相", saturated_liquid_row),
        28: _refrigerant_property_row("28", "饱和气相", saturated_vapor_row),
        29: [
            _inline_str_cell("A29", "入口温度(C)", style=2),
            _number_cell("B29", refrigerant.inlet_temperature_c, style=2),
            _inline_str_cell("C29", "出口温度(C)", style=2),
            _number_cell("D29", refrigerant.outlet_temperature_c, style=2),
            _inline_str_cell("E29", "换热量(W)", style=2),
            _number_cell("F29", refrigerant.heat_transfer_w, style=2),
        ],
        30: [
            _inline_str_cell("A30", "入口焓(J/kg)", style=2),
            _number_cell("B30", _optional_number(refrigerant.inlet_enthalpy_j_per_kg), style=2),
            _inline_str_cell("C30", "出口焓(J/kg)", style=2),
            _number_cell("D30", _optional_number(refrigerant.outlet_enthalpy_j_per_kg), style=2),
            _inline_str_cell("E30", "求解模式", style=2),
            _inline_str_cell("F30", refrigerant.solve_mode, style=2),
        ],
        31: [
            _inline_str_cell("A31", "干度", style=2),
            _number_cell("B31", refrigerant.quality, style=2),
            _inline_str_cell("C31", "气相体积分数", style=2),
            _number_cell("D31", refrigerant.vapor_volume_fraction, style=2),
            _inline_str_cell("E31", "StarCCM+", style=2),
            _inline_str_cell("F31", refrigerant.starccm_volume_fraction, style=2),
        ],
        32: [
            _inline_str_cell("A32", "质量流量(kg/h)", style=2),
            _number_cell("B32", mass_flow_kg_h, style=2),
            _inline_str_cell("C32", "质量流量(kg/s)", style=2),
            _number_cell("D32", refrigerant.total_mass_flow_kg_s, style=2),
            _inline_str_cell("E32", "单层质量流量(kg/s)", style=2),
            _number_cell("F32", refrigerant.single_layer_mass_flow_kg_s, style=2),
        ],
    }


def _refrigerant_property_row(
    row_number: str,
    phase_label: str,
    row: LiquidRow | VaporRow,
) -> list[str]:
    return [
        _inline_str_cell(f"A{row_number}", phase_label, style=2),
        _number_cell(f"B{row_number}", row.density_kg_per_m3, style=2),
        _number_cell(f"C{row_number}", row.equivalent_specific_heat_j_per_kg_k, style=2),
        _number_cell(f"D{row_number}", row.equivalent_thermal_conductivity_w_per_m_k, style=2),
        _number_cell(f"E{row_number}", row.equivalent_dynamic_viscosity_pa_s, style=2),
        _number_cell(f"F{row_number}", row.enthalpy_j_per_kg, style=2),
    ]


def _optional_number(value: float | None) -> float:
    if value is None:
        return 0.0
    return value


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
