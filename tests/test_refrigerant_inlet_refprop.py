from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from refprop_to_ccm.core import (
    RefrigerantInletRefpropRequest,
    calculate_refrigerant_inlet_from_refprop,
)
from refprop_to_ccm.gui import RefpropToCcmApp, format_inlet_parameter_summary
from refprop_to_ccm.inlet_conditions import (
    RefrigerantInletCondition,
    load_refrigerant_inlet_from_xlsx,
    normalize_refrigerant_inlet_volume_fraction,
    validate_refrigerant_inlet_condition,
)
from refprop_to_ccm.models import (
    CoolantCalculation,
    CoolantRow,
    LiquidProperties,
    SaturatedMixtureState,
    SaturationState,
)
from refprop_to_ccm.star_apply import StarApplyConfig, render_refrigerant_inlet_condition_macro
from refprop_to_ccm.tables import write_coolant_xlsx


def _liquid_properties() -> LiquidProperties:
    return LiquidProperties(
        saturation_temperature_k=313.15,
        saturation_pressure_pa=800_000.0,
        specific_heat_j_per_kg_k=1_500.0,
        standard_state_temperature_k=313.15,
        thermal_conductivity_w_per_m_k=0.08,
        dynamic_viscosity_pa_s=0.0002,
        density_kg_per_m3=1_000.0,
        molecular_weight_kg_per_kmol=100.0,
        saturated_liquid_enthalpy_j_per_kg=200_000.0,
        saturated_vapor_enthalpy_j_per_kg=600_000.0,
        liquid_standard_state_enthalpy_j_per_kg=200_000.0,
        vapor_standard_state_enthalpy_j_per_kg=600_000.0,
        heat_of_formation_input_j_per_kg=200_000.0,
        vapor_heat_of_formation_input_j_per_kg=600_000.0,
        density_temperature_derivative_kg_per_m3_k=0.0,
        saturated_vapor_density_kg_per_m3=10.0,
    )


class FakeRefpropClient:
    def __init__(self) -> None:
        self.loaded: tuple[str, object] | None = None
        self.enthalpy_queries: list[tuple[str, float, float]] = []

    def load_fluid(self, fluid_name: str, components) -> None:
        self.loaded = (fluid_name, components)

    def saturation_from_pressure(self, fluid_name: str, pressure_pa: float) -> SaturationState:
        assert fluid_name == "R454C"
        return SaturationState(temperature_k=313.15, pressure_pa=pressure_pa)

    def saturated_liquid_properties(
        self,
        fluid_name: str,
        saturation: SaturationState,
    ) -> LiquidProperties:
        assert fluid_name == "R454C"
        assert saturation.pressure_pa == pytest.approx(800_000.0)
        return _liquid_properties()

    def enthalpy_tp(self, fluid_name: str, pressure_pa: float, temperature_k: float) -> float:
        self.enthalpy_queries.append((fluid_name, pressure_pa, temperature_k))
        if temperature_k == pytest.approx(373.15):
            return 500_000.0
        if temperature_k == pytest.approx(333.15):
            return 400_000.0
        raise AssertionError(f"unexpected temperature: {temperature_k}")

    def temperature_ph(self, fluid_name: str, pressure_pa: float, enthalpy_j_per_kg: float) -> float:
        assert fluid_name == "R454C"
        assert pressure_pa == pytest.approx(800_000.0)
        return 313.15

    def saturated_mixture_state_from_quality(
        self,
        fluid_name: str,
        pressure_pa: float,
        quality: float,
    ) -> SaturatedMixtureState:
        assert fluid_name == "R454C"
        assert pressure_pa == pytest.approx(800_000.0)
        return SaturatedMixtureState(
            temperature_k=313.15,
            pressure_pa=pressure_pa,
            mass_quality=quality,
            enthalpy_j_per_kg=200_000.0 + quality * 400_000.0,
            liquid_density_kg_per_m3=1_000.0,
            vapor_density_kg_per_m3=10.0,
        )


def test_calculate_refrigerant_inlet_queries_refprop_after_entry_inputs() -> None:
    refprop = FakeRefpropClient()
    request = RefrigerantInletRefpropRequest(
        fluid_name="R454C",
        fluid_components=None,
        saturation_type="pressure",
        saturation_value=0.8,
        saturation_unit="MPa",
        solve_mode="heat_transfer",
        heat_transfer_w=10_000.0,
        total_mass_flow_kg_s=None,
        layer_count=10,
        inlet_temperature_c=100.0,
        outlet_temperature_c=60.0,
        outlet_enthalpy_direction=None,
    )

    result = calculate_refrigerant_inlet_from_refprop(request, refprop=refprop)

    assert refprop.loaded == ("R454C", None)
    assert refprop.enthalpy_queries == [
        ("R454C", 800_000.0, pytest.approx(373.15)),
        ("R454C", 800_000.0, pytest.approx(333.15)),
    ]
    assert result.condition.total_mass_flow_kg_s == pytest.approx(0.1)
    assert result.condition.single_layer_mass_flow_kg_s == pytest.approx(0.01)
    assert result.condition.heat_transfer_w == pytest.approx(10_000.0)
    assert result.saturation.pressure_pa == pytest.approx(800_000.0)
    assert result.liquid == _liquid_properties()


