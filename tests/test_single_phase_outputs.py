from __future__ import annotations

from pathlib import Path

from refprop_to_ccm import core
from refprop_to_ccm.config import ToolConfig
from refprop_to_ccm.models import LiquidProperties, SaturationState, VaporRow


class _FakeRefpropClient:
    def __init__(self) -> None:
        self.last_equivalent_replacement_count = 0
        self.last_equivalent_quality_points: int | None = None
        self.vapor_table_calls = 0
        self.liquid_table_calls = 0

    def load_fluid(self, _fluid_name: str, _components: object) -> None:
        return None

    def saturation_from_pressure(self, _fluid_name: str, pressure_pa: float) -> SaturationState:
        return SaturationState(temperature_k=300.0, pressure_pa=pressure_pa)

    def saturated_liquid_properties(self, _fluid_name: str, saturation: SaturationState) -> LiquidProperties:
        return _liquid_properties(saturation)

    def vapor_table(self, **_kwargs: object) -> list[VaporRow]:
        self.vapor_table_calls += 1
        return [
            VaporRow(
                temperature_c=30.0,
                density_kg_per_m3=25.0,
                equivalent_specific_heat_j_per_kg_k=1200.0,
                equivalent_thermal_conductivity_w_per_m_k=0.02,
                equivalent_dynamic_viscosity_pa_s=1.2e-5,
                enthalpy_j_per_kg=400000.0,
            )
        ]

    def equivalent_vapor_table(self, **_kwargs: object) -> list[VaporRow]:
        return self.vapor_table()

    def liquid_table(self, **_kwargs: object) -> list[object]:
        self.liquid_table_calls += 1
        return []


def test_generate_outputs_for_liquid_mode_skips_vapor_file_and_query(tmp_path: Path, monkeypatch) -> None:
    refprop = _FakeRefpropClient()
    monkeypatch.setattr(core, "RefpropClient", lambda: refprop)

    result = core.generate_outputs(_config(tmp_path, refrigerant_phase_mode="liquid"))

    assert result.liquid_json is not None
    assert result.liquid_json.exists()
    assert result.vapor_csv is None
    assert refprop.vapor_table_calls == 0
    assert 'REFRIGERANT_PHASE_MODE = "liquid"' in result.macro_file.read_text(encoding="utf-8")


def test_generate_outputs_for_vapor_mode_skips_liquid_files(tmp_path: Path, monkeypatch) -> None:
    refprop = _FakeRefpropClient()
    monkeypatch.setattr(core, "RefpropClient", lambda: refprop)

    result = core.generate_outputs(_config(tmp_path, refrigerant_phase_mode="vapor"))

    assert result.liquid_json is None
    assert result.liquid_csv is None
    assert result.vapor_csv is not None
    assert result.vapor_csv.exists()
    assert refprop.vapor_table_calls == 1
    assert refprop.liquid_table_calls == 0
    assert 'REFRIGERANT_PHASE_MODE = "vapor"' in result.macro_file.read_text(encoding="utf-8")


def _config(output_directory: Path, *, refrigerant_phase_mode: str) -> ToolConfig:
    return ToolConfig(
        fluid_name="R134A",
        fluid_components=None,
        saturation_type="pressure",
        saturation_value=0.8,
        saturation_unit="MPa",
        gas_pressure_value=0.8,
        gas_pressure_unit="MPa",
        gas_temperature_start=30.0,
        gas_temperature_end=40.0,
        gas_temperature_step=5.0,
        gas_temperature_unit="C",
        liquid_property_mode="saturation",
        liquid_temperature_start=0.0,
        liquid_temperature_end=0.0,
        liquid_temperature_step=1.0,
        liquid_temperature_unit="C",
        sim_file=output_directory / "input.sim",
        output_sim_file=output_directory / "output.sim",
        continuum_name="Physics 1",
        liquid_phase_name="liquid",
        vapor_phase_name="gas",
        vapor_specific_heat_source="cp_table",
        starccm_exe=None,
        output_directory=output_directory,
        refrigerant_phase_mode=refrigerant_phase_mode,
    )


def _liquid_properties(saturation: SaturationState) -> LiquidProperties:
    return LiquidProperties(
        saturation_temperature_k=saturation.temperature_k,
        saturation_pressure_pa=saturation.pressure_pa,
        specific_heat_j_per_kg_k=1400.0,
        standard_state_temperature_k=saturation.temperature_k,
        thermal_conductivity_w_per_m_k=0.08,
        dynamic_viscosity_pa_s=1.5e-4,
        density_kg_per_m3=1100.0,
        molecular_weight_kg_per_kmol=102.0,
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
