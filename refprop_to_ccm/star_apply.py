from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from .config import ToolConfig
from .inlet_conditions import (
    CoolantInletCondition,
    RefrigerantInletCondition,
    calculate_refrigerant_inlet,
    describe_starccm_volume_fractions,
    load_coolant_calculation_from_xlsx,
    load_refrigerant_inlet_from_xlsx,
)
from .models import CoolantRow, LiquidProperties
from .starccm import STARCCM_RUN_TIMEOUT_SECONDS, render_macro


@dataclass(frozen=True)
class StarApplyResult:
    macro_file: Path
    star_log: Path | None = None


@dataclass(frozen=True)
class StarApplyConfig:
    source_type: str
    sim_file: Path
    output_sim_file: Path
    continuum_name: str
    liquid_phase_name: str
    vapor_phase_name: str
    starccm_exe: Path | None
    output_directory: Path
    liquid_json: Path | None = None
    liquid_csv: Path | None = None
    vapor_csv: Path | None = None
    vapor_specific_heat_source: str = "cp_table"
    liquid_property_mode: str = "saturation"
    coolant_xlsx: Path | None = None
    coolant_region_name: str = "Coolant"
    coolant_boundary_name: str = "Inlet"
    refrigerant_region_name: str = "Refrigerant"
    refrigerant_boundary_name: str = "Inlet"
    refrigerant_single_layer_mass_flow_kg_s: float | None = None
    refrigerant_vapor_volume_fraction: float | None = None
    refrigerant_heat_transfer_w: float | None = None
    refrigerant_layer_count: int = 18
    refrigerant_inlet_temperature_c: float = 98.0
    refrigerant_inlet_enthalpy_j_per_kg: float | None = None
    refrigerant_outlet_enthalpy_j_per_kg: float | None = None
    refrigerant_saturated_liquid_enthalpy_j_per_kg: float | None = None
    refrigerant_saturated_vapor_enthalpy_j_per_kg: float | None = None
    refrigerant_saturated_liquid_density_kg_per_m3: float | None = None
    refrigerant_saturated_vapor_density_kg_per_m3: float | None = None


def apply_star_from_outputs(config: StarApplyConfig, run_star: bool = False) -> StarApplyResult:
    config.output_directory.mkdir(parents=True, exist_ok=True)
    source_type = config.source_type.strip().lower()
    if source_type == "refprop":
        macro_text = _render_refprop_macro(config)
        macro_file = config.output_directory / "apply_refprop_to_star.java"
    elif source_type == "coolant":
        macro_text = _render_coolant_macro(config)
        macro_file = config.output_directory / "apply_coolant_to_star.java"
    elif source_type == "inlet_conditions":
        macro_text = _render_inlet_conditions_macro_from_config(config)
        macro_file = config.output_directory / "apply_inlet_conditions_to_star.java"
    elif source_type == "coolant_inlet_condition":
        macro_text = render_coolant_inlet_condition_macro(config, _coolant_inlet_from_config(config))
        macro_file = config.output_directory / "apply_coolant_inlet_to_star.java"
    elif source_type == "refrigerant_inlet_condition":
        macro_text = render_refrigerant_inlet_condition_macro(config, _refrigerant_inlet_from_config(config))
        macro_file = config.output_directory / "apply_refrigerant_inlet_to_star.java"
    else:
        raise ValueError(
            "source_type must be refprop, coolant, inlet_conditions, "
            "coolant_inlet_condition, or refrigerant_inlet_condition."
        )

    macro_file.write_text(macro_text, encoding="utf-8")
    star_log = run_starccm_macro(
        starccm_exe=config.starccm_exe,
        sim_file=config.sim_file,
        macro_file=macro_file.resolve(),
        output_directory=config.output_directory,
    ) if run_star else None
    return StarApplyResult(macro_file=macro_file.resolve(), star_log=star_log)


def _render_inlet_conditions_macro_from_config(config: StarApplyConfig) -> str:
    coolant = _coolant_inlet_from_config(config)
    if _has_direct_refrigerant_inlet(config):
        refrigerant = _direct_refrigerant_inlet(config)
    else:
        try:
            refrigerant = load_refrigerant_inlet_from_xlsx(config.coolant_xlsx) if config.coolant_xlsx is not None else None
        except Exception:
            refrigerant = None
    if refrigerant is None:
        heat_transfer_w = (
            coolant.heat_transfer_w
            if config.refrigerant_heat_transfer_w is None
            else config.refrigerant_heat_transfer_w
        )
        refrigerant = calculate_refrigerant_inlet(
            heat_transfer_w=heat_transfer_w,
            layer_count=config.refrigerant_layer_count,
            inlet_temperature_c=config.refrigerant_inlet_temperature_c,
            inlet_enthalpy_j_per_kg=_required_config_float(
                config.refrigerant_inlet_enthalpy_j_per_kg,
                "refrigerant_inlet_enthalpy_j_per_kg",
            ),
            outlet_enthalpy_j_per_kg=_required_config_float(
                config.refrigerant_outlet_enthalpy_j_per_kg,
                "refrigerant_outlet_enthalpy_j_per_kg",
            ),
            saturated_liquid_enthalpy_j_per_kg=_required_config_float(
                config.refrigerant_saturated_liquid_enthalpy_j_per_kg,
                "refrigerant_saturated_liquid_enthalpy_j_per_kg",
            ),
            saturated_vapor_enthalpy_j_per_kg=_required_config_float(
                config.refrigerant_saturated_vapor_enthalpy_j_per_kg,
                "refrigerant_saturated_vapor_enthalpy_j_per_kg",
            ),
            saturated_liquid_density_kg_per_m3=_required_config_float(
                config.refrigerant_saturated_liquid_density_kg_per_m3,
                "refrigerant_saturated_liquid_density_kg_per_m3",
            ),
            saturated_vapor_density_kg_per_m3=_required_config_float(
                config.refrigerant_saturated_vapor_density_kg_per_m3,
                "refrigerant_saturated_vapor_density_kg_per_m3",
            ),
        )
    return render_inlet_conditions_macro(config, coolant, refrigerant)


