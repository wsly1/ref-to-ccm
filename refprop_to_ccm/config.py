from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .units import pressure_to_pa, temperature_to_k


@dataclass(frozen=True)
class ToolConfig:
    fluid_name: str
    fluid_components: list[dict[str, Any]] | None
    saturation_type: str
    saturation_value: float
    saturation_unit: str
    gas_pressure_value: float | None
    gas_pressure_unit: str
    gas_temperature_start: float
    gas_temperature_end: float
    gas_temperature_step: float
    gas_temperature_unit: str
    liquid_property_mode: str
    liquid_temperature_start: float
    liquid_temperature_end: float
    liquid_temperature_step: float
    liquid_temperature_unit: str
    sim_file: Path
    output_sim_file: Path
    continuum_name: str
    liquid_phase_name: str
    vapor_phase_name: str
    vapor_specific_heat_source: str
    starccm_exe: Path | None
    output_directory: Path
    gas_table_mode: str = "temperature"
    quality_points: int | None = None
    viscosity_model: str = "cicchitti"

    @property
    def saturation_pressure_pa(self) -> float:
        return pressure_to_pa(self.saturation_value, self.saturation_unit)

    @property
    def saturation_temperature_k(self) -> float:
        return temperature_to_k(self.saturation_value, self.saturation_unit)

    @property
    def gas_pressure_pa(self) -> float | None:
        if self.gas_pressure_value is None:
            return None
        return pressure_to_pa(self.gas_pressure_value, self.gas_pressure_unit)

    @property
    def gas_temperature_start_k(self) -> float:
        return temperature_to_k(self.gas_temperature_start, self.gas_temperature_unit)

    @property
    def gas_temperature_end_k(self) -> float:
        return temperature_to_k(self.gas_temperature_end, self.gas_temperature_unit)

    @property
    def gas_temperature_step_k(self) -> float:
        unit = self.gas_temperature_unit.strip().lower()
        if unit in {"c", "degc", "celsius", "k", "kelvin"}:
            return self.gas_temperature_step
        raise ValueError(f"Unsupported temperature step unit: {self.gas_temperature_unit}")

    @property
    def liquid_temperature_start_k(self) -> float:
        return temperature_to_k(self.liquid_temperature_start, self.liquid_temperature_unit)

    @property
    def liquid_temperature_end_k(self) -> float:
        return temperature_to_k(self.liquid_temperature_end, self.liquid_temperature_unit)

    @property
    def liquid_temperature_step_k(self) -> float:
        unit = self.liquid_temperature_unit.strip().lower()
        if unit in {"c", "degc", "celsius", "k", "kelvin"}:
            return self.liquid_temperature_step
        raise ValueError(f"Unsupported liquid temperature step unit: {self.liquid_temperature_unit}")

    def starccm_summary(self) -> dict[str, str | None]:
        return {
            "sim_file": str(self.sim_file),
            "output_sim_file": str(self.output_sim_file),
            "continuum_name": self.continuum_name,
            "liquid_phase_name": self.liquid_phase_name,
            "vapor_phase_name": self.vapor_phase_name,
            "vapor_specific_heat_source": self.vapor_specific_heat_source,
            "liquid_property_mode": self.liquid_property_mode,
            "gas_table_mode": self.gas_table_mode,
            "gas_quality_points": str(self.quality_points) if self.quality_points is not None else "auto",
            "gas_viscosity_model": self.viscosity_model,
            "starccm_exe": str(self.starccm_exe) if self.starccm_exe else None,
        }


