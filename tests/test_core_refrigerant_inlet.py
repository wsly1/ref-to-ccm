from __future__ import annotations

import unittest
from pathlib import Path

from refprop_to_ccm.config import ToolConfig
from refprop_to_ccm.core import build_refrigerant_inlet_condition_summary
from refprop_to_ccm.models import LiquidProperties


class BuildRefrigerantInletConditionSummaryTests(unittest.TestCase):
    def test_returns_none_when_optional_inputs_are_missing(self) -> None:
        config = ToolConfig(
            fluid_name="R134a",
            fluid_components=None,
            saturation_type="pressure",
            saturation_value=1.0,
            saturation_unit="MPa",
            gas_pressure_value=None,
            gas_pressure_unit="MPa",
            gas_temperature_start=80.0,
            gas_temperature_end=90.0,
            gas_temperature_step=1.0,
            gas_temperature_unit="C",
            liquid_property_mode="saturation",
            liquid_temperature_start=0.0,
            liquid_temperature_end=0.0,
            liquid_temperature_step=1.0,
            liquid_temperature_unit="C",
            sim_file=Path("input.sim"),
            output_sim_file=Path("output.sim"),
            continuum_name="Physics 1",
            liquid_phase_name="liquid",
            vapor_phase_name="gas",
            vapor_specific_heat_source="cp_table",
            starccm_exe=None,
            output_directory=Path("out"),
        )

        result = build_refrigerant_inlet_condition_summary(
            config=config,
            refprop=object(),
            liquid=_sample_liquid_properties(),
            saturation_pressure_pa=1_600_000.0,
            saturation_temperature_k=363.15,
        )

        self.assertIsNone(result)

    def test_calculates_summary_from_a25_f32_style_inputs(self) -> None:
        config = ToolConfig(
            fluid_name="R134a",
            fluid_components=None,
            saturation_type="pressure",
            saturation_value=1.0,
            saturation_unit="MPa",
            gas_pressure_value=None,
            gas_pressure_unit="MPa",
            gas_temperature_start=80.0,
            gas_temperature_end=90.0,
            gas_temperature_step=1.0,
            gas_temperature_unit="C",
            liquid_property_mode="saturation",
            liquid_temperature_start=0.0,
            liquid_temperature_end=0.0,
            liquid_temperature_step=1.0,
            liquid_temperature_unit="C",
            sim_file=Path("input.sim"),
            output_sim_file=Path("output.sim"),
            continuum_name="Physics 1",
            liquid_phase_name="liquid",
            vapor_phase_name="gas",
            vapor_specific_heat_source="cp_table",
            starccm_exe=None,
            output_directory=Path("out"),
            refrigerant_inlet_solve_mode="heat_transfer",
            refrigerant_heat_transfer_w=13885.0,
            refrigerant_layer_count=18,
            refrigerant_inlet_temperature_c=98.0,
            refrigerant_outlet_temperature_c=80.0,
        )
        refprop = FakeRefpropClient(
            enthalpy_by_tp={
                (1_600_000.0, 371.15): 430000.0,
                (1_600_000.0, 353.15): 250000.0,
            }
        )

        result = build_refrigerant_inlet_condition_summary(
            config=config,
            refprop=refprop,
            liquid=_sample_liquid_properties(),
            saturation_pressure_pa=1_600_000.0,
            saturation_temperature_k=363.15,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["solve_mode"], "heat_transfer")
        self.assertAlmostEqual(result["heat_transfer_w"], 13885.0)
        self.assertAlmostEqual(result["total_mass_flow_kg_s"], 13885.0 / 180000.0)
        self.assertAlmostEqual(result["single_layer_mass_flow_kg_s"], 13885.0 / 180000.0 / 18.0)
        self.assertAlmostEqual(result["outlet_temperature_c"], 80.0)
        self.assertAlmostEqual(result["quality"], (430000.0 - 240000.0) / (410000.0 - 240000.0))
        self.assertAlmostEqual(result["vapor_volume_fraction"], 1.0)
        self.assertEqual(result["starccm_volume_fraction"], "[1,0]")
        self.assertEqual(
            refprop.calls,
            [
                ("R134a", 1_600_000.0, 371.15),
                ("R134a", 1_600_000.0, 353.15),
            ],
        )

    def test_calculates_summary_from_mass_flow_inputs(self) -> None:
        config = ToolConfig(
            fluid_name="R134a",
            fluid_components=None,
            saturation_type="pressure",
            saturation_value=1.0,
            saturation_unit="MPa",
            gas_pressure_value=None,
            gas_pressure_unit="MPa",
            gas_temperature_start=80.0,
            gas_temperature_end=90.0,
            gas_temperature_step=1.0,
            gas_temperature_unit="C",
            liquid_property_mode="saturation",
            liquid_temperature_start=0.0,
            liquid_temperature_end=0.0,
            liquid_temperature_step=1.0,
            liquid_temperature_unit="C",
            sim_file=Path("input.sim"),
            output_sim_file=Path("output.sim"),
            continuum_name="Physics 1",
            liquid_phase_name="liquid",
            vapor_phase_name="gas",
            vapor_specific_heat_source="cp_table",
            starccm_exe=None,
            output_directory=Path("out"),
            refrigerant_inlet_solve_mode="mass_flow",
            refrigerant_total_mass_flow_kg_s=0.2,
            refrigerant_layer_count=20,
            refrigerant_inlet_temperature_c=5.0,
            refrigerant_outlet_temperature_c=15.0,
        )
        refprop = FakeRefpropClient(
            enthalpy_by_tp={
                (1_600_000.0, 278.15): 250000.0,
                (1_600_000.0, 288.15): 430000.0,
            }
        )

        result = build_refrigerant_inlet_condition_summary(
            config=config,
            refprop=refprop,
            liquid=_sample_liquid_properties(),
            saturation_pressure_pa=1_600_000.0,
            saturation_temperature_k=363.15,
        )

        assert result is not None
        self.assertEqual(result["solve_mode"], "mass_flow")
        self.assertAlmostEqual(result["total_mass_flow_kg_s"], 0.2)
        self.assertAlmostEqual(result["single_layer_mass_flow_kg_s"], 0.01)
        self.assertAlmostEqual(result["heat_transfer_w"], 0.2 * 180000.0)
        self.assertAlmostEqual(result["outlet_temperature_c"], 15.0)

    def test_calculates_outlet_temperature_from_heat_and_mass_flow(self) -> None:
        config = ToolConfig(
            fluid_name="R134a",
            fluid_components=None,
            saturation_type="pressure",
            saturation_value=1.0,
            saturation_unit="MPa",
            gas_pressure_value=None,
            gas_pressure_unit="MPa",
            gas_temperature_start=80.0,
            gas_temperature_end=90.0,
            gas_temperature_step=1.0,
            gas_temperature_unit="C",
            liquid_property_mode="saturation",
            liquid_temperature_start=0.0,
            liquid_temperature_end=0.0,
            liquid_temperature_step=1.0,
            liquid_temperature_unit="C",
            sim_file=Path("input.sim"),
            output_sim_file=Path("output.sim"),
            continuum_name="Physics 1",
            liquid_phase_name="liquid",
            vapor_phase_name="gas",
            vapor_specific_heat_source="cp_table",
            starccm_exe=None,
            output_directory=Path("out"),
            refrigerant_inlet_solve_mode="outlet_temperature",
            refrigerant_heat_transfer_w=10000.0,
            refrigerant_total_mass_flow_kg_s=0.1,
            refrigerant_outlet_enthalpy_direction="increase",
            refrigerant_layer_count=20,
            refrigerant_inlet_temperature_c=5.0,
        )
        refprop = FakeRefpropClient(
            enthalpy_by_tp={(1_600_000.0, 278.15): 250000.0},
            temperature_by_ph={(1_600_000.0, 350000.0): 288.15},
        )

        result = build_refrigerant_inlet_condition_summary(
            config=config,
            refprop=refprop,
            liquid=_sample_liquid_properties(),
            saturation_pressure_pa=1_600_000.0,
            saturation_temperature_k=363.15,
        )

        assert result is not None
        self.assertEqual(result["solve_mode"], "outlet_temperature")
        self.assertEqual(result["outlet_enthalpy_direction"], "increase")
        self.assertAlmostEqual(result["heat_transfer_w"], 10000.0)
        self.assertAlmostEqual(result["total_mass_flow_kg_s"], 0.1)
        self.assertAlmostEqual(result["single_layer_mass_flow_kg_s"], 0.005)
        self.assertAlmostEqual(result["outlet_temperature_c"], 15.0)
        self.assertAlmostEqual(result["outlet_enthalpy_j_per_kg"], 350000.0)