def _coolant_inlet_from_config(config: StarApplyConfig) -> CoolantInletCondition:
    if config.coolant_xlsx is None:
        raise ValueError("coolant_properties.xlsx is required for inlet condition STAR apply.")
    coolant_values = load_coolant_calculation_from_xlsx(config.coolant_xlsx)
    return CoolantInletCondition(
        single_plate_mass_flow_kg_s=coolant_values.single_plate_mass_flow_kg_s,
        inlet_temperature_c=coolant_values.inlet_temperature_c,
        heat_transfer_w=coolant_values.heat_transfer_w,
        volume_flow_l_min=coolant_values.volume_flow_l_min,
        mass_flow_kg_s=coolant_values.mass_flow_kg_s,
        outlet_temperature_c=coolant_values.outlet_temperature_c,
    )


def _render_refprop_macro(config: StarApplyConfig) -> str:
    if config.liquid_json is None:
        raise ValueError("liquid_properties.json is required for REFPROP STAR apply.")
    if config.vapor_csv is None:
        raise ValueError("vapor_properties.csv is required for REFPROP STAR apply.")
    liquid = load_liquid_properties(config.liquid_json)
    tool_config = ToolConfig(
        fluid_name="",
        fluid_components=None,
        saturation_type="pressure",
        saturation_value=0.0,
        saturation_unit="MPa",
        gas_pressure_value=None,
        gas_pressure_unit="MPa",
        gas_temperature_start=0.0,
        gas_temperature_end=0.0,
        gas_temperature_step=0.1,
        gas_temperature_unit="C",
        liquid_property_mode=config.liquid_property_mode,
        liquid_temperature_start=0.0,
        liquid_temperature_end=0.0,
        liquid_temperature_step=0.1,
        liquid_temperature_unit="C",
        sim_file=config.sim_file,
        output_sim_file=config.output_sim_file,
        continuum_name=config.continuum_name,
        liquid_phase_name=config.liquid_phase_name,
        vapor_phase_name=config.vapor_phase_name,
        vapor_specific_heat_source=config.vapor_specific_heat_source,
        starccm_exe=config.starccm_exe,
        output_directory=config.output_directory,
    )
    liquid_csv = config.liquid_csv if config.liquid_property_mode == "table" else None
    return render_macro(
        config=tool_config,
        liquid=liquid,
        liquid_csv=liquid_csv.resolve() if liquid_csv is not None else None,
        vapor_csv=config.vapor_csv.resolve(),
        output_sim=config.output_sim_file,
    )


def load_liquid_properties(path: Path) -> LiquidProperties:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    return LiquidProperties(
        saturation_temperature_k=float(data["saturation_temperature_k"]),
        saturation_pressure_pa=float(data["saturation_pressure_pa"]),
        specific_heat_j_per_kg_k=float(data["specific_heat_j_per_kg_k"]),
        standard_state_temperature_k=float(data["standard_state_temperature_k"]),
        thermal_conductivity_w_per_m_k=float(data["thermal_conductivity_w_per_m_k"]),
        dynamic_viscosity_pa_s=float(data["dynamic_viscosity_pa_s"]),
        density_kg_per_m3=float(data["density_kg_per_m3"]),
        molecular_weight_kg_per_kmol=float(data["molecular_weight_kg_per_kmol"]),
        saturated_liquid_enthalpy_j_per_kg=float(data["saturated_liquid_enthalpy_j_per_kg"]),
        saturated_vapor_enthalpy_j_per_kg=float(data["saturated_vapor_enthalpy_j_per_kg"]),
        liquid_standard_state_enthalpy_j_per_kg=float(data["liquid_standard_state_enthalpy_j_per_kg"]),
        vapor_standard_state_enthalpy_j_per_kg=float(data["vapor_standard_state_enthalpy_j_per_kg"]),
        heat_of_formation_input_j_per_kg=float(data["heat_of_formation_input_j_per_kg"]),
        vapor_heat_of_formation_input_j_per_kg=float(data["vapor_heat_of_formation_input_j_per_kg"]),
        density_temperature_derivative_kg_per_m3_k=float(data["density_temperature_derivative_kg_per_m3_k"]),
        liquid_standard_state_entropy_j_per_kg_k=(
            float(data["liquid_standard_state_entropy_j_per_kg_k"])
            if data.get("liquid_standard_state_entropy_j_per_kg_k") is not None
            else None
        ),
        vapor_standard_state_entropy_j_per_kg_k=(
            float(data["vapor_standard_state_entropy_j_per_kg_k"])
            if data.get("vapor_standard_state_entropy_j_per_kg_k") is not None
            else None
        ),
    )