def load_config(path: Path) -> ToolConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping.")

    fluid = _mapping(data, "fluid")
    saturation = _mapping(data, "saturation")
    gas_table = _mapping(data, "gas_table")
    liquid_table = data.get("liquid_table") or {}
    if not isinstance(liquid_table, dict):
        raise ValueError("Config section 'liquid_table' must be a mapping when provided.")
    starccm = _mapping(data, "starccm")
    output = data.get("output") or {}

    sat_type = str(saturation.get("type", "pressure")).strip().lower()
    if sat_type not in {"pressure", "temperature"}:
        raise ValueError("saturation.type must be pressure or temperature.")

    gas_table_mode = str(gas_table.get("mode") or "temperature").strip().lower()
    if gas_table_mode not in {"temperature", "equivalent_quality"}:
        raise ValueError("gas_table.mode must be temperature or equivalent_quality.")
    temp_start = _required_float_if(gas_table, "temperature_start", gas_table_mode == "temperature", 0.0, "gas_table")
    temp_end = _required_float_if(gas_table, "temperature_end", gas_table_mode == "temperature", 0.0, "gas_table")
    temp_step = float(gas_table.get("temperature_step", 0.1))
    if temp_step <= 0:
        raise ValueError("gas_table.temperature_step must be positive.")
    if gas_table_mode == "temperature" and temp_end < temp_start:
        raise ValueError("gas_table.temperature_end must be greater than or equal to start.")
    specific_heat_source = str(gas_table.get("specific_heat_source") or "cp_table").strip().lower()
    if specific_heat_source not in {"cp_table", "enthalpy_table"}:
        raise ValueError("gas_table.specific_heat_source must be cp_table or enthalpy_table.")
    quality_points = _optional_quality_points(gas_table.get("quality_points"))
    viscosity_model = str(gas_table.get("viscosity_model") or "cicchitti").strip().lower()
    if viscosity_model not in {"mcadams", "cicchitti"}:
        raise ValueError("gas_table.viscosity_model must be mcadams or cicchitti.")

    liquid_mode = str(liquid_table.get("mode") or "saturation").strip().lower()
    if liquid_mode not in {"saturation", "table"}:
        raise ValueError("liquid_table.mode must be saturation or table.")
    liquid_temp_start = _required_float_if(liquid_table, "temperature_start", liquid_mode == "table", 0.0, "liquid_table")
    liquid_temp_end = _required_float_if(liquid_table, "temperature_end", liquid_mode == "table", 0.0, "liquid_table")
    liquid_temp_step = float(liquid_table.get("temperature_step", 0.1))
    if liquid_temp_step <= 0:
        raise ValueError("liquid_table.temperature_step must be positive.")
    if liquid_mode == "table" and liquid_temp_end < liquid_temp_start:
        raise ValueError("liquid_table.temperature_end must be greater than or equal to start.")

    sim_file = Path(str(starccm.get("sim_file") or "input.sim"))
    output_sim = Path(str(starccm.get("output_sim_file") or sim_file.with_name(sim_file.stem + "_refprop.sim")))
    continuum_name = str(starccm.get("continuum_name") or "").strip()
    if not continuum_name:
        raise ValueError("starccm.continuum_name is required because the macro writes to an existing continuum.")

    return ToolConfig(
        fluid_name=str(fluid["name"]).strip(),
        fluid_components=fluid.get("components"),
        saturation_type=sat_type,
        saturation_value=float(saturation["value"]),
        saturation_unit=str(saturation.get("unit") or ("MPa" if sat_type == "pressure" else "C")),
        gas_pressure_value=_optional_float(gas_table.get("pressure")),
        gas_pressure_unit=str(gas_table.get("pressure_unit") or "MPa"),
        gas_temperature_start=temp_start,
        gas_temperature_end=temp_end,
        gas_temperature_step=temp_step,
        gas_temperature_unit=str(gas_table.get("temperature_unit") or "C"),
        liquid_property_mode=liquid_mode,
        liquid_temperature_start=liquid_temp_start,
        liquid_temperature_end=liquid_temp_end,
        liquid_temperature_step=liquid_temp_step,
        liquid_temperature_unit=str(liquid_table.get("temperature_unit") or "C"),
        sim_file=sim_file,
        output_sim_file=output_sim,
        continuum_name=continuum_name,
        liquid_phase_name=str(starccm.get("liquid_phase_name") or "liquid").strip(),
        vapor_phase_name=str(starccm.get("vapor_phase_name") or "gas").strip(),
        vapor_specific_heat_source=specific_heat_source,
        starccm_exe=Path(str(starccm["starccm_exe"])) if starccm.get("starccm_exe") else None,
        output_directory=Path(str(output.get("directory") or "out")),
        gas_table_mode=gas_table_mode,
        quality_points=quality_points,
        viscosity_model=viscosity_model,
    )


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Config section '{key}' is required.")
    return value


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_quality_points(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"", "auto", "自动"}:
        return None
    points = int(text)
    if points < 2:
        raise ValueError("gas_table.quality_points must be auto or an integer greater than or equal to 2.")
    return points


def _required_float_if(data: dict[str, Any], key: str, required: bool, default: float, section: str) -> float:
    value = data.get(key)
    if value is None or value == "":
        if required:
            raise ValueError(f"{section}.{key} is required for the selected mode.")
        return default
    return float(value)