@pytest.mark.parametrize(
    ("inlet_state_mode", "input_value", "expected_quality", "expected_enthalpy"),
    [
        ("enthalpy", 350_000.0, 0.375, 350_000.0),
        ("quality", 0.25, 0.25, 300_000.0),
        (
            "vapor_volume_fraction",
            0.8,
            0.8 * 10.0 / (0.8 * 10.0 + 0.2 * 1_000.0),
            200_000.0
            + (0.8 * 10.0 / (0.8 * 10.0 + 0.2 * 1_000.0)) * 400_000.0,
        ),
    ],
)
def test_calculate_refrigerant_inlet_supports_three_two_phase_input_modes(
    inlet_state_mode: str,
    input_value: float,
    expected_quality: float,
    expected_enthalpy: float,
) -> None:
    request_kwargs = {
        "inlet_enthalpy_j_per_kg": None,
        "inlet_quality": None,
        "inlet_vapor_volume_fraction": None,
    }
    request_kwargs[
        {
            "enthalpy": "inlet_enthalpy_j_per_kg",
            "quality": "inlet_quality",
            "vapor_volume_fraction": "inlet_vapor_volume_fraction",
        }[inlet_state_mode]
    ] = input_value
    request = RefrigerantInletRefpropRequest(
        fluid_name="R454C",
        fluid_components=None,
        saturation_type="pressure",
        saturation_value=0.8,
        saturation_unit="MPa",
        solve_mode="heat_transfer",
        heat_transfer_w=10_000.0,
        total_mass_flow_kg_s=None,
        layer_count=10,
        inlet_temperature_c=None,
        outlet_temperature_c=60.0,
        outlet_enthalpy_direction=None,
        inlet_state_mode=inlet_state_mode,
        **request_kwargs,
    )

    result = calculate_refrigerant_inlet_from_refprop(
        request,
        refprop=FakeRefpropClient(),
    )

    assert result.condition.quality == pytest.approx(expected_quality, abs=1.0e-8)
    assert result.condition.inlet_enthalpy_j_per_kg == pytest.approx(expected_enthalpy, abs=1.0e-4)
    assert result.condition.inlet_temperature_c == pytest.approx(40.0)
    assert result.condition.saturated_liquid_density_kg_per_m3 == pytest.approx(1_000.0)
    assert result.condition.saturated_vapor_density_kg_per_m3 == pytest.approx(10.0)


def test_out_of_range_calculated_volume_fraction_requires_explicit_normalization() -> None:
    request = RefrigerantInletRefpropRequest(
        fluid_name="R454C",
        fluid_components=None,
        saturation_type="pressure",
        saturation_value=0.8,
        saturation_unit="MPa",
        solve_mode="heat_transfer",
        heat_transfer_w=10_000.0,
        total_mass_flow_kg_s=None,
        layer_count=10,
        inlet_temperature_c=None,
        outlet_temperature_c=60.0,
        outlet_enthalpy_direction=None,
        inlet_state_mode="enthalpy",
        inlet_enthalpy_j_per_kg=-40_000.0,
    )

    result = calculate_refrigerant_inlet_from_refprop(
        request,
        refprop=FakeRefpropClient(),
        allow_out_of_range_volume_fraction=True,
    )

    assert result.condition.quality == pytest.approx(-0.6)
    assert result.condition.vapor_volume_fraction == pytest.approx(-0.6)
    normalized = normalize_refrigerant_inlet_volume_fraction(result.condition)
    assert normalized.calculated_vapor_volume_fraction == pytest.approx(-0.6)
    assert normalized.vapor_volume_fraction == 0.0
    assert normalized.liquid_volume_fraction == 1.0


def test_direct_volume_fraction_above_one_can_only_be_normalized_to_vapor() -> None:
    request = RefrigerantInletRefpropRequest(
        fluid_name="R454C",
        fluid_components=None,
        saturation_type="pressure",
        saturation_value=0.8,
        saturation_unit="MPa",
        solve_mode="heat_transfer",
        heat_transfer_w=10_000.0,
        total_mass_flow_kg_s=None,
        layer_count=10,
        inlet_temperature_c=None,
        outlet_temperature_c=60.0,
        outlet_enthalpy_direction=None,
        inlet_state_mode="vapor_volume_fraction",
        inlet_vapor_volume_fraction=1.4,
    )

    result = calculate_refrigerant_inlet_from_refprop(
        request,
        refprop=FakeRefpropClient(),
        allow_out_of_range_volume_fraction=True,
    )
    normalized = normalize_refrigerant_inlet_volume_fraction(result.condition)

    assert normalized.calculated_vapor_volume_fraction == pytest.approx(1.4)
    assert normalized.vapor_volume_fraction == 1.0
    assert normalized.liquid_volume_fraction == 0.0


