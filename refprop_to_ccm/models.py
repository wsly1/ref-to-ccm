from __future__ import annotations

from dataclasses import asdict, dataclass

from .units import k_to_c


@dataclass(frozen=True)
class SaturationState:
    temperature_k: float
    pressure_pa: float

    def to_json(self) -> dict[str, float]:
        return {
            "temperature_K": self.temperature_k,
            "temperature_C": k_to_c(self.temperature_k),
            "pressure_Pa": self.pressure_pa,
            "pressure_MPa": self.pressure_pa / 1.0e6,
        }


@dataclass(frozen=True)
class SaturatedMixtureState:
    temperature_k: float
    pressure_pa: float
    mass_quality: float
    enthalpy_j_per_kg: float
    liquid_density_kg_per_m3: float
    vapor_density_kg_per_m3: float


@dataclass(frozen=True)
class LiquidProperties:
    saturation_temperature_k: float
    saturation_pressure_pa: float
    specific_heat_j_per_kg_k: float
    standard_state_temperature_k: float
    thermal_conductivity_w_per_m_k: float
    dynamic_viscosity_pa_s: float
    density_kg_per_m3: float
    molecular_weight_kg_per_kmol: float
    saturated_liquid_enthalpy_j_per_kg: float
    saturated_vapor_enthalpy_j_per_kg: float
    liquid_standard_state_enthalpy_j_per_kg: float
    vapor_standard_state_enthalpy_j_per_kg: float
    heat_of_formation_input_j_per_kg: float
    vapor_heat_of_formation_input_j_per_kg: float
    density_temperature_derivative_kg_per_m3_k: float
    saturated_vapor_density_kg_per_m3: float = 0.0
    saturated_vapor_specific_heat_j_per_kg_k: float = 0.0
    saturated_vapor_thermal_conductivity_w_per_m_k: float = 0.0
    saturated_vapor_dynamic_viscosity_pa_s: float = 0.0
    liquid_standard_state_entropy_j_per_kg_k: float | None = None
    vapor_standard_state_entropy_j_per_kg_k: float | None = None

    def to_json(self) -> dict[str, float | None]:
        data = asdict(self)
        data["saturation_temperature_c"] = k_to_c(self.saturation_temperature_k)
        data["saturation_pressure_mpa"] = self.saturation_pressure_pa / 1.0e6
        return data


@dataclass(frozen=True)
class VaporRow:
    temperature_c: float
    density_kg_per_m3: float
    equivalent_specific_heat_j_per_kg_k: float
    equivalent_thermal_conductivity_w_per_m_k: float
    equivalent_dynamic_viscosity_pa_s: float
    enthalpy_j_per_kg: float


@dataclass(frozen=True)
class LiquidRow:
    temperature_c: float
    density_kg_per_m3: float
    equivalent_specific_heat_j_per_kg_k: float
    equivalent_thermal_conductivity_w_per_m_k: float
    equivalent_dynamic_viscosity_pa_s: float
    enthalpy_j_per_kg: float


@dataclass(frozen=True)
class CoolantRow:
    temperature_c: float
    density_kg_per_m3: float
    specific_heat_j_per_kg_k: float
    thermal_conductivity_w_per_m_k: float
    dynamic_viscosity_kg_per_m_s: float
    mass_fraction: float | None = None
    volume_fraction: float | None = None
    freezing_point_c: float | None = None
    boiling_point_c: float | None = None


@dataclass(frozen=True)
class CoolantCalculation:
    row: CoolantRow
    solve_mode: str
    volume_flow_l_min: float
    mass_flow_kg_s: float
    single_plate_mass_flow_kg_s: float
    inlet_temperature_c: float
    outlet_temperature_c: float
    heat_transfer_w: float
    outlet_direction: str = "heating"
    plate_count: int = 32
