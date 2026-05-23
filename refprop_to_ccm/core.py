from __future__ import annotations

import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

from .config import ToolConfig
from .inlet_conditions import calculate_refrigerant_inlet
from .models import LiquidProperties
from .refprop_client import RefpropClient
from .refprop_client import TEMPERATURE_EPSILON
from .starccm import StarCcmRunner, render_macro
from .tables import write_liquid_csv, write_liquid_json, write_summary_json, write_vapor_csv
from .units import k_to_c, temperature_to_k

SATURATION_TEMPERATURE_TOLERANCE_K = 1.0e-4
MAX_TEMPERATURE_TABLE_ROWS = 100_000


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
    validate_temperature_table_sizes(config)
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

    if config.gas_table_mode == "temperature":
        vapor_rows = refprop.vapor_table(
            fluid_name=config.fluid_name,
            pressure_pa=gas_pressure_pa,
            temperature_start_k=config.gas_temperature_start_k,
            temperature_end_k=config.gas_temperature_end_k,
            temperature_step_k=config.gas_temperature_step_k,
        )
    elif config.gas_table_mode == "equivalent_quality":
        vapor_rows = refprop.equivalent_vapor_table(
            fluid_name=config.fluid_name,
            pressure_pa=gas_pressure_pa,
            temperature_start_k=config.gas_temperature_start_k,
            temperature_end_k=config.gas_temperature_end_k,
            temperature_step_k=config.gas_temperature_step_k,
            quality_points=config.quality_points,
            viscosity_model=config.viscosity_model,
        )
    else:
        raise ValueError(f"Unsupported gas table mode: {config.gas_table_mode}")

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
        "gas_table_mode": config.gas_table_mode,
        "gas_equivalent_replacement_points": refprop.last_equivalent_replacement_count,
        "gas_equivalent_quality_points_used": refprop.last_equivalent_quality_points,
        "liquid_table_pressure_pa": saturation.pressure_pa if liquid_rows is not None else None,
        "liquid_properties": str(liquid_json.resolve()),
        "liquid_property_table": str(liquid_csv.resolve()) if liquid_rows is not None else None,
        "vapor_properties": str(vapor_csv.resolve()),
        "starccm": config.starccm_summary(),
    }
    refrigerant_inlet_summary = build_refrigerant_inlet_condition_summary(
        config=config,
        refprop=refprop,
        liquid=liquid,
        saturation_pressure_pa=saturation.pressure_pa,
        saturation_temperature_k=saturation.temperature_k,
    )
    if refrigerant_inlet_summary is not None:
        summary["refrigerant_inlet_condition"] = refrigerant_inlet_summary
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


