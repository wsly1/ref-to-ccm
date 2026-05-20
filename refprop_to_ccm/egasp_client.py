from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from types import ModuleType

from .models import CoolantCalculation, CoolantRow


class EgaspClientError(RuntimeError):
    """Raised when the local EGASP adapter cannot return usable property data."""


def build_coolant_row(
    temperature_c: float,
    query_type: str = "volume",
    query_value: float = 0.5,
    egasp_root: Path | None = None,
) -> CoolantRow:
    egasp = _load_egasp_class(egasp_root)()
    try:
        result = egasp.props(
            query_temp=float(temperature_c),
            query_type=str(query_type),
            query_value=float(query_value),
        )
    except SystemExit as exc:
        raise EgaspClientError("EGASP exited while calculating coolant properties.") from exc
    except Exception as exc:
        raise EgaspClientError(f"EGASP calculation failed: {exc}") from exc

    if len(result) != 8:
        raise EgaspClientError(f"EGASP returned {len(result)} values, expected 8.")

    mass, volume, freezing, boiling, rho, cp, k, mu = result
    values = {
        "mass_fraction": mass,
        "volume_fraction": volume,
        "density_kg_per_m3": rho,
        "specific_heat_j_per_kg_k": cp,
        "thermal_conductivity_w_per_m_k": k,
        "dynamic_viscosity_kg_per_m_s": mu,
    }
    missing = [name for name, value in values.items() if value is None]
    if missing:
        raise EgaspClientError(f"EGASP returned missing data for: {', '.join(missing)}.")

    return CoolantRow(
        temperature_c=_require_finite("temperature_c", temperature_c),
        density_kg_per_m3=_require_finite("density_kg_per_m3", rho),
        specific_heat_j_per_kg_k=_require_finite("specific_heat_j_per_kg_k", cp),
        thermal_conductivity_w_per_m_k=_require_finite("thermal_conductivity_w_per_m_k", k),
        dynamic_viscosity_kg_per_m_s=_require_finite("dynamic_viscosity_kg_per_m_s", mu),
        mass_fraction=_optional_finite("mass_fraction", mass),
        volume_fraction=_optional_finite("volume_fraction", volume),
        freezing_point_c=_optional_finite("freezing_point_c", freezing),
        boiling_point_c=_optional_finite("boiling_point_c", boiling),
    )


def build_coolant_calculation(
    row: CoolantRow,
    *,
    solve_mode: str,
    inlet_temperature_c: float,
    outlet_direction: str = "heating",
    volume_flow_l_min: float | None = None,
    outlet_temperature_c: float | None = None,
    heat_transfer_w: float | None = None,
    plate_count: int = 32,
) -> CoolantCalculation:
    inlet = _require_finite("inlet_temperature_c", inlet_temperature_c)
    direction = str(outlet_direction)
    if direction not in {"heating", "cooling"}:
        raise EgaspClientError(
            f"Unsupported coolant outlet direction: {outlet_direction}. "
            "Expected heating or cooling."
        )

    if plate_count <= 0:
        raise EgaspClientError("coolant plate count must be greater than 0.")

    solve = str(solve_mode)
    density = row.density_kg_per_m3
    specific_heat = row.specific_heat_j_per_kg_k

    if solve == "heat":
        volume_flow = _require_finite_arg("volume_flow_l_min", volume_flow_l_min)
        outlet = _require_finite_arg("outlet_temperature_c", outlet_temperature_c)
        _require_positive("volume_flow_l_min", volume_flow)
        mass_flow = _mass_flow_kg_s(volume_flow, density)
        heat_transfer = _heat_transfer_w(mass_flow, specific_heat, inlet, outlet)
    elif solve == "outlet-temperature":
        volume_flow = _require_finite_arg("volume_flow_l_min", volume_flow_l_min)
        required_heat = _require_finite_arg("heat_transfer_w", heat_transfer_w)
        _require_positive("volume_flow_l_min", volume_flow)
        _require_non_negative("heat_transfer_w", required_heat)
        mass_flow = _mass_flow_kg_s(volume_flow, density)
        delta_t = required_heat / (mass_flow * specific_heat)
        if direction == "cooling":
            outlet = inlet - delta_t
        else:
            outlet = inlet + delta_t
        heat_transfer = required_heat
    elif solve == "volume-flow":
        required_heat = _require_finite_arg("heat_transfer_w", heat_transfer_w)
        outlet = _require_finite_arg("outlet_temperature_c", outlet_temperature_c)
        _require_non_negative("heat_transfer_w", required_heat)
        delta_t = abs(outlet - inlet)
        if delta_t == 0:
            raise EgaspClientError(
                "Cannot solve coolant volume flow when inlet and outlet temperatures are equal."
            )
        volume_flow = required_heat / (density * specific_heat * delta_t) * 1000.0 * 60.0
        mass_flow = _mass_flow_kg_s(volume_flow, density)
        heat_transfer = required_heat
    else:
        raise EgaspClientError(
            f"Unsupported coolant solve mode: {solve_mode}. "
            "Expected heat, outlet-temperature, or volume-flow."
        )

    return CoolantCalculation(
        row=row,
        solve_mode=solve,
        volume_flow_l_min=_require_finite("volume_flow_l_min", volume_flow),
        mass_flow_kg_s=_require_finite("mass_flow_kg_s", mass_flow),
        single_plate_mass_flow_kg_s=_require_finite(
            "single_plate_mass_flow_kg_s", mass_flow / float(plate_count)
        ),
        inlet_temperature_c=inlet,
        outlet_temperature_c=_require_finite("outlet_temperature_c", outlet),
        heat_transfer_w=_require_finite("heat_transfer_w", heat_transfer),
        outlet_direction=direction,
        plate_count=int(plate_count),
    )