def _render_coolant_macro(config: StarApplyConfig) -> str:
    if config.coolant_xlsx is None:
        raise ValueError("coolant_properties.xlsx is required for coolant STAR apply.")
    coolant = load_coolant_row(config.coolant_xlsx)
    return f"""// Auto-generated by refprop-to-ccm. Applies coolant constants from a generated workbook.
package macro;

import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import star.common.*;
import star.base.neo.*;
import star.material.*;

public class apply_coolant_to_star extends StarMacro {{
  private Simulation sim;
  private final List<String> successfulWrites = new ArrayList<String>();
  private final List<String> failedWrites = new ArrayList<String>();

  private static final String CONTINUUM_NAME = "{_java(config.continuum_name)}";
  private static final String LIQUID_PHASE_NAME = "{_java(config.liquid_phase_name)}";
  private static final String OUTPUT_SIM = "{_java(str(config.output_sim_file))}";

  public void execute() {{
    sim = getActiveSimulation();
    PhysicsContinuum continuum = getExistingContinuum();
    Material material = getLiquidMaterial(continuum);
    sim.println("[refprop-to-ccm] Applying coolant constants to " + material.getPresentationName());
    setConstantWithUnitsOrDefault(material, "star.energy.SpecificHeatProperty", {coolant.specific_heat_j_per_kg_k:.12g}, "J/kg-K", {coolant.specific_heat_j_per_kg_k:.12g}, "Specific Heat");
    setConstantWithUnitsOrDefault(material, "star.energy.ThermalConductivityProperty", {coolant.thermal_conductivity_w_per_m_k:.12g}, "W/m-K", {coolant.thermal_conductivity_w_per_m_k:.12g}, "Thermal Conductivity");
    setConstantWithUnitsOrDefault(material, "star.flow.DynamicViscosityProperty", {coolant.dynamic_viscosity_kg_per_m_s:.12g}, "Pa-s", {coolant.dynamic_viscosity_kg_per_m_s:.12g}, "Dynamic Viscosity");
    if (!setConstantWithUnitsOrDefault(material, "star.energy.PolynomialDensityProperty", {coolant.density_kg_per_m3:.12g}, "kg/m^3", {coolant.density_kg_per_m3:.12g}, "Polynomial Density")) {{
      setConstantWithUnitsOrDefault(material, "star.flow.ConstantDensityProperty", {coolant.density_kg_per_m3:.12g}, "kg/m^3", {coolant.density_kg_per_m3:.12g}, "Constant Density");
    }}
    sim.println("[refprop-to-ccm] Coolant table temperature C = {coolant.temperature_c:.12g}");
    writeApplySummary();
    sim.println("[refprop-to-ccm] Saving simulation as: " + OUTPUT_SIM);
    sim.saveState(OUTPUT_SIM);
  }}

  private PhysicsContinuum getExistingContinuum() {{
    try {{
      Continuum continuum = sim.getContinuumManager().getContinuum(CONTINUUM_NAME);
      if (continuum == null) {{
        throw new RuntimeException("Continuum not found: " + CONTINUUM_NAME);
      }}
      return (PhysicsContinuum) continuum;
    }} catch (Throwable ex) {{
      throw new RuntimeException("Could not find target physics continuum '" + CONTINUUM_NAME + "'.", ex);
    }}
  }}

  private Material getLiquidMaterial(PhysicsContinuum continuum) {{
    Material phaseMaterial = getMaterialFromPhaseBestEffort(continuum);
    if (phaseMaterial != null) {{
      return phaseMaterial;
    }}
    for (String className : Arrays.asList(
      "star.material.SinglePhaseLiquidModel",
      "star.material.SingleComponentLiquidModel"
    )) {{
      try {{
        Class modelClass = Class.forName(className);
        Object model = continuum.getModelManager().getModel(modelClass);
        if (model != null) {{
          return (Material) model.getClass().getMethod("getMaterial").invoke(model);
        }}
      }} catch (Throwable ex) {{
        sim.println("[refprop-to-ccm] Continuum liquid material lookup skipped: " + className + " -> " + ex.getMessage());
      }}
    }}
    throw new RuntimeException("No supported liquid material model found. Check continuum and liquid phase name.");
  }}

  private Material getMaterialFromPhaseBestEffort(PhysicsContinuum continuum) {{
    try {{
      EulerianMultiPhaseModel multiphase = continuum.getModelManager().getModel(EulerianMultiPhaseModel.class);
      if (multiphase == null || LIQUID_PHASE_NAME.length() == 0) {{
        return null;
      }}
      Phase phase = multiphase.getPhaseManager().getPhase(LIQUID_PHASE_NAME);
      if (phase == null) {{
        return null;
      }}
      EulerianPhase eulerianPhase = (EulerianPhase) phase;
      for (String className : Arrays.asList(
        "star.material.SinglePhaseLiquidModel",
        "star.material.SingleComponentLiquidModel"
      )) {{
        try {{
          Class modelClass = Class.forName(className);
          Object model = eulerianPhase.getModelManager().getModel(modelClass);
          if (model != null) {{
            return (Material) model.getClass().getMethod("getMaterial").invoke(model);
          }}
        }} catch (Throwable ex) {{
          sim.println("[refprop-to-ccm] Phase liquid material lookup skipped: " + className + " -> " + ex.getMessage());
        }}
      }}
    }} catch (Throwable ex) {{
      sim.println("[refprop-to-ccm] Phase material lookup skipped: " + ex.getMessage());
    }}
    return null;
  }}

  private boolean setConstantWithUnitsOrDefault(Material material, String propertyClassName, double value, String unitName, double defaultUnitValue, String label) {{
    try {{
      Class propertyClass = Class.forName(propertyClassName);
      MaterialProperty property = (MaterialProperty) material.getMaterialProperties().getMaterialProperty(propertyClass);
      property.setConstant(defaultUnitValue);
      MaterialPropertyMethod method = property.getMethod();
      Object quantity = method.getClass().getMethod("getQuantity").invoke(method);
      try {{
        Units units = (Units) sim.getUnitsManager().getObject(unitName);
        quantity.getClass().getMethod("setValueAndUnits", double.class, Units.class).invoke(quantity, value, units);
        recordSuccess(label + " = " + value + " " + unitName + " (explicit unit)");
        return true;
      }} catch (Throwable unitEx) {{
        sim.println("[refprop-to-ccm] Explicit unit write failed for " + label + " via " + propertyClassName + "; trying fallback default-unit numeric value = " + defaultUnitValue + ": " + unitEx.getMessage());
      }}
      quantity.getClass().getMethod("setValue", double.class).invoke(quantity, defaultUnitValue);
      recordSuccess(label + " = " + defaultUnitValue + " (fallback default-unit numeric value; source " + value + " " + unitName + ")");
      return true;
    }} catch (Throwable ex) {{
      recordFailure(label + " via " + propertyClassName + ": " + ex.getMessage());
      return false;
    }}
  }}

  private void recordSuccess(String detail) {{
    successfulWrites.add(detail);
    sim.println("[refprop-to-ccm] SUCCESS: " + detail);
  }}

  private void recordFailure(String detail) {{
    failedWrites.add(detail);
    sim.println("[refprop-to-ccm] FAILED: " + detail);
  }}

  private void writeApplySummary() {{
    sim.println("[refprop-to-ccm] Apply summary: succeeded=" + successfulWrites.size() + ", failed=" + failedWrites.size());
    for (String detail : successfulWrites) {{
      sim.println("[refprop-to-ccm]   SUCCESS: " + detail);
    }}
    for (String detail : failedWrites) {{
      sim.println("[refprop-to-ccm]   FAILED: " + detail);
    }}
  }}
}}
"""


