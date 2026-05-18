from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import LiquidProperties, LiquidRow, VaporRow


PROPERTY_HEADERS = [
    "Temperature (C)",
    "Density (kg/m3)",
    "Equivalent Specific Heat (J/kg-K)",
    "Equivalent Thermal Conductivity (W/m-K)",
    "Equivalent Dynamic Viscosity (Pa-s)",
    "Enthalpy (J/kg)",
]


def write_liquid_json(path: Path, liquid: LiquidProperties) -> None:
    path.write_text(json.dumps(liquid.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")


def write_summary_json(path: Path, summary: dict) -> None:
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def write_vapor_csv(path: Path, rows: list[VaporRow]) -> None:
    _write_property_csv(path, rows)


def write_liquid_csv(path: Path, rows: list[LiquidRow]) -> None:
    _write_property_csv(path, rows)


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
