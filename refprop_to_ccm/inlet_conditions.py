from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile


_SHEET_XML_PATH = "xl/worksheets/sheet1.xml"
_SPREADSHEET_NS = {"ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_EPSILON = 1.0e-12


@dataclass(frozen=True)
class CoolantCalculationWorkbookValues:
    volume_flow_l_min: float
    mass_flow_kg_s: float
    single_plate_mass_flow_kg_s: float
    inlet_temperature_c: float
    outlet_temperature_c: float
    heat_transfer_w: float


@dataclass(frozen=True)
class CoolantInletCondition:
    single_plate_mass_flow_kg_s: float
    inlet_temperature_c: float
    heat_transfer_w: float
    volume_flow_l_min: float = 0.0
    mass_flow_kg_s: float = 0.0
    outlet_temperature_c: float = 0.0


@dataclass(frozen=True)
class RefrigerantInletCondition:
    total_mass_flow_kg_s: float
    single_layer_mass_flow_kg_s: float
    inlet_temperature_c: float
    quality: float
    vapor_volume_fraction: float
    liquid_volume_fraction: float
    starccm_volume_fraction: str
    solve_mode: str = "heat_transfer"
    heat_transfer_w: float = 0.0
    outlet_temperature_c: float = 0.0
    inlet_enthalpy_j_per_kg: float | None = None
    outlet_enthalpy_j_per_kg: float | None = None
    outlet_enthalpy_direction: str = ""


RefrigerantInletCalculation = RefrigerantInletCondition


def load_coolant_calculation_from_xlsx(path: str | Path) -> CoolantCalculationWorkbookValues:
    workbook_path = Path(path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Coolant workbook does not exist: {workbook_path}")

    with ZipFile(workbook_path) as workbook:
        try:
            sheet_xml = workbook.read(_SHEET_XML_PATH)
        except KeyError as exc:
            raise ValueError(
                f"Coolant workbook is missing expected worksheet data: {_SHEET_XML_PATH}"
            ) from exc

    root = ElementTree.fromstring(sheet_xml)
    cell_values = {
        "B17": _read_number_cell(root, "B17"),
        "D17": _read_number_cell(root, "D17"),
        "F17": _read_number_cell(root, "F17"),
        "B18": _read_number_cell(root, "B18"),
        "D18": _read_number_cell(root, "D18"),
        "F18": _read_number_cell(root, "F18"),
    }
    return CoolantCalculationWorkbookValues(
        volume_flow_l_min=cell_values["B17"],
        mass_flow_kg_s=cell_values["D17"],
        single_plate_mass_flow_kg_s=cell_values["F17"],
        inlet_temperature_c=cell_values["B18"],
        outlet_temperature_c=cell_values["D18"],
        heat_transfer_w=cell_values["F18"],
    )


def load_refrigerant_inlet_from_xlsx(path: str | Path) -> RefrigerantInletCondition:
    workbook_path = Path(path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Combined coolant/refrigerant workbook does not exist: {workbook_path}")

    with ZipFile(workbook_path) as workbook:
        try:
            sheet_xml = workbook.read(_SHEET_XML_PATH)
        except KeyError as exc:
            raise ValueError(
                f"Combined workbook is missing expected worksheet data: {_SHEET_XML_PATH}"
            ) from exc

    root = ElementTree.fromstring(sheet_xml)
    total_mass_flow = _read_number_cell(root, "D32")
    single_layer_mass_flow = _read_number_cell(root, "F32")
    inlet_temperature = _read_number_cell(root, "B29")
    outlet_temperature = _read_number_cell(root, "D29")
    heat_transfer = _read_number_cell(root, "F29")
    quality = _read_number_cell(root, "B31")
    vapor_fraction = _read_number_cell(root, "D31")
    liquid_fraction = 1.0 - vapor_fraction
    return RefrigerantInletCondition(
        total_mass_flow_kg_s=total_mass_flow,
        single_layer_mass_flow_kg_s=single_layer_mass_flow,
        inlet_temperature_c=inlet_temperature,
        quality=quality,
        vapor_volume_fraction=vapor_fraction,
        liquid_volume_fraction=liquid_fraction,
        starccm_volume_fraction=(
            f"[{_format_starccm_number(vapor_fraction)},{_format_starccm_number(liquid_fraction)}]"
        ),
        heat_transfer_w=heat_transfer,
        outlet_temperature_c=outlet_temperature,
    )


def calculate_refrigerant_inlet(
    *,
    solve_mode: str = "heat_transfer",
    heat_transfer_w: float | None = None,
    total_mass_flow_kg_s: float | None = None,
    layer_count: int,
    inlet_temperature_c: float,
    outlet_temperature_c: float = 0.0,
    inlet_enthalpy_j_per_kg: float,
    outlet_enthalpy_j_per_kg: float,
    saturated_liquid_enthalpy_j_per_kg: float,
    saturated_vapor_enthalpy_j_per_kg: float,
    saturated_liquid_density_kg_per_m3: float,
    saturated_vapor_density_kg_per_m3: float,
) -> RefrigerantInletCondition:
    inlet_temperature = _require_finite("inlet_temperature_c", inlet_temperature_c)
    outlet_temperature = _require_finite("outlet_temperature_c", outlet_temperature_c)

    normalized_solve_mode = str(solve_mode).strip().lower()
    if normalized_solve_mode not in {"heat_transfer", "mass_flow", "outlet_temperature"}:
        raise ValueError("solve_mode must be heat_transfer, mass_flow, or outlet_temperature.")

    if int(layer_count) != layer_count or layer_count <= 0:
        raise ValueError("layer_count must be a positive integer.")

    inlet_enthalpy = _require_finite("inlet_enthalpy_j_per_kg", inlet_enthalpy_j_per_kg)
    outlet_enthalpy = _require_finite("outlet_enthalpy_j_per_kg", outlet_enthalpy_j_per_kg)
    saturated_liquid_enthalpy = _require_finite(
        "saturated_liquid_enthalpy_j_per_kg", saturated_liquid_enthalpy_j_per_kg
    )
    saturated_vapor_enthalpy = _require_finite(
        "saturated_vapor_enthalpy_j_per_kg", saturated_vapor_enthalpy_j_per_kg
    )
    saturated_liquid_density = _require_positive(
        "saturated_liquid_density_kg_per_m3", saturated_liquid_density_kg_per_m3
    )
    saturated_vapor_density = _require_positive(
        "saturated_vapor_density_kg_per_m3", saturated_vapor_density_kg_per_m3
    )

    enthalpy_delta = abs(inlet_enthalpy - outlet_enthalpy)
    if enthalpy_delta <= 0.0:
        raise ValueError("abs(inlet_enthalpy_j_per_kg - outlet_enthalpy_j_per_kg) must be greater than 0.")

    latent_enthalpy = saturated_vapor_enthalpy - saturated_liquid_enthalpy
    if latent_enthalpy <= 0.0:
        raise ValueError(
            "saturated_vapor_enthalpy_j_per_kg must be greater than saturated_liquid_enthalpy_j_per_kg."
        )

    if normalized_solve_mode == "heat_transfer":
        total_heat_transfer = _require_finite("heat_transfer_w", heat_transfer_w)
        if total_heat_transfer < 0.0:
            raise ValueError("heat_transfer_w must be greater than or equal to 0.")
        total_mass_flow = total_heat_transfer / enthalpy_delta
    elif normalized_solve_mode == "mass_flow":
        total_mass_flow = _require_finite("total_mass_flow_kg_s", total_mass_flow_kg_s)
        if total_mass_flow < 0.0:
            raise ValueError("total_mass_flow_kg_s must be greater than or equal to 0.")
        total_heat_transfer = total_mass_flow * enthalpy_delta
    else:
        total_heat_transfer = _require_finite("heat_transfer_w", heat_transfer_w)
        total_mass_flow = _require_finite("total_mass_flow_kg_s", total_mass_flow_kg_s)
        if total_heat_transfer < 0.0:
            raise ValueError("heat_transfer_w must be greater than or equal to 0.")
        if total_mass_flow <= 0.0:
            raise ValueError("total_mass_flow_kg_s must be greater than 0.")

    single_layer_mass_flow = total_mass_flow / float(layer_count)
    quality = (inlet_enthalpy - saturated_liquid_enthalpy) / latent_enthalpy
    vapor_volume_fraction = _vapor_volume_fraction(
        quality=quality,
        liquid_density_kg_per_m3=saturated_liquid_density,
        vapor_density_kg_per_m3=saturated_vapor_density,
    )
    liquid_volume_fraction = 1.0 - vapor_volume_fraction

    return RefrigerantInletCondition(
        total_mass_flow_kg_s=total_mass_flow,
        single_layer_mass_flow_kg_s=single_layer_mass_flow,
        inlet_temperature_c=inlet_temperature,
        quality=quality,
        vapor_volume_fraction=vapor_volume_fraction,
        liquid_volume_fraction=liquid_volume_fraction,
        starccm_volume_fraction=(
            f"[{_format_starccm_number(vapor_volume_fraction)},{_format_starccm_number(liquid_volume_fraction)}]"
        ),
        solve_mode=normalized_solve_mode,
        heat_transfer_w=total_heat_transfer,
        outlet_temperature_c=outlet_temperature,
        inlet_enthalpy_j_per_kg=inlet_enthalpy,
        outlet_enthalpy_j_per_kg=outlet_enthalpy,
    )


def _read_number_cell(root: ElementTree.Element, cell_ref: str) -> float:
    cell = root.find(f'.//ss:c[@r="{cell_ref}"]', _SPREADSHEET_NS)
    if cell is None:
        raise ValueError(f"Coolant workbook is missing required cell {cell_ref}.")
    value_node = cell.find("ss:v", _SPREADSHEET_NS)
    if value_node is None or value_node.text is None:
        raise ValueError(f"Coolant workbook cell {cell_ref} does not contain a numeric value.")
    try:
        return _require_finite(cell_ref, float(value_node.text))
    except ValueError as exc:
        raise ValueError(f"Coolant workbook cell {cell_ref} is not a valid numeric value.") from exc


def _vapor_volume_fraction(
    *,
    quality: float,
    liquid_density_kg_per_m3: float,
    vapor_density_kg_per_m3: float,
) -> float:
    if quality <= 0.0:
        return 0.0
    if quality >= 1.0:
        return 1.0

    specific_volume_liquid = 1.0 / liquid_density_kg_per_m3
    specific_volume_vapor = 1.0 / vapor_density_kg_per_m3
    mixture_specific_volume = (
        (1.0 - quality) * specific_volume_liquid + quality * specific_volume_vapor
    )
    if mixture_specific_volume <= _EPSILON:
        raise ValueError("Calculated mixture specific volume must be greater than 0.")
    vapor_fraction = quality * specific_volume_vapor / mixture_specific_volume
    return min(max(vapor_fraction, 0.0), 1.0)


def _format_starccm_number(value: float) -> str:
    rounded = round(value)
    if math.isclose(value, rounded, rel_tol=0.0, abs_tol=1.0e-12):
        return str(int(rounded))
    return format(value, ".12g")


def _require_finite(name: str, value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite.")
    return numeric


def _require_positive(name: str, value: float) -> float:
    numeric = _require_finite(name, value)
    if numeric <= 0.0:
        raise ValueError(f"{name} must be greater than 0.")
    return numeric