def render_inlet_conditions_macro(
    config: StarApplyConfig,
    coolant: CoolantInletCondition,
    refrigerant: RefrigerantInletCondition,
) -> str:
    return f"""// Auto-generated by refprop-to-ccm. Applies inlet conditions from generated workbook outputs.
package macro;

import java.util.ArrayList;
import java.util.List;

import star.common.*;
import star.flow.*;
import star.material.*;
import star.base.neo.DoubleVector;

public class apply_inlet_conditions_to_star extends StarMacro {{
  private Simulation sim;
  private final List<String> successfulWrites = new ArrayList<String>();
  private final List<String> failedWrites = new ArrayList<String>();

  private static final String OUTPUT_SIM = "{_java(str(config.output_sim_file))}";
  private static final String CONTINUUM_NAME = "{_java(config.continuum_name)}";
  private static final String LIQUID_PHASE_NAME = "{_java(config.liquid_phase_name)}";
  private static final String VAPOR_PHASE_NAME = "{_java(config.vapor_phase_name)}";

  private static final class CoolantTarget {{
    private static final String REGION_NAME = "{_java(config.coolant_region_name)}";
    private static final String BOUNDARY_NAME = "{_java(config.coolant_boundary_name)}";
    private static final double SINGLE_PLATE_MASS_FLOW_KG_S = {coolant.single_plate_mass_flow_kg_s:.12g};
    private static final double INLET_TEMPERATURE_C = {coolant.inlet_temperature_c:.12g};
  }}

  private static final class RefrigerantTarget {{
    private static final String REGION_NAME = "{_java(config.refrigerant_region_name)}";
    private static final String BOUNDARY_NAME = "{_java(config.refrigerant_boundary_name)}";
    private static final double SINGLE_LAYER_MASS_FLOW_KG_S = {refrigerant.single_layer_mass_flow_kg_s:.12g};
    private static final double INLET_TEMPERATURE_C = {refrigerant.inlet_temperature_c:.12g};
    private static final double LIQUID_VOLUME_FRACTION = {refrigerant.liquid_volume_fraction:.12g};
    private static final double VAPOR_VOLUME_FRACTION = {refrigerant.vapor_volume_fraction:.12g};
  }}

  public void execute() {{
    sim = getActiveSimulation();
    Boundary coolantBoundary = getBoundary("coolant", CoolantTarget.REGION_NAME, CoolantTarget.BOUNDARY_NAME);
    sim.println("[refprop-to-ccm] Coolant single-plate mass flow kg/s = " + CoolantTarget.SINGLE_PLATE_MASS_FLOW_KG_S);
    sim.println("[refprop-to-ccm] Coolant inlet temperature C = " + CoolantTarget.INLET_TEMPERATURE_C);
    setBoundaryScalarAny(
      coolantBoundary,
      new String[] {{"star.flow.MassFlowRateProfile"}},
      CoolantTarget.SINGLE_PLATE_MASS_FLOW_KG_S,
      "kg/s",
      CoolantTarget.SINGLE_PLATE_MASS_FLOW_KG_S,
      "coolant mass flow"
    );
    setBoundaryScalarAny(
      coolantBoundary,
      new String[] {{"star.energy.StaticTemperatureProfile", "star.energy.TotalTemperatureProfile", "star.energy.TemperatureProfile"}},
      CoolantTarget.INLET_TEMPERATURE_C,
      "C",
      {coolant.inlet_temperature_c + 273.15:.12g},
      "coolant inlet temperature"
    );

    Boundary refrigerantBoundary = getBoundary("refrigerant", RefrigerantTarget.REGION_NAME, RefrigerantTarget.BOUNDARY_NAME);
    sim.println("[refprop-to-ccm] Refrigerant single-layer mass flow kg/s = " + RefrigerantTarget.SINGLE_LAYER_MASS_FLOW_KG_S);
    sim.println("[refprop-to-ccm] Refrigerant inlet temperature C = " + RefrigerantTarget.INLET_TEMPERATURE_C);
    sim.println("[refprop-to-ccm] Refrigerant phase fractions: " + LIQUID_PHASE_NAME + "=" + RefrigerantTarget.LIQUID_VOLUME_FRACTION + ", " + VAPOR_PHASE_NAME + "=" + RefrigerantTarget.VAPOR_VOLUME_FRACTION);
    setBoundaryScalarAny(
      refrigerantBoundary,
      new String[] {{"star.flow.MassFlowRateProfile"}},
      RefrigerantTarget.SINGLE_LAYER_MASS_FLOW_KG_S,
      "kg/s",
      RefrigerantTarget.SINGLE_LAYER_MASS_FLOW_KG_S,
      "refrigerant mass flow"
    );
    setBoundaryScalarAny(
      refrigerantBoundary,
      new String[] {{"star.energy.StaticTemperatureProfile", "star.energy.TotalTemperatureProfile", "star.energy.TemperatureProfile"}},
      RefrigerantTarget.INLET_TEMPERATURE_C,
      "C",
      {refrigerant.inlet_temperature_c + 273.15:.12g},
      "refrigerant inlet temperature"
    );
    setVolumeFraction(refrigerantBoundary, CONTINUUM_NAME, LIQUID_PHASE_NAME, VAPOR_PHASE_NAME, RefrigerantTarget.LIQUID_VOLUME_FRACTION, RefrigerantTarget.VAPOR_VOLUME_FRACTION);

    writeApplySummary();
    sim.println("[refprop-to-ccm] Saving simulation as: " + OUTPUT_SIM);
    sim.saveState(OUTPUT_SIM);
  }}

{_boundary_macro_helpers()}
"""


