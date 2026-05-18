from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import ToolConfig
from .refprop_client import RefpropClient
from .starccm import StarCcmRunner, render_macro
from .tables import write_liquid_csv, write_liquid_json, write_summary_json, write_vapor_csv
from .units import k_to_c


@dataclass(frozen=True)
class RunResult:
    summary: dict
    liquid_json: Path
    liquid_csv: Path | None
    vapor_csv: Path
    summary_json: Path
    macro_file: Path
    star_log: Path | None = None

    def to_display_text(self) -> str:
        return json.dumps(self.summary, indent=2, ensure_ascii=False)


def generate_outputs(config: ToolConfig, run_star: bool = False) -> RunResult:
    out_dir = config.output_directory
    out_dir.mkdir(parents=True, exist_ok=True)

    refprop = RefpropClient()
    refprop.load_fluid(config.fluid_name, config.fluid_components)

    saturation = resolve_saturation(refprop, config)
    validate_gas_temperature_range(config, saturation.temperature_k)
    validate_liquid_temperature_range(config, saturation.temperature_k)
    liquid = refprop.saturated_liquid_properties(config.fluid_name, saturation)

    gas_pressure_pa = config.gas_pressure_pa
    if gas_pressure_pa is None:
        gas_pressure_pa = saturation.pressure_pa

    vapor_rows = refprop.vapor_table(
        fluid_name=config.fluid_name,
        pressure_pa=gas_pressure_pa,
        temperature_start_k=config.gas_temperature_start_k,
        temperature_end_k=config.gas_temperature_end_k,
        temperature_step_k=config.gas_temperature_step_k,
    )

    liquid_rows = None
    if config.liquid_property_mode == "table":
        liquid_rows = refprop.liquid_table(
            fluid_name=config.fluid_name,
            pressure_pa=saturation.pressure_pa,
            temperature_start_k=config.liquid_temperature_start_k,
            temperature_end_k=config.liquid_temperature_end_k,
            temperature_step_k=config.liquid_temperature_step_k,
        )

    liquid_json = out_dir / "liquid_properties.json"
    liquid_csv = out_dir / "liquid_properties.csv"
    vapor_csv = out_dir / "vapor_properties.csv"
    summary_json = out_dir / "summary.json"
    macro_file = out_dir / "apply_refprop_to_star.java"

    write_liquid_json(liquid_json, liquid)
    if liquid_rows is not None:
        write_liquid_csv(liquid_csv, liquid_rows)
    write_vapor_csv(vapor_csv, vapor_rows)

    summary = {
        "fluid": config.fluid_name,
        "saturation": saturation.to_json(),
        "gas_table_pressure_pa": gas_pressure_pa,
        "liquid_table_pressure_pa": saturation.pressure_pa if liquid_rows is not None else None,
        "liquid_properties": str(liquid_json.resolve()),
        "liquid_property_table": str(liquid_csv.resolve()) if liquid_rows is not None else None,
        "vapor_properties": str(vapor_csv.resolve()),
        "starccm": config.starccm_summary(),
    }
    write_summary_json(summary_json, summary)

    macro_text = render_macro(
        config=config,
        liquid=liquid,
        liquid_csv=liquid_csv.resolve() if liquid_rows is not None else None,
        vapor_csv=vapor_csv.resolve(),
        output_sim=config.output_sim_file,
    )
    macro_file.write_text(macro_text, encoding="utf-8")

    result = RunResult(
        summary=summary,
        liquid_json=liquid_json.resolve(),
        liquid_csv=liquid_csv.resolve() if liquid_rows is not None else None,
        vapor_csv=vapor_csv.resolve(),
        summary_json=summary_json.resolve(),
        macro_file=macro_file.resolve(),
    )

    star_log = None
    if run_star:
        star_log = StarCcmRunner(config).run(macro_file.resolve())

    return RunResult(
        summary=result.summary,
        liquid_json=result.liquid_json,
        liquid_csv=result.liquid_csv,
        vapor_csv=result.vapor_csv,
        summary_json=result.summary_json,
        macro_file=result.macro_file,
        star_log=star_log,
    )


def resolve_saturation(refprop: RefpropClient, config: ToolConfig):
    if config.saturation_type == "pressure":
        return refprop.saturation_from_pressure(config.fluid_name, config.saturation_pressure_pa)
    if config.saturation_type == "temperature":
        return refprop.saturation_from_temperature(config.fluid_name, config.saturation_temperature_k)
    raise ValueError(f"Unsupported saturation type: {config.saturation_type}")


def validate_gas_temperature_range(config: ToolConfig, saturation_temperature_k: float) -> None:
    if config.gas_temperature_start_k <= saturation_temperature_k:
        raise ValueError(
            "气态温度范围的最小值必须大于饱和温度。"
            f"当前起点为 {config.gas_temperature_start:.6g} C，"
            f"饱和温度为 {k_to_c(saturation_temperature_k):.6g} C。"
        )


def validate_liquid_temperature_range(config: ToolConfig, saturation_temperature_k: float) -> None:
    if config.liquid_property_mode != "table":
        return
    if config.liquid_temperature_end_k >= saturation_temperature_k:
        raise ValueError(
            "液态温度表的最高温度必须小于饱和温度。"
            f"当前终点为 {config.liquid_temperature_end:.6g} C，"
            f"饱和温度为 {k_to_c(saturation_temperature_k):.6g} C。"
        )
