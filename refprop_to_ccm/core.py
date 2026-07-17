from __future__ import annotations

import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ToolConfig
from .inlet_conditions import (
    RefrigerantInletCondition,
    calculate_refrigerant_inlet,
    vapor_volume_fraction_from_quality,
)
from .models import LiquidProperties, SaturatedMixtureState, SaturationState
from .refprop_client import RefpropClient
from .refprop_client import TEMPERATURE_EPSILON
from .starccm import StarCcmRunner, render_macro
from .tables import write_liquid_csv, write_liquid_json, write_summary_json, write_vapor_csv
from .units import k_to_c, pressure_to_pa, temperature_to_k

SATURATION_TEMPERATURE_TOLERANCE_K = 1.0e-4
MAX_TEMPERATURE_TABLE_ROWS = 100_000


@dataclass(frozen=True)
class RunResult:
    summary: dict
    liquid_json: Path | None
    liquid_csv: Path | None
    vapor_csv: Path | None
    summary_json: Path
    macro_file: Path
    star_log: Path | None = None

    def to_display_text(self) -> str:
        return json.dumps(self.summary, indent=2, ensure_ascii=False)


@dataclass(frozen=True)
class RefrigerantInletRefpropRequest:
    fluid_name: str
    fluid_components: list[dict[str, Any]] | None
    saturation_type: str
    saturation_value: float
    saturation_unit: str
    solve_mode: str
    heat_transfer_w: float | None
    total_mass_flow_kg_s: float | None
    layer_count: int
    inlet_temperature_c: float | None
    outlet_temperature_c: float | None
    outlet_enthalpy_direction: str | None
    inlet_state_mode: str = "temperature"
    inlet_enthalpy_j_per_kg: float | None = None
    inlet_enthalpy_source_mode: str = "direct"
    inlet_enthalpy_upstream_pressure_pa: float | None = None
    inlet_enthalpy_upstream_temperature_c: float | None = None
    inlet_quality: float | None = None
    inlet_vapor_volume_fraction: float | None = None


@dataclass(frozen=True)
class RefrigerantInletRefpropResult:
    condition: RefrigerantInletCondition
    saturation: SaturationState
    liquid: LiquidProperties


@dataclass(frozen=True)
class _ResolvedRefrigerantInletState:
    temperature_c: float
    enthalpy_j_per_kg: float
    quality: float | None
    vapor_volume_fraction: float | None
    saturated_liquid_enthalpy_j_per_kg: float
    saturated_vapor_enthalpy_j_per_kg: float
    liquid_density_kg_per_m3: float
    vapor_density_kg_per_m3: float
    state_mode: str


def calculate_refrigerant_inlet_from_refprop(
    request: RefrigerantInletRefpropRequest,
    *,
    refprop=None,
    allow_out_of_range_volume_fraction: bool = False,
) -> RefrigerantInletRefpropResult:
    client = refprop if refprop is not None else RefpropClient()
    client.load_fluid(request.fluid_name, request.fluid_components)

    saturation_type = request.saturation_type.strip().lower()
    if saturation_type == "pressure":
        saturation = client.saturation_from_pressure(
            request.fluid_name,
            pressure_to_pa(request.saturation_value, request.saturation_unit),
        )
    elif saturation_type == "temperature":
        saturation = client.saturation_from_temperature(
            request.fluid_name,
            temperature_to_k(request.saturation_value, request.saturation_unit),
        )
    else:
        raise ValueError("saturation_type must be pressure or temperature.")

    liquid = client.saturated_liquid_properties(request.fluid_name, saturation)
    condition = _calculate_refrigerant_inlet_condition(
        request=request,
        refprop=client,
        saturation_pressure_pa=saturation.pressure_pa,
        saturation_temperature_k=saturation.temperature_k,
        liquid=liquid,
        allow_out_of_range_volume_fraction=allow_out_of_range_volume_fraction,
    )
    return RefrigerantInletRefpropResult(
        condition=condition,
        saturation=saturation,
        liquid=liquid,
    )