def render_coolant_inlet_condition_macro(config: StarApplyConfig, coolant: CoolantInletCondition) -> str:
    return f"""// Auto-generated by refprop-to-ccm. Applies coolant inlet condition.
package macro;

import java.util.ArrayList;
import java.util.List;

import star.common.*;

public class apply_coolant_inlet_to_star extends StarMacro {{
  private Simulation sim;
  private final List<String> successfulWrites = new ArrayList<String>();
  private final List<String> failedWrites = new ArrayList<String>();

  private static final String OUTPUT_SIM = "{_java(str(config.output_sim_file))}";
  private static final String REGION_NAME = "{_java(config.coolant_region_name)}";
  private static final String BOUNDARY_NAME = "{_java(config.coolant_boundary_name)}";
  private static final double MASS_FLOW_KG_S = {coolant.single_plate_mass_flow_kg_s:.12g};
  private static final double INLET_TEMPERATURE_C = {coolant.inlet_temperature_c:.12g};

  public void execute() {{
    sim = getActiveSimulation();
    Boundary boundary = getBoundary("coolant", REGION_NAME, BOUNDARY_NAME);
    sim.println("[refprop-to-ccm] Coolant single-plate mass flow kg/s = " + MASS_FLOW_KG_S);
    sim.println("[refprop-to-ccm] Coolant inlet temperature C = " + INLET_TEMPERATURE_C);
    setBoundaryScalarAny(boundary, new String[] {{"star.flow.MassFlowRateProfile"}}, MASS_FLOW_KG_S, "kg/s", MASS_FLOW_KG_S, "coolant mass flow");
    setBoundaryScalarAny(boundary, new String[] {{"star.energy.StaticTemperatureProfile", "star.energy.TotalTemperatureProfile", "star.energy.TemperatureProfile"}}, INLET_TEMPERATURE_C, "C", {coolant.inlet_temperature_c + 273.15:.12g}, "coolant inlet temperature");
    writeApplySummary();
    sim.println("[refprop-to-ccm] Saving simulation as: " + OUTPUT_SIM);
    sim.saveState(OUTPUT_SIM);
  }}

{_boundary_macro_helpers(include_volume_fraction=False)}
"""