def test_inlet_parameter_summary_only_contains_physical_inlet_values() -> None:
    result = calculate_refrigerant_inlet_from_refprop(
        RefrigerantInletRefpropRequest(
            fluid_name="R454C",
            fluid_components=None,
            saturation_type="pressure",
            saturation_value=0.8,
            saturation_unit="MPa",
            solve_mode="heat_transfer",
            heat_transfer_w=10_000.0,
            total_mass_flow_kg_s=None,
            layer_count=10,
            inlet_temperature_c=None,
            outlet_temperature_c=60.0,
            outlet_enthalpy_direction=None,
            inlet_state_mode="quality",
            inlet_quality=0.25,
        ),
        refprop=FakeRefpropClient(),
    )

    summary = format_inlet_parameter_summary(
        coolant_values=SimpleNamespace(
            inlet_temperature_c=42.0,
            outlet_temperature_c=66.5,
            volume_flow_l_min=25.0,
            mass_flow_kg_s=0.4375,
            single_plate_mass_flow_kg_s=0.013671875,
            heat_transfer_w=38_587.5,
        ),
        refrigerant_result=result,
    )

    for expected in (
        "入口温度",
        "出口温度",
        "体积流量",
        "单板质量流量",
        "饱和压力",
        "入口焓值",
        "出口焓值",
        "干度",
        "饱和液体密度",
        "饱和气体密度",
        "气体体积分数",
    ):
        assert expected in summary
    assert "STAR-CCM+" not in summary
    assert "连续体" not in summary
    assert "宏输出" not in summary


@pytest.mark.parametrize("vapor_fraction", [-0.01, 1.01])
def test_validate_refrigerant_inlet_rejects_out_of_range_vapor_fraction(
    vapor_fraction: float,
) -> None:
    valid = RefrigerantInletCondition(
        total_mass_flow_kg_s=0.1,
        single_layer_mass_flow_kg_s=0.01,
        inlet_temperature_c=100.0,
        quality=0.5,
        vapor_volume_fraction=0.5,
        liquid_volume_fraction=0.5,
        starccm_volume_fraction="gas=0.5, liquid=0.5",
    )
    invalid = replace(
        valid,
        vapor_volume_fraction=vapor_fraction,
        liquid_volume_fraction=1.0 - vapor_fraction,
    )

    with pytest.raises(ValueError, match="0到1"):
        validate_refrigerant_inlet_condition(invalid)


def test_refrigerant_star_macro_rejects_invalid_vapor_fraction(tmp_path) -> None:
    config = StarApplyConfig(
        source_type="refrigerant_inlet_condition",
        sim_file=tmp_path / "input.sim",
        output_sim_file=tmp_path / "output.sim",
        continuum_name="Refrigerant",
        liquid_phase_name="liquid",
        vapor_phase_name="gas",
        starccm_exe=None,
        output_directory=tmp_path,
    )
    invalid = RefrigerantInletCondition(
        total_mass_flow_kg_s=0.1,
        single_layer_mass_flow_kg_s=0.01,
        inlet_temperature_c=100.0,
        quality=1.2,
        vapor_volume_fraction=1.2,
        liquid_volume_fraction=-0.2,
        starccm_volume_fraction="gas=1.2, liquid=-0.2",
    )

    with pytest.raises(ValueError, match="0到1"):
        render_refrigerant_inlet_condition_macro(config, invalid)


def test_combined_workbook_uses_entry_calculation_result(tmp_path) -> None:
    workbook_path = tmp_path / "coolant_properties.xlsx"
    coolant_row = CoolantRow(
        temperature_c=42.0,
        density_kg_per_m3=1_050.0,
        specific_heat_j_per_kg_k=3_600.0,
        thermal_conductivity_w_per_m_k=0.4,
        dynamic_viscosity_kg_per_m_s=0.003,
    )
    coolant_calculation = CoolantCalculation(
        row=coolant_row,
        solve_mode="heat",
        volume_flow_l_min=25.0,
        mass_flow_kg_s=0.4375,
        single_plate_mass_flow_kg_s=0.013671875,
        inlet_temperature_c=42.0,
        outlet_temperature_c=66.5,
        heat_transfer_w=38_587.5,
    )
    write_coolant_xlsx(workbook_path, coolant_row, coolant_calculation)
    condition = RefrigerantInletCondition(
        total_mass_flow_kg_s=0.18,
        single_layer_mass_flow_kg_s=0.01,
        inlet_temperature_c=98.0,
        quality=0.4,
        vapor_volume_fraction=0.95,
        liquid_volume_fraction=0.05,
        starccm_volume_fraction="gas=0.95, liquid=0.05",
        heat_transfer_w=13_885.0,
        outlet_temperature_c=57.0,
    )
    result = SimpleNamespace(
        condition=condition,
        saturation=SaturationState(temperature_k=313.15, pressure_pa=800_000.0),
        liquid=_liquid_properties(),
    )

    written_path = RefpropToCcmApp._write_combined_coolant_refrigerant_workbook(
        workbook_path,
        result,
    )

    assert written_path == workbook_path
    loaded = load_refrigerant_inlet_from_xlsx(workbook_path)
    assert loaded.single_layer_mass_flow_kg_s == pytest.approx(0.01)
    assert loaded.vapor_volume_fraction == pytest.approx(0.95)
    assert loaded.inlet_temperature_c == pytest.approx(98.0)
