from __future__ import annotations

from pathlib import Path

import pytest

from refprop_to_ccm.config import ToolConfig, load_config
from refprop_to_ccm.models import LiquidProperties
from refprop_to_ccm.starccm import _fit_property_polynomials, render_macro


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


def test_render_macro_reports_available_phase_names_when_phase_lookup_fails() -> None:
    macro = render_macro(
        _minimal_config(),
        _minimal_liquid_properties(),
        liquid_csv=None,
        vapor_csv=Path("vapor.csv"),
        output_sim=Path("output.sim"),
    )

    assert "findPhaseByPresentationName" in macro
    assert "availablePhaseNames(multiphase)" in macro
    assert "equalsIgnoreCase" in macro


def test_render_macro_for_liquid_mode_targets_only_a_single_phase_liquid_material() -> None:
    macro = render_macro(
        _minimal_config(refrigerant_phase_mode="liquid"),
        _minimal_liquid_properties(),
        liquid_csv=None,
        vapor_csv=None,
        output_sim=Path("output.sim"),
    )

    assert 'REFRIGERANT_PHASE_MODE = "liquid"' in macro
    assert "getExistingSinglePhaseMaterial(continuum" in macro
    assert '"star.material.SinglePhaseLiquidModel"' in macro
    assert "setLiquidProperties(material, liquidTable);" in macro
    assert "setVaporProperties(material, vaporTable);" not in macro


def test_render_macro_for_vapor_mode_targets_only_a_single_phase_gas_material() -> None:
    macro = render_macro(
        _minimal_config(refrigerant_phase_mode="vapor"),
        _minimal_liquid_properties(),
        liquid_csv=None,
        vapor_csv=Path("vapor.csv"),
        output_sim=Path("output.sim"),
    )

    assert 'REFRIGERANT_PHASE_MODE = "vapor"' in macro
    assert "getExistingSinglePhaseMaterial(continuum" in macro
    assert '"star.material.SinglePhaseGasModel"' in macro
    assert "setLiquidProperties(material, liquidTable);" not in macro
    assert "setVaporProperties(material, vaporTable);" in macro


def test_render_macro_for_multiphase_mode_keeps_both_phase_material_writes() -> None:
    macro = render_macro(
        _minimal_config(refrigerant_phase_mode="multiphase"),
        _minimal_liquid_properties(),
        liquid_csv=None,
        vapor_csv=Path("vapor.csv"),
        output_sim=Path("output.sim"),
    )

    assert 'REFRIGERANT_PHASE_MODE = "multiphase"' in macro
    assert "EulerianMultiPhaseModel" in macro
    assert "setLiquidProperties(liquidMaterial, liquidTable);" in macro
    assert "setVaporProperties(vaporMaterial, vaporTable);" in macro


def test_fit_property_polynomials_from_refprop_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "vapor_properties.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Temperature (C),Density (kg/m^3),Equivalent Specific Heat (J/kg-K),"
                "Equivalent Thermal Conductivity (W/m-K),Equivalent Dynamic Viscosity (Pa-s),Enthalpy (J/kg)",
                "0,1000,2000,0.1,0.001,300000",
                "10,1020,2030,0.2,0.002,300500",
                "20,1040,2060,0.3,0.003,301000",
            ]
        ),
        encoding="utf-8-sig",
    )

    polynomials = _fit_property_polynomials(csv_path, degree=1)

    assert polynomials.temperature_min_c == pytest.approx(0.0)
    assert polynomials.temperature_max_c == pytest.approx(20.0)
    assert polynomials.density == pytest.approx((1000.0, 2.0))
    assert polynomials.specific_heat == pytest.approx((2000.0, 3.0))
    assert polynomials.thermal_conductivity == pytest.approx((0.1, 0.01))
    assert polynomials.dynamic_viscosity == pytest.approx((0.001, 0.0001))
    assert polynomials.enthalpy == pytest.approx((300000.0, 50.0))