def render_refrigerant_inlet_condition_macro(config: StarApplyConfig, refrigerant: RefrigerantInletCondition) -> str:
    return f"""// Auto-generated by refprop-to-ccm. Applies refrigerant inlet condition.
package macro;

import java.util.ArrayList;
import java.util.List;

import star.common.*;
import star.flow.*;
import star.material.*;
import star.base.neo.DoubleVector;

public class apply_refrigerant_inlet_to_star extends StarMacro {{
  private Simulation sim;
  private final List<String> successfulWrites = new ArrayList<String>();
  private final List<String> failedWrites = new ArrayList<String>();

  private static final String OUTPUT_SIM = "{_java(str(config.output_sim_file))}";
  private static final String CONTINUUM_NAME = "{_java(config.continuum_name)}";
  private static final String LIQUID_PHASE_NAME = "{_java(config.liquid_phase_name)}";
  private static final String VAPOR_PHASE_NAME = "{_java(config.vapor_phase_name)}";
  private static final String REGION_NAME = "{_java(config.refrigerant_region_name)}";
  private static final String BOUNDARY_NAME = "{_java(config.refrigerant_boundary_name)}";
  private static final double MASS_FLOW_KG_S = {refrigerant.single_layer_mass_flow_kg_s:.12g};
  private static final double INLET_TEMPERATURE_C = {refrigerant.inlet_temperature_c:.12g};
  private static final double LIQUID_VOLUME_FRACTION = {refrigerant.liquid_volume_fraction:.12g};
  private static final double VAPOR_VOLUME_FRACTION = {refrigerant.vapor_volume_fraction:.12g};

  public void execute() {{
    sim = getActiveSimulation();
    Boundary boundary = getBoundary("refrigerant", REGION_NAME, BOUNDARY_NAME);
    sim.println("[refprop-to-ccm] Refrigerant single-layer mass flow kg/s = " + MASS_FLOW_KG_S);
    sim.println("[refprop-to-ccm] Refrigerant inlet temperature C = " + INLET_TEMPERATURE_C);
    sim.println("[refprop-to-ccm] Refrigerant phase fractions: " + LIQUID_PHASE_NAME + "=" + LIQUID_VOLUME_FRACTION + ", " + VAPOR_PHASE_NAME + "=" + VAPOR_VOLUME_FRACTION);
    setBoundaryScalarAny(boundary, new String[] {{"star.flow.MassFlowRateProfile"}}, MASS_FLOW_KG_S, "kg/s", MASS_FLOW_KG_S, "refrigerant mass flow");
    setBoundaryScalarAny(boundary, new String[] {{"star.energy.StaticTemperatureProfile", "star.energy.TotalTemperatureProfile", "star.energy.TemperatureProfile"}}, INLET_TEMPERATURE_C, "C", {refrigerant.inlet_temperature_c + 273.15:.12g}, "refrigerant inlet temperature");
    setVolumeFraction(boundary, CONTINUUM_NAME, LIQUID_PHASE_NAME, VAPOR_PHASE_NAME, LIQUID_VOLUME_FRACTION, VAPOR_VOLUME_FRACTION);
    writeApplySummary();
    sim.println("[refprop-to-ccm] Saving simulation as: " + OUTPUT_SIM);
    sim.saveState(OUTPUT_SIM);
  }}

{_boundary_macro_helpers()}
"""


def load_coolant_row(path: Path) -> CoolantRow:
    values = _read_xlsx_numeric_cells(path)
    return CoolantRow(
        temperature_c=values["A16"],
        density_kg_per_m3=values["B16"],
        specific_heat_j_per_kg_k=values["C16"],
        thermal_conductivity_w_per_m_k=values["D16"],
        dynamic_viscosity_kg_per_m_s=values["E16"],
    )


