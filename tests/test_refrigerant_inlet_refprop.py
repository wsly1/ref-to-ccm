from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from refprop_to_ccm.core import (
    RefrigerantInletRefpropRequest,
    calculate_refrigerant_inlet_from_refprop,
)
from refprop_to_ccm.gui import RefpropToCcmApp
from refprop_to_ccm.inlet_conditions import (
    RefrigerantInletCondition,
    load_refrigerant_inlet_from_xlsx,
    validate_refrigerant_inlet_condition,
)
from refprop_to_ccm.models import CoolantCalculation, CoolantRow, LiquidProperties, SaturationState
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