class LiquidPropertiesSerializationTests(unittest.TestCase):
    def test_to_json_includes_saturated_vapor_density(self) -> None:
        liquid = _sample_liquid_properties()

        payload = liquid.to_json()

        self.assertEqual(payload["saturated_vapor_density_kg_per_m3"], 90.0)


class FakeRefpropClient:
    def __init__(
        self,
        enthalpy_by_tp: dict[tuple[float, float], float],
        temperature_by_ph: dict[tuple[float, float], float] | None = None,
    ) -> None:
        self.enthalpy_by_tp = enthalpy_by_tp
        self.temperature_by_ph = temperature_by_ph or {}
        self.calls: list[tuple[str, float, float]] = []

    def enthalpy_tp(self, fluid_name: str, pressure_pa: float, temperature_k: float) -> float:
        self.calls.append((fluid_name, pressure_pa, temperature_k))
        return self.enthalpy_by_tp[(pressure_pa, temperature_k)]

    def temperature_ph(self, fluid_name: str, pressure_pa: float, enthalpy_j_per_kg: float) -> float:
        self.calls.append((fluid_name, pressure_pa, enthalpy_j_per_kg))
        return self.temperature_by_ph[(pressure_pa, enthalpy_j_per_kg)]


def _sample_liquid_properties() -> LiquidProperties:
    return LiquidProperties(
        saturation_temperature_k=363.15,
        saturation_pressure_pa=1_600_000.0,
        specific_heat_j_per_kg_k=1500.0,
        standard_state_temperature_k=363.15,
        thermal_conductivity_w_per_m_k=0.08,
        dynamic_viscosity_pa_s=0.0002,
        density_kg_per_m3=980.0,
        molecular_weight_kg_per_kmol=100.0,
        saturated_liquid_enthalpy_j_per_kg=240000.0,
        saturated_vapor_enthalpy_j_per_kg=410000.0,
        saturated_vapor_density_kg_per_m3=90.0,
        liquid_standard_state_enthalpy_j_per_kg=240000.0,
        vapor_standard_state_enthalpy_j_per_kg=410000.0,
        heat_of_formation_input_j_per_kg=240000.0,
        vapor_heat_of_formation_input_j_per_kg=410000.0,
        density_temperature_derivative_kg_per_m3_k=0.0,
    )


if __name__ == "__main__":
    unittest.main()