def _read_xlsx_numeric_cells(path: Path) -> dict[str, float]:
    with ZipFile(path) as workbook:
        sheet_xml = workbook.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(sheet_xml)
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    result: dict[str, float] = {}
    for cell in root.findall(".//x:c", namespace):
        ref = cell.attrib.get("r", "")
        if ref not in {"A16", "B16", "C16", "D16", "E16"}:
            continue
        value_node = cell.find("x:v", namespace)
        if value_node is not None and value_node.text is not None:
            result[ref] = float(value_node.text)
    missing = {"A16", "B16", "C16", "D16", "E16"} - result.keys()
    if missing:
        raise ValueError(f"Coolant workbook is missing expected numeric cells: {', '.join(sorted(missing))}")
    return result


def run_starccm_macro(
    starccm_exe: Path | None,
    sim_file: Path,
    macro_file: Path,
    output_directory: Path,
) -> Path:
    if starccm_exe is None:
        raise ValueError("STAR-CCM+ executable is required when running STAR.")
    if not starccm_exe.exists():
        raise FileNotFoundError(f"STAR-CCM+ executable does not exist: {starccm_exe}")
    if not sim_file.exists():
        raise FileNotFoundError(f"STAR-CCM+ sim file does not exist: {sim_file}")
    command = [str(starccm_exe), "-batch", str(macro_file), str(sim_file)]
    log_file = output_directory / "starccm_apply_run.log"
    with log_file.open("w", encoding="utf-8", errors="replace") as handle:
        handle.write("Command:\n")
        handle.write(" ".join(command))
        handle.write("\n\nOutput:\n")
        try:
            completed = subprocess.run(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=STARCCM_RUN_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            handle.write(f"\nSTAR-CCM+ run timed out after {STARCCM_RUN_TIMEOUT_SECONDS} seconds.\n")
            raise TimeoutError(
                f"STAR-CCM+ 运行超时（超过 {STARCCM_RUN_TIMEOUT_SECONDS} 秒）。"
                f"日志: {log_file.resolve()}"
            ) from exc
    if completed.returncode != 0:
        raise RuntimeError(f"STAR-CCM+ run failed with exit code {completed.returncode}. Log: {log_file.resolve()}")
    return log_file.resolve()


def _java(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _has_direct_refrigerant_inlet(config: StarApplyConfig) -> bool:
    return (
        config.refrigerant_single_layer_mass_flow_kg_s is not None
        and config.refrigerant_vapor_volume_fraction is not None
        and config.refrigerant_inlet_temperature_c is not None
    )


def _refrigerant_inlet_from_config(config: StarApplyConfig) -> RefrigerantInletCondition:
    if _has_direct_refrigerant_inlet(config):
        return _direct_refrigerant_inlet(config)
    if config.coolant_xlsx is not None:
        return load_refrigerant_inlet_from_xlsx(config.coolant_xlsx)
    return _direct_refrigerant_inlet(config)


def _direct_refrigerant_inlet(config: StarApplyConfig) -> RefrigerantInletCondition:
    mass_flow = _required_config_float(
        config.refrigerant_single_layer_mass_flow_kg_s,
        "refrigerant_single_layer_mass_flow_kg_s",
    )
    if mass_flow <= 0.0:
        raise ValueError("refrigerant_single_layer_mass_flow_kg_s must be greater than 0.")
    vapor_fraction = _required_config_float(
        config.refrigerant_vapor_volume_fraction,
        "refrigerant_vapor_volume_fraction",
    )
    if vapor_fraction < 0.0 or vapor_fraction > 1.0:
        raise ValueError("refrigerant_vapor_volume_fraction must be between 0 and 1.")
    liquid_fraction = 1.0 - vapor_fraction
    return RefrigerantInletCondition(
        total_mass_flow_kg_s=mass_flow,
        single_layer_mass_flow_kg_s=mass_flow,
        inlet_temperature_c=float(config.refrigerant_inlet_temperature_c),
        quality=vapor_fraction,
        vapor_volume_fraction=vapor_fraction,
        liquid_volume_fraction=liquid_fraction,
        starccm_volume_fraction=describe_starccm_volume_fractions(vapor_fraction, liquid_fraction),
    )


def _boundary_macro_helpers(*, include_volume_fraction: bool = True) -> str:
    volume_fraction_helper = """
  private void setVolumeFraction(
      Boundary boundary,
      String continuumName,
      String liquidPhaseName,
      String vaporPhaseName,
      double liquidFraction,
      double vaporFraction) {
    try {
      PhysicsContinuum continuum = (PhysicsContinuum) sim.getContinuumManager().getContinuum(continuumName);
      if (continuum == null) {
        throw new RuntimeException("Continuum not found: " + continuumName);
      }
      EulerianMultiPhaseModel multiphase = continuum.getModelManager().getModel(EulerianMultiPhaseModel.class);
      if (multiphase == null) {
        throw new RuntimeException("Continuum does not have EulerianMultiPhaseModel: " + continuumName);
      }
      if (multiphase.getPhaseManager().getObjects().size() != 2) {
        throw new RuntimeException("Volume fraction writer requires exactly two configured phases.");
      }
      double[] orderedFractions = new double[2];
      boolean liquidFound = false;
      boolean vaporFound = false;
      int index = 0;
      for (Object object : multiphase.getPhaseManager().getObjects()) {
        Phase phase = (Phase) object;
        String phaseName = phase.getPresentationName();
        if (phaseName.equals(liquidPhaseName)) {
          orderedFractions[index] = liquidFraction;
          liquidFound = true;
        } else if (phaseName.equals(vaporPhaseName)) {
          orderedFractions[index] = vaporFraction;
          vaporFound = true;
        } else {
          throw new RuntimeException("Unexpected phase in continuum: " + phaseName);
        }
        index++;
      }
      if (!liquidFound || !vaporFound) {
        throw new RuntimeException(
          "Could not find configured phase names: liquid=" + liquidPhaseName + ", vapor=" + vaporPhaseName
        );
      }
      VolumeFractionProfile profile = boundary.getValues().get(VolumeFractionProfile.class);
      profile.getMethod(ConstantArrayProfileMethod.class).getQuantity().setArray(new DoubleVector(orderedFractions));
      recordSuccess(
        "Set volume fractions in continuum order: " +
        multiphase.getPhaseManager().getObjects().toString() + " = " + new DoubleVector(orderedFractions).toString()
      );
    } catch (Throwable ex) {
      recordFailure("Volume fraction write skipped: " + ex.getMessage());
    }
  }
""" if include_volume_fraction else ""
    return """  private Boundary getBoundary(String label, String regionName, String boundaryName) {
    Region region = sim.getRegionManager().getRegion(regionName);
    if (region == null) {
      throw new RuntimeException("Region not found for " + label + ": " + regionName);
    }
    Boundary boundary = region.getBoundaryManager().getBoundary(boundaryName);
    if (boundary == null) {
      throw new RuntimeException("Boundary not found for " + label + ": " + regionName + "/" + boundaryName);
    }
    sim.println("[refprop-to-ccm] Target " + label + " boundary = " + regionName + "/" + boundaryName);
    return boundary;
  }

  private boolean setBoundaryScalarAny(Boundary boundary, String[] profileClassNames, double value, String unitName, double defaultUnitValue, String label) {
    for (String profileClassName : profileClassNames) {
      if (setBoundaryScalar(boundary, profileClassName, value, unitName, defaultUnitValue, label)) {
        return true;
      }
    }
    recordFailure("Could not set " + label + " on boundary " + boundary.getPresentationName());
    return false;
  }

  private boolean setBoundaryScalar(Boundary boundary, String profileClassName, double value, String unitName, double defaultUnitValue, String label) {
    try {
      Class profileClass = Class.forName(profileClassName);
      Object profile = boundary.getValues().get(profileClass);
      if (profile == null) {
        return false;
      }
      Class methodClass = Class.forName("star.common.ConstantScalarProfileMethod");
      profile.getClass().getMethod("setMethod", Class.class).invoke(profile, methodClass);
      Object method = profile.getClass().getMethod("getMethod", Class.class).invoke(profile, methodClass);
      Object quantity = method.getClass().getMethod("getQuantity").invoke(method);
      try {
        Units units = (Units) sim.getUnitsManager().getObject(unitName);
        quantity.getClass().getMethod("setValueAndUnits", double.class, Units.class).invoke(quantity, value, units);
        recordSuccess(label + " via " + profileClassName + " = " + value + " " + unitName + " (explicit unit)");
        return true;
      } catch (Throwable unitEx) {
        sim.println("[refprop-to-ccm] Explicit unit write failed for " + label + " via " + profileClassName + "; trying fallback default-unit numeric value = " + defaultUnitValue + ": " + unitEx.getMessage());
      }
      quantity.getClass().getMethod("setValue", double.class).invoke(quantity, defaultUnitValue);
      recordSuccess(label + " via " + profileClassName + " = " + defaultUnitValue + " (fallback default-unit numeric value; source " + value + " " + unitName + ")");
      return true;
    } catch (Throwable ex) {
      sim.println("[refprop-to-ccm] Boundary scalar write skipped for " + label + " via " + profileClassName + ": " + ex.getMessage());
      return false;
    }
  }

  private void recordSuccess(String detail) {
    successfulWrites.add(detail);
    sim.println("[refprop-to-ccm] SUCCESS: " + detail);
  }

  private void recordFailure(String detail) {
    failedWrites.add(detail);
    sim.println("[refprop-to-ccm] FAILED: " + detail);
  }

  private void writeApplySummary() {
    sim.println("[refprop-to-ccm] Apply summary: succeeded=" + successfulWrites.size() + ", failed=" + failedWrites.size());
    for (String detail : successfulWrites) {
      sim.println("[refprop-to-ccm]   SUCCESS: " + detail);
    }
    for (String detail : failedWrites) {
      sim.println("[refprop-to-ccm]   FAILED: " + detail);
    }
  }

""" + volume_fraction_helper + "}"""


def _required_config_float(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"{name} is required for inlet condition STAR apply.")
    return float(value)