def build_refrigerant_inlet_condition_summary(
    config: ToolConfig,
    refprop,
    liquid: LiquidProperties,
    saturation_pressure_pa: float,
    saturation_temperature_k: float,
) -> dict[str, float | str] | None:
    solve_mode = config.refrigerant_inlet_solve_mode or "heat_transfer"
    if config.refrigerant_layer_count is None or config.refrigerant_inlet_temperature_c is None:
        return None
    if solve_mode == "heat_transfer" and config.refrigerant_heat_transfer_w is None:
        return None
    if solve_mode == "mass_flow" and config.refrigerant_total_mass_flow_kg_s is None:
        return None
    if solve_mode in {"heat_transfer", "mass_flow"} and config.refrigerant_outlet_temperature_c is None:
        return None
    if solve_mode == "outlet_temperature" and (
        config.refrigerant_heat_transfer_w is None
        or config.refrigerant_total_mass_flow_kg_s is None
        or config.refrigerant_outlet_enthalpy_direction is None
    ):
        return None
    if solve_mode not in {"heat_transfer", "mass_flow", "outlet_temperature"}:
        raise ValueError("refrigerant_inlet_solve_mode must be heat_transfer, mass_flow, or outlet_temperature.")

    inlet_temperature_k = temperature_to_k(config.refrigerant_inlet_temperature_c, "C")
    inlet_enthalpy_j_per_kg = refprop.enthalpy_tp(config.fluid_name, saturation_pressure_pa, inlet_temperature_k)
    outlet_enthalpy_direction = ""
    if solve_mode == "outlet_temperature":
        outlet_enthalpy_direction = str(config.refrigerant_outlet_enthalpy_direction).strip().lower()
        if outlet_enthalpy_direction not in {"increase", "decrease"}:
            raise ValueError("refrigerant_outlet_enthalpy_direction must be increase or decrease.")
        if config.refrigerant_total_mass_flow_kg_s <= 0.0:
            raise ValueError("refrigerant_total_mass_flow_kg_s must be greater than 0.")
        enthalpy_delta = config.refrigerant_heat_transfer_w / config.refrigerant_total_mass_flow_kg_s
        if outlet_enthalpy_direction == "increase":
            outlet_enthalpy_j_per_kg = inlet_enthalpy_j_per_kg + enthalpy_delta
        else:
            outlet_enthalpy_j_per_kg = inlet_enthalpy_j_per_kg - enthalpy_delta
        outlet_temperature_k = refprop.temperature_ph(
            config.fluid_name,
            saturation_pressure_pa,
            outlet_enthalpy_j_per_kg,
        )
        outlet_temperature_c = k_to_c(outlet_temperature_k)
    else:
        outlet_temperature_c = config.refrigerant_outlet_temperature_c
        outlet_temperature_k = temperature_to_k(outlet_temperature_c, "C")
        outlet_enthalpy_j_per_kg = refprop.enthalpy_tp(config.fluid_name, saturation_pressure_pa, outlet_temperature_k)

    refrigerant_inlet = calculate_refrigerant_inlet(
        solve_mode=solve_mode,
        heat_transfer_w=config.refrigerant_heat_transfer_w,
        total_mass_flow_kg_s=config.refrigerant_total_mass_flow_kg_s,
        layer_count=config.refrigerant_layer_count,
        inlet_temperature_c=config.refrigerant_inlet_temperature_c,
        outlet_temperature_c=outlet_temperature_c,
        inlet_enthalpy_j_per_kg=inlet_enthalpy_j_per_kg,
        outlet_enthalpy_j_per_kg=outlet_enthalpy_j_per_kg,
        saturated_liquid_enthalpy_j_per_kg=liquid.saturated_liquid_enthalpy_j_per_kg,
        saturated_vapor_enthalpy_j_per_kg=liquid.saturated_vapor_enthalpy_j_per_kg,
        saturated_liquid_density_kg_per_m3=liquid.density_kg_per_m3,
        saturated_vapor_density_kg_per_m3=liquid.saturated_vapor_density_kg_per_m3,
    )
    payload = asdict(refrigerant_inlet)
    if outlet_enthalpy_direction:
        payload["outlet_enthalpy_direction"] = outlet_enthalpy_direction
    return payload


def validate_gas_temperature_range(config: ToolConfig, saturation_temperature_k: float) -> None:
    if config.gas_table_mode == "equivalent_quality":
        return
    if config.gas_temperature_start_k < saturation_temperature_k - SATURATION_TEMPERATURE_TOLERANCE_K:
        raise ValueError(
            "气态温度范围的最小值不能小于饱和温度。"
            f"当前起点为 {config.gas_temperature_start:.6g} C，"
            f"饱和温度为 {k_to_c(saturation_temperature_k):.6g} C。"
        )


def validate_temperature_table_sizes(config: ToolConfig) -> None:
    _validate_temperature_table_size(
        "气态温度表",
        config.gas_temperature_start_k,
        config.gas_temperature_end_k,
        config.gas_temperature_step_k,
    )
    if config.liquid_property_mode == "table":
        _validate_temperature_table_size(
            "液态温度表",
            config.liquid_temperature_start_k,
            config.liquid_temperature_end_k,
            config.liquid_temperature_step_k,
        )


def _validate_temperature_table_size(label: str, start_k: float, end_k: float, step_k: float) -> None:
    if not all(math.isfinite(value) for value in (start_k, end_k, step_k)):
        raise ValueError(f"{label}的温度范围和步长必须为有限数值。")
    if step_k <= 0.0:
        raise ValueError(f"{label}的温度步长必须大于 0。")
    if end_k < start_k:
        raise ValueError(f"{label}的终点温度不能小于起点温度。")

    row_count = math.floor((end_k + TEMPERATURE_EPSILON - start_k) / step_k) + 1
    last_temperature_k = start_k + (row_count - 1) * step_k
    if last_temperature_k < end_k - TEMPERATURE_EPSILON:
        row_count += 1
    if row_count > MAX_TEMPERATURE_TABLE_ROWS:
        raise ValueError(
            f"{label}预计生成 {row_count:,} 行，超过行数上限 {MAX_TEMPERATURE_TABLE_ROWS:,}。"
            "请增大温度步长或缩小温度范围。"
        )


def validate_liquid_temperature_range(config: ToolConfig, saturation_temperature_k: float) -> None:
    if config.liquid_property_mode != "table":
        return
    if config.liquid_temperature_end_k > saturation_temperature_k + SATURATION_TEMPERATURE_TOLERANCE_K:
        raise ValueError(
            "液态温度表的最高温度不能大于饱和温度。"
            f"当前终点为 {config.liquid_temperature_end:.6g} C，"
            f"饱和温度为 {k_to_c(saturation_temperature_k):.6g} C。"
        )