def generate_outputs(config: ToolConfig, run_star: bool = False) -> RunResult:
    refrigerant_phase_mode = config.refrigerant_phase_mode.strip().lower()
    if refrigerant_phase_mode not in {"multiphase", "liquid", "vapor"}:
        raise ValueError("refrigerant_phase_mode must be liquid, vapor, or multiphase.")
    validate_temperature_table_sizes(config)
    out_dir = config.output_directory
    out_dir.mkdir(parents=True, exist_ok=True)
    writes_liquid = refrigerant_phase_mode in {"liquid", "multiphase"}
    writes_vapor = refrigerant_phase_mode in {"vapor", "multiphase"}

    refprop = RefpropClient()
    refprop.load_fluid(config.fluid_name, config.fluid_components)

    saturation = resolve_saturation(refprop, config)
    if writes_vapor:
        validate_gas_temperature_range(config, saturation.temperature_k)
    if writes_liquid:
        validate_liquid_temperature_range(config, saturation.temperature_k)
    liquid = refprop.saturated_liquid_properties(config.fluid_name, saturation)

    gas_pressure_pa = config.gas_pressure_pa
    if gas_pressure_pa is None:
        gas_pressure_pa = saturation.pressure_pa

    vapor_rows = None
    if writes_vapor and config.gas_table_mode == "temperature":
        vapor_rows = refprop.vapor_table(
            fluid_name=config.fluid_name,
            pressure_pa=gas_pressure_pa,
            temperature_start_k=config.gas_temperature_start_k,
            temperature_end_k=config.gas_temperature_end_k,
            temperature_step_k=config.gas_temperature_step_k,
            quality_points=config.quality_points,
            viscosity_model=config.viscosity_model,
        )
    elif writes_vapor and config.gas_table_mode == "equivalent_quality":
        vapor_rows = refprop.equivalent_vapor_table(
            fluid_name=config.fluid_name,
            pressure_pa=gas_pressure_pa,
            temperature_start_k=config.gas_temperature_start_k,
            temperature_end_k=config.gas_temperature_end_k,
            temperature_step_k=config.gas_temperature_step_k,
            quality_points=config.quality_points,
            viscosity_model=config.viscosity_model,
        )
    elif writes_vapor:
        raise ValueError(f"Unsupported gas table mode: {config.gas_table_mode}")

    liquid_rows = None
    if writes_liquid and config.liquid_property_mode == "table":
        liquid_rows = refprop.liquid_table(
            fluid_name=config.fluid_name,
            pressure_pa=saturation.pressure_pa,
            temperature_start_k=config.liquid_temperature_start_k,
            temperature_end_k=config.liquid_temperature_end_k,
            temperature_step_k=config.liquid_temperature_step_k,
        )

    liquid_json = out_dir / "liquid_properties.json" if writes_liquid else None
    liquid_csv = out_dir / "liquid_properties.csv" if liquid_rows is not None else None
    vapor_csv = out_dir / "vapor_properties.csv" if vapor_rows is not None else None
    summary_json = out_dir / "summary.json"
    macro_file = out_dir / "apply_refprop_to_star.java"

    if liquid_json is not None:
        write_liquid_json(liquid_json, liquid)
    if liquid_rows is not None:
        assert liquid_csv is not None
        write_liquid_csv(liquid_csv, liquid_rows)
    if vapor_rows is not None:
        assert vapor_csv is not None
        write_vapor_csv(vapor_csv, vapor_rows)

    summary = {
        "fluid": config.fluid_name,
        "refrigerant_phase_mode": refrigerant_phase_mode,
        "saturation": saturation.to_json(),
        "gas_table_pressure_pa": gas_pressure_pa,
        "gas_table_mode": config.gas_table_mode,
        "gas_equivalent_replacement_points": refprop.last_equivalent_replacement_count,
        "gas_equivalent_quality_points_used": refprop.last_equivalent_quality_points,
        "liquid_table_pressure_pa": saturation.pressure_pa if liquid_rows is not None else None,
        "liquid_properties": str(liquid_json.resolve()) if liquid_json is not None else None,
        "liquid_property_table": str(liquid_csv.resolve()) if liquid_csv is not None else None,
        "vapor_properties": str(vapor_csv.resolve()) if vapor_csv is not None else None,
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
        liquid_csv=liquid_csv.resolve() if liquid_csv is not None else None,
        vapor_csv=vapor_csv.resolve() if vapor_csv is not None else None,
        output_sim=config.output_sim_file,
    )
    macro_file.write_text(macro_text, encoding="utf-8")

    result = RunResult(
        summary=summary,
        liquid_json=liquid_json.resolve() if liquid_json is not None else None,
        liquid_csv=liquid_csv.resolve() if liquid_csv is not None else None,
        vapor_csv=vapor_csv.resolve() if vapor_csv is not None else None,
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

    request = RefrigerantInletRefpropRequest(
        fluid_name=config.fluid_name,
        fluid_components=config.fluid_components,
        saturation_type=config.saturation_type,
        saturation_value=config.saturation_value,
        saturation_unit=config.saturation_unit,
        solve_mode=solve_mode,
        heat_transfer_w=config.refrigerant_heat_transfer_w,
        total_mass_flow_kg_s=config.refrigerant_total_mass_flow_kg_s,
        layer_count=config.refrigerant_layer_count,
        inlet_temperature_c=config.refrigerant_inlet_temperature_c,
        outlet_temperature_c=config.refrigerant_outlet_temperature_c,
        outlet_enthalpy_direction=config.refrigerant_outlet_enthalpy_direction,
    )
    refrigerant_inlet = _calculate_refrigerant_inlet_condition(
        request=request,
        refprop=refprop,
        saturation_pressure_pa=saturation_pressure_pa,
        saturation_temperature_k=saturation_temperature_k,
        liquid=liquid,
    )
    return asdict(refrigerant_inlet)


def _calculate_refrigerant_inlet_condition(
    *,
    request: RefrigerantInletRefpropRequest,
    refprop,
    saturation_pressure_pa: float,
    saturation_temperature_k: float,
    liquid: LiquidProperties,
    allow_out_of_range_volume_fraction: bool = False,
) -> RefrigerantInletCondition:
    solve_mode = request.solve_mode.strip().lower()
    if solve_mode not in {"heat_transfer", "mass_flow", "outlet_temperature"}:
        raise ValueError("solve_mode must be heat_transfer, mass_flow, or outlet_temperature.")

    inlet_state = _resolve_refrigerant_inlet_state(
        request=request,
        refprop=refprop,
        saturation_pressure_pa=saturation_pressure_pa,
        liquid=liquid,
    )
    inlet_enthalpy_j_per_kg = inlet_state.enthalpy_j_per_kg
    outlet_enthalpy_direction = ""
    if solve_mode == "outlet_temperature":
        outlet_enthalpy_direction = str(request.outlet_enthalpy_direction or "").strip().lower()
        if outlet_enthalpy_direction not in {"increase", "decrease"}:
            raise ValueError("outlet_enthalpy_direction must be increase or decrease.")
        if request.heat_transfer_w is None:
            raise ValueError("heat_transfer_w is required when calculating outlet temperature.")
        if request.total_mass_flow_kg_s is None or request.total_mass_flow_kg_s <= 0.0:
            raise ValueError("total_mass_flow_kg_s must be greater than 0.")
        enthalpy_delta = request.heat_transfer_w / request.total_mass_flow_kg_s
        if outlet_enthalpy_direction == "increase":
            outlet_enthalpy_j_per_kg = inlet_enthalpy_j_per_kg + enthalpy_delta
        else:
            outlet_enthalpy_j_per_kg = inlet_enthalpy_j_per_kg - enthalpy_delta
        outlet_temperature_k = refprop.temperature_ph(
            request.fluid_name,
            saturation_pressure_pa,
            outlet_enthalpy_j_per_kg,
        )
        outlet_temperature_c = k_to_c(outlet_temperature_k)
    else:
        if request.outlet_temperature_c is None:
            raise ValueError("outlet_temperature_c is required for this solve mode.")
        outlet_temperature_c = request.outlet_temperature_c
        outlet_temperature_k = temperature_to_k(outlet_temperature_c, "C")
        outlet_enthalpy_j_per_kg = refprop.enthalpy_tp(
            request.fluid_name,
            saturation_pressure_pa,
            outlet_temperature_k,
        )

    return calculate_refrigerant_inlet(
        solve_mode=solve_mode,
        heat_transfer_w=request.heat_transfer_w,
        total_mass_flow_kg_s=request.total_mass_flow_kg_s,
        layer_count=request.layer_count,
        inlet_temperature_c=inlet_state.temperature_c,
        outlet_temperature_c=outlet_temperature_c,
        inlet_enthalpy_j_per_kg=inlet_enthalpy_j_per_kg,
        outlet_enthalpy_j_per_kg=outlet_enthalpy_j_per_kg,
        saturated_liquid_enthalpy_j_per_kg=inlet_state.saturated_liquid_enthalpy_j_per_kg,
        saturated_vapor_enthalpy_j_per_kg=inlet_state.saturated_vapor_enthalpy_j_per_kg,
        saturated_liquid_density_kg_per_m3=inlet_state.liquid_density_kg_per_m3,
        saturated_vapor_density_kg_per_m3=inlet_state.vapor_density_kg_per_m3,
        outlet_enthalpy_direction=outlet_enthalpy_direction,
        fluid_name=request.fluid_name,
        inlet_state_mode=inlet_state.state_mode,
        saturation_pressure_pa=saturation_pressure_pa,
        saturation_temperature_c=k_to_c(saturation_temperature_k),
        inlet_quality=inlet_state.quality,
        inlet_vapor_volume_fraction=inlet_state.vapor_volume_fraction,
        allow_out_of_range_volume_fraction=allow_out_of_range_volume_fraction,
    )


def _resolve_refrigerant_inlet_state(
    *,
    request: RefrigerantInletRefpropRequest,
    refprop,
    saturation_pressure_pa: float,
    liquid: LiquidProperties,
) -> _ResolvedRefrigerantInletState:
    state_mode = str(request.inlet_state_mode or "temperature").strip().lower()
    if state_mode == "temperature":
        inlet_temperature_c = _required_finite(
            request.inlet_temperature_c,
            "inlet_temperature_c",
        )
        inlet_enthalpy = refprop.enthalpy_tp(
            request.fluid_name,
            saturation_pressure_pa,
            temperature_to_k(inlet_temperature_c, "C"),
        )
        return _ResolvedRefrigerantInletState(
            temperature_c=inlet_temperature_c,
            enthalpy_j_per_kg=inlet_enthalpy,
            quality=None,
            vapor_volume_fraction=None,
            saturated_liquid_enthalpy_j_per_kg=liquid.saturated_liquid_enthalpy_j_per_kg,
            saturated_vapor_enthalpy_j_per_kg=liquid.saturated_vapor_enthalpy_j_per_kg,
            liquid_density_kg_per_m3=liquid.density_kg_per_m3,
            vapor_density_kg_per_m3=liquid.saturated_vapor_density_kg_per_m3,
            state_mode=state_mode,
        )

    if state_mode not in {"enthalpy", "quality", "vapor_volume_fraction"}:
        raise ValueError(
            "inlet_state_mode must be temperature, enthalpy, quality, or vapor_volume_fraction."
        )

    saturated_liquid = refprop.saturated_mixture_state_from_quality(
        request.fluid_name,
        saturation_pressure_pa,
        0.0,
    )
    saturated_vapor = refprop.saturated_mixture_state_from_quality(
        request.fluid_name,
        saturation_pressure_pa,
        1.0,
    )
    if saturated_vapor.enthalpy_j_per_kg <= saturated_liquid.enthalpy_j_per_kg:
        raise ValueError("REFPROP返回的饱和气体焓值必须大于饱和液体焓值。")

    if state_mode == "enthalpy":
        enthalpy_source_mode = str(
            request.inlet_enthalpy_source_mode or "direct"
        ).strip().lower()
        if enthalpy_source_mode == "direct":
            inlet_enthalpy = _required_finite(
                request.inlet_enthalpy_j_per_kg,
                "inlet_enthalpy_j_per_kg",
            )
        elif enthalpy_source_mode == "upstream_tp":
            upstream_pressure_pa = _required_finite(
                request.inlet_enthalpy_upstream_pressure_pa,
                "inlet_enthalpy_upstream_pressure_pa",
            )
            if upstream_pressure_pa <= 0.0:
                raise ValueError("阀前压力必须大于0。")
            upstream_temperature_c = _required_finite(
                request.inlet_enthalpy_upstream_temperature_c,
                "inlet_enthalpy_upstream_temperature_c",
            )
            upstream_temperature_k = temperature_to_k(upstream_temperature_c, "C")
            _reject_saturated_upstream_tp_state(
                refprop=refprop,
                fluid_name=request.fluid_name,
                pressure_pa=upstream_pressure_pa,
                temperature_k=upstream_temperature_k,
            )
            inlet_enthalpy = refprop.enthalpy_tp_single_phase(
                request.fluid_name,
                upstream_pressure_pa,
                upstream_temperature_k,
            )
        else:
            raise ValueError(
                "inlet_enthalpy_source_mode must be direct or upstream_tp."
            )
        state, quality, inlet_temperature_c = _state_from_inlet_enthalpy(
            refprop=refprop,
            fluid_name=request.fluid_name,
            pressure_pa=saturation_pressure_pa,
            enthalpy_j_per_kg=inlet_enthalpy,
            saturated_liquid=saturated_liquid,
            saturated_vapor=saturated_vapor,
        )
        vapor_fraction = vapor_volume_fraction_from_quality(
            quality=quality,
            liquid_density_kg_per_m3=state.liquid_density_kg_per_m3,
            vapor_density_kg_per_m3=state.vapor_density_kg_per_m3,
        )
    elif state_mode == "quality":
        quality = _required_finite(request.inlet_quality, "inlet_quality")
        state = _state_for_possibly_unbounded_quality(
            refprop=refprop,
            fluid_name=request.fluid_name,
            pressure_pa=saturation_pressure_pa,
            quality=quality,
            saturated_liquid=saturated_liquid,
            saturated_vapor=saturated_vapor,
        )
        inlet_enthalpy = state.enthalpy_j_per_kg
        inlet_temperature_c = k_to_c(state.temperature_k)
        vapor_fraction = vapor_volume_fraction_from_quality(
            quality=quality,
            liquid_density_kg_per_m3=state.liquid_density_kg_per_m3,
            vapor_density_kg_per_m3=state.vapor_density_kg_per_m3,
        )
    else:
        vapor_fraction = _required_finite(
            request.inlet_vapor_volume_fraction,
            "inlet_vapor_volume_fraction",
        )
        state, quality = _state_from_vapor_volume_fraction(
            refprop=refprop,
            fluid_name=request.fluid_name,
            pressure_pa=saturation_pressure_pa,
            vapor_volume_fraction=vapor_fraction,
            saturated_liquid=saturated_liquid,
            saturated_vapor=saturated_vapor,
        )
        inlet_enthalpy = state.enthalpy_j_per_kg
        inlet_temperature_c = k_to_c(state.temperature_k)

    return _ResolvedRefrigerantInletState(
        temperature_c=inlet_temperature_c,
        enthalpy_j_per_kg=inlet_enthalpy,
        quality=quality,
        vapor_volume_fraction=vapor_fraction,
        saturated_liquid_enthalpy_j_per_kg=saturated_liquid.enthalpy_j_per_kg,
        saturated_vapor_enthalpy_j_per_kg=saturated_vapor.enthalpy_j_per_kg,
        liquid_density_kg_per_m3=state.liquid_density_kg_per_m3,
        vapor_density_kg_per_m3=state.vapor_density_kg_per_m3,
        state_mode=state_mode,
    )


def _reject_saturated_upstream_tp_state(
    *,
    refprop,
    fluid_name: str,
    pressure_pa: float,
    temperature_k: float,
) -> None:
    try:
        saturated_liquid = refprop.saturated_mixture_state_from_quality(
            fluid_name,
            pressure_pa,
            0.0,
        )
        saturated_vapor = refprop.saturated_mixture_state_from_quality(
            fluid_name,
            pressure_pa,
            1.0,
        )
    except RuntimeError:
        # 超临界压力没有饱和温度范围，此时交给后续TP闪蒸判断状态。
        return

    lower_temperature_k = min(
        saturated_liquid.temperature_k,
        saturated_vapor.temperature_k,
    )
    upper_temperature_k = max(
        saturated_liquid.temperature_k,
        saturated_vapor.temperature_k,
    )
    if (
        lower_temperature_k - SATURATION_TEMPERATURE_TOLERANCE_K
        <= temperature_k
        <= upper_temperature_k + SATURATION_TEMPERATURE_TOLERANCE_K
    ):
        raise ValueError(
            "阀前压力和温度对应饱和/两相状态，"
            "请改为单相液体或单相气体状态后再查询焓值。"
        )


def _state_from_inlet_enthalpy(
    *,
    refprop,
    fluid_name: str,
    pressure_pa: float,
    enthalpy_j_per_kg: float,
    saturated_liquid: SaturatedMixtureState,
    saturated_vapor: SaturatedMixtureState,
) -> tuple[SaturatedMixtureState, float, float]:
    liquid_enthalpy = saturated_liquid.enthalpy_j_per_kg
    vapor_enthalpy = saturated_vapor.enthalpy_j_per_kg
    quality = (enthalpy_j_per_kg - liquid_enthalpy) / (vapor_enthalpy - liquid_enthalpy)
    if quality < 0.0 or quality > 1.0:
        boundary_state = saturated_liquid if quality < 0.0 else saturated_vapor
        temperature_k = refprop.temperature_ph(
            fluid_name,
            pressure_pa,
            enthalpy_j_per_kg,
        )
        state = SaturatedMixtureState(
            temperature_k=temperature_k,
            pressure_pa=pressure_pa,
            mass_quality=quality,
            enthalpy_j_per_kg=enthalpy_j_per_kg,
            liquid_density_kg_per_m3=boundary_state.liquid_density_kg_per_m3,
            vapor_density_kg_per_m3=boundary_state.vapor_density_kg_per_m3,
        )
        return state, quality, k_to_c(temperature_k)

    state = _bisect_saturated_state(
        refprop=refprop,
        fluid_name=fluid_name,
        pressure_pa=pressure_pa,
        target=enthalpy_j_per_kg,
        value_from_state=lambda candidate: candidate.enthalpy_j_per_kg,
        saturated_liquid=saturated_liquid,
        saturated_vapor=saturated_vapor,
    )
    return state, state.mass_quality, k_to_c(state.temperature_k)


def _state_for_possibly_unbounded_quality(
    *,
    refprop,
    fluid_name: str,
    pressure_pa: float,
    quality: float,
    saturated_liquid: SaturatedMixtureState,
    saturated_vapor: SaturatedMixtureState,
) -> SaturatedMixtureState:
    if 0.0 <= quality <= 1.0:
        return refprop.saturated_mixture_state_from_quality(
            fluid_name,
            pressure_pa,
            quality,
        )
    liquid_enthalpy = saturated_liquid.enthalpy_j_per_kg
    vapor_enthalpy = saturated_vapor.enthalpy_j_per_kg
    enthalpy = liquid_enthalpy + quality * (vapor_enthalpy - liquid_enthalpy)
    boundary_state = saturated_liquid if quality < 0.0 else saturated_vapor
    temperature_k = refprop.temperature_ph(fluid_name, pressure_pa, enthalpy)
    return SaturatedMixtureState(
        temperature_k=temperature_k,
        pressure_pa=pressure_pa,
        mass_quality=quality,
        enthalpy_j_per_kg=enthalpy,
        liquid_density_kg_per_m3=boundary_state.liquid_density_kg_per_m3,
        vapor_density_kg_per_m3=boundary_state.vapor_density_kg_per_m3,
    )


def _state_from_vapor_volume_fraction(
    *,
    refprop,
    fluid_name: str,
    pressure_pa: float,
    vapor_volume_fraction: float,
    saturated_liquid: SaturatedMixtureState,
    saturated_vapor: SaturatedMixtureState,
) -> tuple[SaturatedMixtureState, float]:
    if vapor_volume_fraction < 0.0:
        return saturated_liquid, 0.0
    if vapor_volume_fraction > 1.0:
        return saturated_vapor, 1.0
    if vapor_volume_fraction == 0.0:
        return saturated_liquid, 0.0
    if vapor_volume_fraction == 1.0:
        return saturated_vapor, 1.0
    state = _bisect_saturated_state(
        refprop=refprop,
        fluid_name=fluid_name,
        pressure_pa=pressure_pa,
        target=vapor_volume_fraction,
        value_from_state=lambda candidate: vapor_volume_fraction_from_quality(
            quality=candidate.mass_quality,
            liquid_density_kg_per_m3=candidate.liquid_density_kg_per_m3,
            vapor_density_kg_per_m3=candidate.vapor_density_kg_per_m3,
        ),
        saturated_liquid=saturated_liquid,
        saturated_vapor=saturated_vapor,
    )
    return state, state.mass_quality


def _bisect_saturated_state(
    *,
    refprop,
    fluid_name: str,
    pressure_pa: float,
    target: float,
    value_from_state,
    saturated_liquid: SaturatedMixtureState,
    saturated_vapor: SaturatedMixtureState,
) -> SaturatedMixtureState:
    low_state = saturated_liquid
    high_state = saturated_vapor
    low_value = value_from_state(low_state)
    high_value = value_from_state(high_state)
    if target <= low_value:
        return low_state
    if target >= high_value:
        return high_state

    best_state = low_state
    for _ in range(60):
        quality = (low_state.mass_quality + high_state.mass_quality) / 2.0
        candidate = refprop.saturated_mixture_state_from_quality(
            fluid_name,
            pressure_pa,
            quality,
        )
        candidate_value = value_from_state(candidate)
        best_state = candidate
        if math.isclose(candidate_value, target, rel_tol=1.0e-10, abs_tol=1.0e-10):
            break
        if candidate_value < target:
            low_state = candidate
        else:
            high_state = candidate
    return best_state


def _required_finite(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"{name} is required for the selected inlet state mode.")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite.")
    return numeric


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
    phase_mode = config.refrigerant_phase_mode.strip().lower()
    if phase_mode not in {"multiphase", "liquid", "vapor"}:
        raise ValueError("refrigerant_phase_mode must be liquid, vapor, or multiphase.")
    if phase_mode in {"multiphase", "vapor"}:
        _validate_temperature_table_size(
            "气态温度表",
            config.gas_temperature_start_k,
            config.gas_temperature_end_k,
            config.gas_temperature_step_k,
        )
    if phase_mode in {"multiphase", "liquid"} and config.liquid_property_mode == "table":
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