def test_render_macro_can_write_refrigerant_properties_as_polynomials(tmp_path: Path) -> None:
    vapor_csv = tmp_path / "vapor_properties.csv"
    vapor_csv.write_text(
        "\n".join(
            [
                "Temperature (C),Density (kg/m^3),Equivalent Specific Heat (J/kg-K),"
                "Equivalent Thermal Conductivity (W/m-K),Equivalent Dynamic Viscosity (Pa-s),Enthalpy (J/kg)",
                "0,1000,2000,0.1,0.001,300000",
                "10,1020,2030,0.2,0.002,300500",
                "20,1040,2060,0.3,0.003,301000",
            ]
        ),
        encoding="utf-8-sig",
    )

    macro = render_macro(
        _minimal_config(
            refrigerant_property_write_mode="polynomial",
            refrigerant_polynomial_degree=1,
        ),
        _minimal_liquid_properties(),
        liquid_csv=None,
        vapor_csv=vapor_csv,
        output_sim=Path("output.sim"),
    )

    assert 'REFRIGERANT_PROPERTY_WRITE_MODE = "polynomial"' in macro
    assert "setVaporTemperaturePolynomials(material);" in macro
    assert "private static final double[] VAPOR_DENSITY_POLY" in macro
    assert "setTemperaturePolynomial(" in macro
    assert 'if ("table".equals(REFRIGERANT_PROPERTY_WRITE_MODE) && vaporTable == null)' in macro
    assert "setVaporTemperatureTables(material, table);" not in macro


def test_render_macro_can_write_liquid_refrigerant_properties_as_polynomials_independently(tmp_path: Path) -> None:
    vapor_csv = tmp_path / "vapor_properties.csv"
    liquid_csv = tmp_path / "liquid_properties.csv"
    csv_text = "\n".join(
        [
            "Temperature (C),Density (kg/m^3),Equivalent Specific Heat (J/kg-K),"
            "Equivalent Thermal Conductivity (W/m-K),Equivalent Dynamic Viscosity (Pa-s),Enthalpy (J/kg)",
            "0,1000,2000,0.1,0.001,300000",
            "10,1020,2030,0.2,0.002,300500",
            "20,1040,2060,0.3,0.003,301000",
        ]
    )
    vapor_csv.write_text(csv_text, encoding="utf-8-sig")
    liquid_csv.write_text(csv_text, encoding="utf-8-sig")

    macro = render_macro(
        _minimal_config(
            refrigerant_property_write_mode="table",
            liquid_refrigerant_property_write_mode="polynomial",
            refrigerant_polynomial_degree=1,
            liquid_property_mode="table",
        ),
        _minimal_liquid_properties(),
        liquid_csv=liquid_csv,
        vapor_csv=vapor_csv,
        output_sim=Path("output.sim"),
    )

    assert 'REFRIGERANT_PROPERTY_WRITE_MODE = "table"' in macro
    assert 'LIQUID_REFRIGERANT_PROPERTY_WRITE_MODE = "polynomial"' in macro
    assert "setLiquidTemperaturePolynomials(material);" in macro
    assert "private static final double[] LIQUID_DENSITY_POLY" in macro
    assert "setVaporTemperatureTables(material, table);" in macro
    assert "setVaporTemperaturePolynomials(material);" not in macro


def test_load_config_keeps_legacy_polynomial_mode_for_liquid_refrigerant(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        "\n".join(
            [
                "fluid:",
                "  name: R454C",
                "saturation:",
                "  type: pressure",
                "  value: 0.8",
                "gas_table:",
                "  temperature_start: 30",
                "  temperature_end: 40",
                "starccm:",
                "  continuum_name: Physics 1",
                "  refrigerant_property_write_mode: polynomial",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.refrigerant_property_write_mode == "polynomial"
    assert config.liquid_refrigerant_property_write_mode == "polynomial"


def _minimal_config(
    *,
    refrigerant_property_write_mode: str = "table",
    liquid_refrigerant_property_write_mode: str = "table",
    refrigerant_polynomial_degree: int = 4,
    liquid_property_mode: str = "saturation",
    refrigerant_phase_mode: str = "multiphase",
) -> ToolConfig:
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
        liquid_property_mode=liquid_property_mode,
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
        refrigerant_property_write_mode=refrigerant_property_write_mode,
        liquid_refrigerant_property_write_mode=liquid_refrigerant_property_write_mode,
        refrigerant_polynomial_degree=refrigerant_polynomial_degree,
        refrigerant_phase_mode=refrigerant_phase_mode,
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
