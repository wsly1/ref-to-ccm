from __future__ import annotations

from pathlib import Path

from refprop_to_ccm.config import ToolConfig
from refprop_to_ccm.models import LiquidProperties
from refprop_to_ccm.starccm import render_macro


def test_render_macro_uses_starccm_2022_compatible_material_property_method_lookup() -> None:
    macro = render_macro(
        _minimal_config(),
        _minimal_liquid_properties(),
        liquid_csv=None,
        vapor_csv=Path("vapor.csv"),
        output_sim=Path("output.sim"),
    )

    assert "getMaterialPropertyMethod" not in macro
    assert "property.setMethod(methodClass);" in macro
    assert "MaterialPropertyMethod method = property.getMethod();" in macro


def _minimal_config() -> ToolConfig:
    return ToolConfig(
        fluid_name="R454C",
        fluid_components=None,
        saturation_type="pressure",
        saturation_value=0.8,
        saturation_unit="MPa",
        gas_pressure_value=0.8,
        gas_pressure_unit="MPa",
        gas_temperature_start=10.0,
        gas_temperature_end=20.0,
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


def _minimal_liquid_properties() -> LiquidProperties:
    return LiquidProperties(
        saturation_temperature_k=280.0,
        saturation_pressure_pa=800000.0,
        specific_heat_j_per_kg_k=1400.0,
        standard_state_temperature_k=280.0,
        thermal_conductivity_w_per_m_k=0.08,
        dynamic_viscosity_pa_s=1.5e-4,
        density_kg_per_m3=1100.0,
        molecular_weight_kg_per_kmol=90.0,
        saturated_liquid_enthalpy_j_per_kg=220000.0,
        saturated_vapor_enthalpy_j_per_kg=410000.0,
        liquid_standard_state_enthalpy_j_per_kg=220000.0,
        vapor_standard_state_enthalpy_j_per_kg=410000.0,
        heat_of_formation_input_j_per_kg=220000.0,
        vapor_heat_of_formation_input_j_per_kg=410000.0,
        density_temperature_derivative_kg_per_m3_k=0.0,
        saturated_vapor_density_kg_per_m3=35.0,
        saturated_vapor_specific_heat_j_per_kg_k=1100.0,
        saturated_vapor_thermal_conductivity_w_per_m_k=0.014,
        saturated_vapor_dynamic_viscosity_pa_s=1.2e-5,
    )