def _load_egasp_class(egasp_root: Path | None = None):
    root = Path(egasp_root or Path(__file__).resolve().parent.parent / "egasp")
    src_root = root / "src" / "egasp"
    core_file = src_root / "core.py"
    validate_file = src_root / "validate.py"
    data_file = src_root / "data" / "egasp_data.py"

    missing_paths = [path for path in (core_file, validate_file, data_file) if not path.exists()]
    if missing_paths:
        missing_text = ", ".join(str(path) for path in missing_paths)
        raise EgaspClientError(f"EGASP source files are missing: {missing_text}.")

    package = _ensure_package("egasp", src_root)
    _ensure_package("egasp.data", src_root / "data")
    package.data = sys.modules["egasp.data"]

    try:
        _load_module("egasp.data.egasp_data", data_file)
        _load_module("egasp.validate", validate_file)
        core_module = _load_module("egasp.core", core_file)
    except ModuleNotFoundError as exc:
        if exc.name == "numpy":
            raise EgaspClientError(
                "EGASP requires numpy, but numpy is not installed in the current environment."
            ) from exc
        raise EgaspClientError(f"EGASP dependency is missing: {exc.name}.") from exc

    egasp_class = getattr(core_module, "EGASP", None)
    if egasp_class is None:
        raise EgaspClientError(f"EGASP class was not found in {core_file}.")
    return egasp_class


def _ensure_package(name: str, path: Path) -> ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module
    return module


def _load_module(name: str, path: Path) -> ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EgaspClientError(f"Unable to load module {name} from {path}.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _require_finite(name: str, value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise EgaspClientError(f"EGASP returned a non-finite value for {name}: {value}.")
    return numeric


def _require_finite_arg(name: str, value: float | None) -> float:
    if value is None:
        raise EgaspClientError(f"{name} is required for the selected coolant solve mode.")
    return _require_finite(name, value)


def _mass_flow_kg_s(volume_flow_l_min: float, density_kg_per_m3: float) -> float:
    return volume_flow_l_min / 1000.0 / 60.0 * density_kg_per_m3


def _heat_transfer_w(
    mass_flow_kg_s: float,
    specific_heat_j_per_kg_k: float,
    inlet_temperature_c: float,
    outlet_temperature_c: float,
) -> float:
    return mass_flow_kg_s * specific_heat_j_per_kg_k * abs(outlet_temperature_c - inlet_temperature_c)


def _require_positive(name: str, value: float) -> None:
    if value <= 0:
        raise EgaspClientError(f"{name} must be greater than 0.")


def _require_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise EgaspClientError(f"{name} must be greater than or equal to 0.")


def _optional_finite(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    return _require_finite(name, value)
