from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from .models import LiquidProperties, LiquidRow, SaturatedMixtureState, SaturationState, VaporRow
from .units import k_to_c

ALLOWED_REFPROP_WARNINGS = {-319, -320, -113}
EPSILON = 1.0e-10
TEMPERATURE_EPSILON = 1.0e-6
MAX_ABS_SPECIFIC_ENTROPY_J_PER_KG_K = 1.0e7
_REFPROP_UNIT_MASS_BASE_SI = "mass_base_si"
_REFPROP_UNIT_MASS_SI = "mass_si"
_LEGACY_REFPROP_MASS_SI = 2
_REFPROP_PQ_MASS_QUALITY = 2
_MISSING_REFPROPDLL_FRAGMENT = "REFPROPdll could not be loaded"
_MASS_SI_OUTPUT_SCALE = {
    "E": 1000.0,
    "H": 1000.0,
    "S": 1000.0,
    "CV": 1000.0,
    "CP": 1000.0,
    "CPLIQ": 1000.0,
    "CPVAP": 1000.0,
    "P": 1.0e6,
    "TCX": 1.0e-3,
    "VIS": 1.0e-6,
}
_MASS_SI_OUTPUT_UNCHANGED = {"T", "D", "DLIQ", "DVAP"}


class RefpropClient:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or os.environ.get("RPprefix", r"C:\Program Files (x86)\REFPROP"))
        if not self.root.exists():
            raise FileNotFoundError(f"REFPROP root does not exist: {self.root}")

        try:
            from ctREFPROP.ctREFPROP import REFPROPFunctionLibrary
        except ImportError as exc:
            raise RuntimeError(
                "ctREFPROP is required. Install it with: python -m pip install -r requirements.txt"
            ) from exc

        self.rp = REFPROPFunctionLibrary(str(self.root))
        self.rp.SETPATHdll(str(self.root))
        self._pq_unit_code, self._pq_unit_system = _resolve_refprop_pq_units(self.rp)
        self.loaded_fluid = ""
        self.z: list[float] = [1.0]
        self.last_equivalent_replacement_count = 0
        self.last_equivalent_quality_points: int | None = None

    def load_fluid(self, fluid_name: str, components: list[dict[str, Any]] | None = None) -> None:
        if components:
            names = [str(item["name"]).strip() for item in components]
            fractions = [float(item["fraction"]) for item in components]
            basis = str(components[0].get("basis", "mole")).strip().lower()
            if basis != "mole":
                raise ValueError("Only mole fractions are currently supported for custom mixtures.")
            self.loaded_fluid = "|".join(_as_fld_name(name) for name in names)
            ierr, herr = self.rp.SETUPdll(len(names), self.loaded_fluid, "HMX.BNC", "DEF")
            self._check(ierr, herr, f"loading mixture {self.loaded_fluid}")
            self.z = fractions
            return

        mix_file = self.root / "MIXTURES" / f"{fluid_name.upper()}.MIX"
        if mix_file.exists():
            self.loaded_fluid = str(mix_file)
            setup = self.rp.SETMIXTUREdll(str(mix_file))
            self._check(setup.ierr, getattr(setup, "herr", ""), f"loading mixture file {mix_file}")
            self.z = list(setup.z)
            return

        fluid_file = fluid_name.upper()
        if not fluid_file.endswith(".FLD"):
            fluid_file += ".FLD"
        self.loaded_fluid = fluid_file
        ierr, herr = self.rp.SETUPdll(1, fluid_file, "HMX.BNC", "DEF")
        self._check(ierr, herr, f"loading fluid {fluid_file}")
        self.z = [1.0]

    def saturation_from_pressure(self, fluid_name: str, pressure_pa: float) -> SaturationState:
        pressure_kpa = pressure_pa / 1000.0
        sat = self.rp.SATPdll(pressure_kpa, self.z, 1)
        self._check(sat.ierr, sat.herr, f"calculating saturation from pressure for {fluid_name}")
        return SaturationState(temperature_k=sat.T, pressure_pa=pressure_pa)

    def saturation_from_temperature(self, fluid_name: str, temperature_k: float) -> SaturationState:
        sat = self.rp.SATTdll(temperature_k, self.z, 1)
        self._check(sat.ierr, sat.herr, f"calculating saturation from temperature for {fluid_name}")
        return SaturationState(temperature_k=temperature_k, pressure_pa=sat.P * 1000.0)

    def saturated_liquid_properties(self, fluid_name: str, saturation: SaturationState) -> LiquidProperties:
        sat = self.rp.SATTdll(saturation.temperature_k, self.z, 1)
        self._check(sat.ierr, sat.herr, f"calculating saturated liquid state for {fluid_name}")
        liquid_composition = list(getattr(sat, "x", self.z))
        vapor_composition = list(getattr(sat, "y", self.z))
        props = self._properties_td(saturation.temperature_k, sat.Dl, liquid_composition)
        vapor_props = self._properties_td(saturation.temperature_k, sat.Dv, vapor_composition)
        liquid_entropy = self._refprop_pq(saturation.pressure_pa, 0.0, "S")
        vapor_entropy = self._refprop_pq(saturation.pressure_pa, 1.0, "S")
        return LiquidProperties(
            saturation_temperature_k=saturation.temperature_k,
            saturation_pressure_pa=saturation.pressure_pa,
            specific_heat_j_per_kg_k=props["cp"],
            standard_state_temperature_k=saturation.temperature_k,
            thermal_conductivity_w_per_m_k=props["thermal_conductivity"],
            dynamic_viscosity_pa_s=props["dynamic_viscosity"],
            density_kg_per_m3=props["density"],
            molecular_weight_kg_per_kmol=props["molecular_weight"],
            saturated_liquid_enthalpy_j_per_kg=props["enthalpy"],
            saturated_vapor_enthalpy_j_per_kg=vapor_props["enthalpy"],
            saturated_vapor_density_kg_per_m3=vapor_props["density"],
            saturated_vapor_specific_heat_j_per_kg_k=vapor_props["cp"],
            saturated_vapor_thermal_conductivity_w_per_m_k=vapor_props["thermal_conductivity"],
            saturated_vapor_dynamic_viscosity_pa_s=vapor_props["dynamic_viscosity"],
            liquid_standard_state_enthalpy_j_per_kg=props["enthalpy"],
            vapor_standard_state_enthalpy_j_per_kg=vapor_props["enthalpy"],
            heat_of_formation_input_j_per_kg=props["enthalpy"],
            vapor_heat_of_formation_input_j_per_kg=vapor_props["enthalpy"],
            density_temperature_derivative_kg_per_m3_k=0.0,
            liquid_standard_state_entropy_j_per_kg_k=liquid_entropy,
            vapor_standard_state_entropy_j_per_kg_k=vapor_entropy,
        )

    def enthalpy_tp(self, fluid_name: str, pressure_pa: float, temperature_k: float) -> float:
        pressure_kpa = pressure_pa / 1000.0
        flash = self.rp.TPFLSHdll(temperature_k, pressure_kpa, self.z)
        self._check(flash.ierr, flash.herr, f"calculating enthalpy for {fluid_name} at T={temperature_k} K, P={pressure_pa} Pa")
        flash_enthalpy_j_per_mol = getattr(flash, "h", None)
        if flash_enthalpy_j_per_mol is not None and math.isfinite(float(flash_enthalpy_j_per_mol)):
            molecular_weight = self.rp.WMOLdll(self.z)
            if molecular_weight <= 0.0:
                raise RuntimeError("REFPROP returned a non-positive molecular weight for TP enthalpy conversion.")
            return float(flash_enthalpy_j_per_mol) * 1000.0 / molecular_weight
        props = self._properties_td(temperature_k, flash.D, self.z)
        return props["enthalpy"]

    def temperature_ph(self, fluid_name: str, pressure_pa: float, enthalpy_j_per_kg: float) -> float:
        pressure_kpa = pressure_pa / 1000.0
        molecular_weight = self.rp.WMOLdll(self.z)
        enthalpy_j_per_mol = enthalpy_j_per_kg * molecular_weight / 1000.0
        flash = self.rp.PHFLSHdll(pressure_kpa, enthalpy_j_per_mol, self.z)
        self._check(
            flash.ierr,
            flash.herr,
            f"calculating temperature for {fluid_name} at P={pressure_pa} Pa, H={enthalpy_j_per_kg} J/kg",
        )
        return flash.T

    def saturated_mixture_state_from_quality(
        self,
        fluid_name: str,
        pressure_pa: float,
        quality: float,
    ) -> SaturatedMixtureState:
        mass_quality = float(quality)
        if not math.isfinite(mass_quality) or not 0.0 <= mass_quality <= 1.0:
            raise ValueError("Mass quality must be a finite value between 0 and 1.")
        temperature_k, enthalpy, liquid_density, vapor_density = self._refprop_pq_outputs(
            pressure_pa,
            mass_quality,
            "T;H;DLIQ;DVAP",
        )
        return SaturatedMixtureState(
            temperature_k=temperature_k,
            pressure_pa=pressure_pa,
            mass_quality=mass_quality,
            enthalpy_j_per_kg=enthalpy,
            liquid_density_kg_per_m3=liquid_density,
            vapor_density_kg_per_m3=vapor_density,
        )

    def vapor_table(
        self,
        fluid_name: str,
        pressure_pa: float,
        temperature_start_k: float,
        temperature_end_k: float,
        temperature_step_k: float,
        quality_points: int | None = None,
        viscosity_model: str = "cicchitti",
    ) -> list[VaporRow]:
        try:
            bubble_temperature_k = self._refprop_pq(pressure_pa, 0.0, "T")
            dew_temperature_k = self._refprop_pq(pressure_pa, 1.0, "T")
        except RuntimeError:
            bubble_temperature_k = None
            dew_temperature_k = None
        if (
            bubble_temperature_k is not None
            and dew_temperature_k is not None
            and dew_temperature_k > bubble_temperature_k + TEMPERATURE_EPSILON
            and temperature_start_k <= dew_temperature_k + TEMPERATURE_EPSILON
            and temperature_end_k >= bubble_temperature_k - TEMPERATURE_EPSILON
        ):
            return self.equivalent_vapor_table(
                fluid_name=fluid_name,
                pressure_pa=pressure_pa,
                temperature_start_k=temperature_start_k,
                temperature_end_k=temperature_end_k,
                temperature_step_k=temperature_step_k,
                quality_points=quality_points,
                viscosity_model=viscosity_model,
            )
        rows: list[VaporRow] = []
        for temperature_k in _temperature_points(temperature_start_k, temperature_end_k, temperature_step_k):
            rows.append(self._vapor_row_tp(fluid_name, pressure_pa, temperature_k))
        return rows

    def equivalent_vapor_table(
        self,
        fluid_name: str,
        pressure_pa: float,
        temperature_start_k: float,
        temperature_end_k: float,
        temperature_step_k: float,
        quality_points: int | None,
        viscosity_model: str,
    ) -> list[VaporRow]:
        if quality_points is not None and quality_points < 2:
            raise ValueError("quality_points must be at least 2 or None for auto.")
        if viscosity_model not in {"mcadams", "cicchitti"}:
            raise ValueError("viscosity_model must be mcadams or cicchitti.")
        if temperature_step_k <= 0.0:
            raise ValueError("temperature_step_k must be positive.")
        self.last_equivalent_replacement_count = 0
        self.last_equivalent_quality_points = quality_points

        bubble_temperature_k = self._refprop_pq(pressure_pa, 0.0, "T")
        dew_temperature_k = self._refprop_pq(pressure_pa, 1.0, "T")
        if dew_temperature_k <= bubble_temperature_k + TEMPERATURE_EPSILON:
            raise ValueError(
                "equivalent_quality mode requires a finite two-phase temperature glide at the selected pressure."
            )

        target_temperatures_k = _temperature_points(temperature_start_k, temperature_end_k, temperature_step_k)
        rows: list[VaporRow | None] = []
        replacement_temperatures_k: list[float] = []
        unexpected_failure_temperatures_c: list[float] = []
        for temperature_k in target_temperatures_k:
            if bubble_temperature_k - TEMPERATURE_EPSILON <= temperature_k <= dew_temperature_k + TEMPERATURE_EPSILON:
                rows.append(None)
                replacement_temperatures_k.append(temperature_k)
                continue
            try:
                rows.append(self._vapor_row_tp(fluid_name, pressure_pa, temperature_k))
            except Exception:
                rows.append(None)
                unexpected_failure_temperatures_c.append(k_to_c(temperature_k))

        if unexpected_failure_temperatures_c:
            formatted = ", ".join(f"{value:.6g} C" for value in unexpected_failure_temperatures_c)
            raise RuntimeError(
                "REFPROP direct table generation failed outside the saturation glide range; "
                f"RefEquiv can only replace two-phase points. Failed temperatures: {formatted}"
            )
        if not replacement_temperatures_k:
            self.last_equivalent_replacement_count = 0
            self.last_equivalent_quality_points = quality_points
            return [row for row in rows if row is not None]

        h_sat_liq_bubble = self._refprop_pq(pressure_pa, 0.0, "H")
        thermal_conductivity_liq, dynamic_viscosity_liq = self._refprop_pq_outputs(pressure_pa, 0.0, "TCX;VIS")
        thermal_conductivity_vap, dynamic_viscosity_vap = self._refprop_pq_outputs(pressure_pa, 1.0, "TCX;VIS")
        cp_liq = self._refprop_pq(pressure_pa, 0.0, "CPLIQ")
        density_liq = self._refprop_pq(pressure_pa, 0.0, "DLIQ")
        density_vap = self._refprop_pq(pressure_pa, 1.0, "DVAP")

        effective_quality_points = quality_points or max(len(replacement_temperatures_k), 2)
        self.last_equivalent_replacement_count = len(replacement_temperatures_k)
        self.last_equivalent_quality_points = effective_quality_points
        replacement_samples: list[VaporRow] = []
        for quality in _linspace(0.0, 1.0, effective_quality_points):
            actual_temperature_k, enthalpy_j_per_kg, density_kg_per_m3, _entropy_j_per_kg_k = self._refprop_pq_outputs(
                pressure_pa,
                quality,
                "T;H;D;S",
            )
            vapor_volume_fraction = _vapor_volume_fraction(quality, density_liq, density_vap)
            equivalent_thermal_conductivity = _equivalent_thermal_conductivity(
                thermal_conductivity_liq,
                thermal_conductivity_vap,
                vapor_volume_fraction,
            )
            equivalent_dynamic_viscosity = _equivalent_viscosity(
                dynamic_viscosity_liq,
                dynamic_viscosity_vap,
                quality,
                vapor_volume_fraction,
                viscosity_model,
            )
            delta_temperature = actual_temperature_k - bubble_temperature_k
            if delta_temperature <= TEMPERATURE_EPSILON:
                equivalent_cp = cp_liq
            else:
                equivalent_cp = (enthalpy_j_per_kg - h_sat_liq_bubble) / delta_temperature

            replacement_samples.append(
                VaporRow(
                    temperature_c=k_to_c(actual_temperature_k),
                    density_kg_per_m3=density_kg_per_m3,
                    equivalent_specific_heat_j_per_kg_k=equivalent_cp,
                    equivalent_thermal_conductivity_w_per_m_k=equivalent_thermal_conductivity,
                    equivalent_dynamic_viscosity_pa_s=equivalent_dynamic_viscosity,
                    enthalpy_j_per_kg=enthalpy_j_per_kg,
                )
            )

        merged_rows: list[VaporRow] = []
        for temperature_k, row in zip(target_temperatures_k, rows):
            if row is not None:
                merged_rows.append(row)
            else:
                merged_rows.append(_interpolate_vapor_row(k_to_c(temperature_k), replacement_samples))
        return merged_rows

    def _quality_for_temperature(
        self,
        pressure_pa: float,
        target_temperature_k: float,
        bubble_temperature_k: float,
        dew_temperature_k: float,
    ) -> float:
        if target_temperature_k <= bubble_temperature_k + TEMPERATURE_EPSILON:
            return 0.0
        if target_temperature_k >= dew_temperature_k - TEMPERATURE_EPSILON:
            return 1.0

        low_quality = 0.0
        high_quality = 1.0
        for _ in range(80):
            mid_quality = (low_quality + high_quality) / 2.0
            mid_temperature_k = self._refprop_pq(pressure_pa, mid_quality, "T")
            if abs(mid_temperature_k - target_temperature_k) <= TEMPERATURE_EPSILON:
                return mid_quality
            if mid_temperature_k < target_temperature_k:
                low_quality = mid_quality
            else:
                high_quality = mid_quality
        return (low_quality + high_quality) / 2.0

    def liquid_table(
        self,
        fluid_name: str,
        pressure_pa: float,
        temperature_start_k: float,
        temperature_end_k: float,
        temperature_step_k: float,
    ) -> list[LiquidRow]:
        rows: list[LiquidRow] = []
        pressure_kpa = pressure_pa / 1000.0
        t = temperature_start_k
        while t <= temperature_end_k + 1.0e-9:
            flash = self.rp.TPFLSHdll(t, pressure_kpa, self.z)
            self._check(flash.ierr, flash.herr, f"calculating liquid state for {fluid_name} at {t} K")
            props = self._properties_td(t, flash.D, self.z)
            rows.append(
                LiquidRow(
                    temperature_c=k_to_c(t),
                    density_kg_per_m3=props["density"],
                    equivalent_specific_heat_j_per_kg_k=props["cp"],
                    equivalent_thermal_conductivity_w_per_m_k=props["thermal_conductivity"],
                    equivalent_dynamic_viscosity_pa_s=props["dynamic_viscosity"],
                    enthalpy_j_per_kg=props["enthalpy"],
                )
            )
            t += temperature_step_k
        return rows

    def _vapor_row_tp(self, fluid_name: str, pressure_pa: float, temperature_k: float) -> VaporRow:
        pressure_kpa = pressure_pa / 1000.0
        flash = self.rp.TPFLSHdll(temperature_k, pressure_kpa, self.z)
        self._check(flash.ierr, flash.herr, f"calculating vapor state for {fluid_name} at {temperature_k} K")
        props = self._properties_td(temperature_k, flash.D, self.z)
        return VaporRow(
            temperature_c=k_to_c(temperature_k),
            density_kg_per_m3=props["density"],
            equivalent_specific_heat_j_per_kg_k=props["cp"],
            equivalent_thermal_conductivity_w_per_m_k=props["thermal_conductivity"],
            equivalent_dynamic_viscosity_pa_s=props["dynamic_viscosity"],
            enthalpy_j_per_kg=props["enthalpy"],
        )

    def _properties_td(
        self,
        temperature_k: float,
        density_mol_l: float,
        composition: list[float],
    ) -> dict[str, float]:
        thermo = self.rp.THERMdll(temperature_k, density_mol_l, composition)
        transport = self.rp.TRNPRPdll(temperature_k, density_mol_l, composition)
        self._check(transport.ierr, transport.herr, "calculating transport properties")
        molecular_weight = self.rp.WMOLdll(composition)
        density_kg_m3 = density_mol_l * molecular_weight
        entropy_j_per_kg_k = thermo.s * 1000.0 / molecular_weight
        _validate_specific_entropy(entropy_j_per_kg_k, f"THERM state at T={temperature_k} K")
        return {
            "density": density_kg_m3,
            "cp": thermo.Cp * 1000.0 / molecular_weight,
            "enthalpy": thermo.h * 1000.0 / molecular_weight,
            "entropy": entropy_j_per_kg_k,
            "thermal_conductivity": transport.tcx,
            "dynamic_viscosity": transport.eta * 1.0e-6,
            "molecular_weight": molecular_weight,
        }

    def _refprop_pq(self, pressure_pa: float, quality: float, output: str) -> float:
        return self._refprop_pq_outputs(pressure_pa, quality, output)[0]

    def _refprop_pq_outputs(self, pressure_pa: float, quality: float, outputs: str) -> tuple[float, ...]:
        if not _has_usable_refpropdll(self.rp):
            return self._refprop_pq_outputs_legacy(pressure_pa, quality, outputs)

        unit_code, unit_system = self._get_pq_units()
        try:
            result = self.rp.REFPROPdll(
                self.loaded_fluid,
                "PQMASS",
                outputs,
                unit_code,
                0,
                0,
                _pq_pressure_input(pressure_pa, unit_system),
                quality,
                self.z,
            )
        except ValueError as exc:
            if _is_missing_refpropdll_error(exc):
                return self._refprop_pq_outputs_legacy(pressure_pa, quality, outputs)
            raise
        self._check(result.ierr, result.herr, f"calculating PQ state ({outputs}) at P={pressure_pa} Pa, Q={quality}")
        output_names = [output_name.strip().upper() for output_name in outputs.split(";")]
        values = tuple(
            _pq_output_value(output_name, float(result.Output[index]), unit_system)
            for index, output_name in enumerate(output_names)
        )
        return _validate_pq_output_values(pressure_pa, quality, outputs, output_names, values)

    def _refprop_pq_outputs_legacy(self, pressure_pa: float, quality: float, outputs: str) -> tuple[float, ...]:
        state = self.rp.PQFLSHdll(pressure_pa / 1000.0, quality, self.z, _REFPROP_PQ_MASS_QUALITY)
        self._check(state.ierr, state.herr, f"calculating legacy PQ state ({outputs}) at P={pressure_pa} Pa, Q={quality}")

        output_names = [output_name.strip().upper() for output_name in outputs.split(";")]
        transport_cache: dict[str, Any] = {}
        values = tuple(
            self._legacy_pq_output_value(state, pressure_pa, quality, output_name, transport_cache)
            for output_name in output_names
        )
        return _validate_pq_output_values(pressure_pa, quality, outputs, output_names, values)

    def _legacy_pq_output_value(
        self,
        state: Any,
        pressure_pa: float,
        quality: float,
        output_name: str,
        transport_cache: dict[str, Any],
    ) -> float:
        bulk_molecular_weight = float(self.rp.WMOLdll(self.z))
        liquid_composition = list(getattr(state, "x", self.z))
        vapor_composition = list(getattr(state, "y", self.z))
        liquid_molecular_weight = float(self.rp.WMOLdll(liquid_composition))
        vapor_molecular_weight = float(self.rp.WMOLdll(vapor_composition))

        if output_name == "T":
            return float(state.T)
        if output_name == "P":
            return pressure_pa
        if output_name == "D":
            return float(state.D) * bulk_molecular_weight
        if output_name == "DLIQ":
            return float(state.Dl) * liquid_molecular_weight
        if output_name == "DVAP":
            return float(state.Dv) * vapor_molecular_weight
        if output_name == "E":
            return float(state.e) * 1000.0 / bulk_molecular_weight
        if output_name == "H":
            return float(state.h) * 1000.0 / bulk_molecular_weight
        if output_name == "S":
            return float(state.s) * 1000.0 / bulk_molecular_weight
        if output_name == "CV":
            return float(state.Cv) * 1000.0 / bulk_molecular_weight
        if output_name == "CP":
            return float(state.Cp) * 1000.0 / bulk_molecular_weight
        if output_name == "CPLIQ":
            liquid_thermo = self.rp.THERMdll(float(state.T), float(state.Dl), liquid_composition)
            return float(liquid_thermo.Cp) * 1000.0 / liquid_molecular_weight
        if output_name == "CPVAP":
            vapor_thermo = self.rp.THERMdll(float(state.T), float(state.Dv), vapor_composition)
            return float(vapor_thermo.Cp) * 1000.0 / vapor_molecular_weight
        if output_name in {"TCX", "VIS"}:
            transport = transport_cache.get("transport")
            if transport is None:
                transport = self._legacy_pq_transport(state, quality, liquid_composition, vapor_composition)
                transport_cache["transport"] = transport
            if output_name == "TCX":
                return float(transport.tcx)
            return float(transport.eta) * 1.0e-6
        raise RuntimeError(f"Unsupported legacy REFPROP PQ output: {output_name}")

    def _legacy_pq_transport(
        self,
        state: Any,
        quality: float,
        liquid_composition: list[float],
        vapor_composition: list[float],
    ) -> Any:
        if quality <= EPSILON:
            density = float(state.Dl)
            composition = liquid_composition
        elif quality >= 1.0 - EPSILON:
            density = float(state.Dv)
            composition = vapor_composition
        else:
            raise RuntimeError("REFPROP transport properties are only available at saturated liquid or vapor PQ states.")

        transport = self.rp.TRNPRPdll(float(state.T), density, composition)
        self._check(transport.ierr, transport.herr, "calculating legacy PQ transport properties")
        return transport

    def _get_pq_units(self) -> tuple[int, str]:
        if not hasattr(self, "_pq_unit_code") or not hasattr(self, "_pq_unit_system"):
            self._pq_unit_code, self._pq_unit_system = _resolve_refprop_pq_units(self.rp)
        return self._pq_unit_code, self._pq_unit_system

    @staticmethod
    def _check(ierr: int, herr: str, action: str) -> None:
        if ierr in ALLOWED_REFPROP_WARNINGS:
            return
        if ierr != 0:
            raise RuntimeError(f"REFPROP error while {action}: {ierr} {herr}")


def _validate_pq_output_values(
    pressure_pa: float,
    quality: float,
    outputs: str,
    output_names: list[str],
    values: tuple[float, ...],
) -> tuple[float, ...]:
    if any(math.isnan(value) for value in values):
        raise RuntimeError(f"REFPROP returned NaN while calculating PQ state ({outputs})")
    for output_name, value in zip(output_names, values):
        if output_name == "S":
            _validate_specific_entropy(value, f"PQ state at P={pressure_pa} Pa, Q={quality}")
    return values


def _has_usable_refpropdll(rp: Any) -> bool:
    if not callable(getattr(rp, "REFPROPdll", None)):
        return False
    return getattr(rp, "_REFPROPdll", True) is not None


def _is_missing_refpropdll_error(exc: ValueError) -> bool:
    return _MISSING_REFPROPDLL_FRAGMENT in str(exc)


def _validate_specific_entropy(value: float, context: str) -> None:
    if not math.isfinite(value):
        raise RuntimeError(f"REFPROP returned non-finite entropy while calculating {context}: {value}")
    if abs(value) > MAX_ABS_SPECIFIC_ENTROPY_J_PER_KG_K:
        raise RuntimeError(
            f"REFPROP returned abnormal entropy while calculating {context}: "
            f"{value} J/kg-K"
        )


def _resolve_refprop_pq_units(rp: Any) -> tuple[int, str]:
    mass_base_si = _refprop_enum_value(rp, "MASS_BASE_SI", "MASS BASE SI")
    if mass_base_si is not None:
        return mass_base_si, _REFPROP_UNIT_MASS_BASE_SI

    mass_si = _refprop_enum_value(rp, "MASS_SI", "MASS SI")
    if mass_si is not None:
        return mass_si, _REFPROP_UNIT_MASS_SI

    return _LEGACY_REFPROP_MASS_SI, _REFPROP_UNIT_MASS_SI


def _refprop_enum_value(rp: Any, attr_name: str, enum_name: str) -> int | None:
    attr_value = getattr(rp, attr_name, None)
    if attr_value is not None:
        return int(attr_value)

    get_enum = getattr(rp, "GETENUMdll", None)
    if not callable(get_enum):
        return None
    try:
        enum_result = get_enum(0, enum_name)
    except Exception:
        return None
    if int(getattr(enum_result, "ierr", 0)) != 0:
        return None
    return int(enum_result.iEnum)


def _pq_pressure_input(pressure_pa: float, unit_system: str) -> float:
    if unit_system == _REFPROP_UNIT_MASS_BASE_SI:
        return pressure_pa
    if unit_system == _REFPROP_UNIT_MASS_SI:
        return pressure_pa / 1.0e6
    raise RuntimeError(f"Unsupported REFPROP unit system: {unit_system}")


def _pq_output_value(output_name: str, value: float, unit_system: str) -> float:
    if unit_system == _REFPROP_UNIT_MASS_BASE_SI:
        return value
    if unit_system != _REFPROP_UNIT_MASS_SI:
        raise RuntimeError(f"Unsupported REFPROP unit system: {unit_system}")

    if output_name in _MASS_SI_OUTPUT_SCALE:
        return value * _MASS_SI_OUTPUT_SCALE[output_name]
    if output_name in _MASS_SI_OUTPUT_UNCHANGED:
        return value
    raise RuntimeError(f"Unsupported REFPROP MASS SI output conversion: {output_name}")


def _as_fld_name(name: str) -> str:
    upper = name.strip().upper()
    if upper.endswith(".FLD"):
        return upper
    return upper + ".FLD"


def _equivalent_thermal_conductivity(
    thermal_conductivity_liq: float,
    thermal_conductivity_vap: float,
    vapor_volume_fraction: float,
) -> float:
    if vapor_volume_fraction <= EPSILON:
        return thermal_conductivity_liq
    if vapor_volume_fraction >= 1.0 - EPSILON:
        return thermal_conductivity_vap

    a = 1.0
    b = (
        2.0 * (1.0 - vapor_volume_fraction) * thermal_conductivity_vap
        - (1.0 - vapor_volume_fraction) * thermal_conductivity_liq
        + 2.0 * vapor_volume_fraction * thermal_conductivity_liq
        - vapor_volume_fraction * thermal_conductivity_vap
    )
    c = -2.0 * thermal_conductivity_liq * thermal_conductivity_vap
    discriminant = b * b - 4.0 * a * c
    root = math.sqrt(discriminant)
    candidate_1 = (-b + root) / (2.0 * a)
    candidate_2 = (-b - root) / (2.0 * a)
    lower = min(thermal_conductivity_liq, thermal_conductivity_vap) - EPSILON
    upper = max(thermal_conductivity_liq, thermal_conductivity_vap) + EPSILON
    if lower <= candidate_1 <= upper:
        return candidate_1
    return candidate_2


def _equivalent_viscosity(
    dynamic_viscosity_liq: float,
    dynamic_viscosity_vap: float,
    quality: float,
    vapor_volume_fraction: float,
    model: str,
) -> float:
    if quality <= EPSILON:
        return dynamic_viscosity_liq
    if quality >= 1.0 - EPSILON:
        return dynamic_viscosity_vap
    if model == "mcadams":
        return 1.0 / ((1.0 - quality) / dynamic_viscosity_liq + quality / dynamic_viscosity_vap)
    if model == "cicchitti":
        return (1.0 - vapor_volume_fraction) * dynamic_viscosity_liq + vapor_volume_fraction * dynamic_viscosity_vap
    raise ValueError(f"Unsupported viscosity model: {model}")


def _vapor_volume_fraction(quality: float, density_liq: float, density_vap: float) -> float:
    if quality <= EPSILON:
        return 0.0
    if quality >= 1.0 - EPSILON:
        return 1.0
    specific_volume_liq = 1.0 / density_liq
    specific_volume_vap = 1.0 / density_vap
    mixture_specific_volume = (1.0 - quality) * specific_volume_liq + quality * specific_volume_vap
    return quality * specific_volume_vap / mixture_specific_volume


def _linspace(start: float, end: float, count: int) -> list[float]:
    if count == 1:
        return [start]
    step = (end - start) / float(count - 1)
    return [start + step * index for index in range(count)]


def _temperature_points(start_k: float, end_k: float, step_k: float) -> list[float]:
    points = []
    temperature_k = start_k
    while temperature_k <= end_k + TEMPERATURE_EPSILON:
        points.append(temperature_k)
        temperature_k += step_k
    if not points or points[-1] < end_k - TEMPERATURE_EPSILON:
        points.append(end_k)
    return points


def _interpolate_vapor_row(temperature_c: float, rows: list[VaporRow]) -> VaporRow:
    if not rows:
        raise RuntimeError("No RefEquiv replacement rows were generated.")
    ordered = sorted(rows, key=lambda row: row.temperature_c)
    if temperature_c <= ordered[0].temperature_c + TEMPERATURE_EPSILON:
        return _vapor_row_at_temperature(temperature_c, ordered[0])
    if temperature_c >= ordered[-1].temperature_c - TEMPERATURE_EPSILON:
        return _vapor_row_at_temperature(temperature_c, ordered[-1])

    for lower, upper in zip(ordered, ordered[1:]):
        if lower.temperature_c <= temperature_c <= upper.temperature_c:
            span = upper.temperature_c - lower.temperature_c
            if abs(span) <= TEMPERATURE_EPSILON:
                return _vapor_row_at_temperature(temperature_c, lower)
            ratio = (temperature_c - lower.temperature_c) / span
            return VaporRow(
                temperature_c=temperature_c,
                density_kg_per_m3=_lerp(lower.density_kg_per_m3, upper.density_kg_per_m3, ratio),
                equivalent_specific_heat_j_per_kg_k=_lerp(
                    lower.equivalent_specific_heat_j_per_kg_k,
                    upper.equivalent_specific_heat_j_per_kg_k,
                    ratio,
                ),
                equivalent_thermal_conductivity_w_per_m_k=_lerp(
                    lower.equivalent_thermal_conductivity_w_per_m_k,
                    upper.equivalent_thermal_conductivity_w_per_m_k,
                    ratio,
                ),
                equivalent_dynamic_viscosity_pa_s=_lerp(
                    lower.equivalent_dynamic_viscosity_pa_s,
                    upper.equivalent_dynamic_viscosity_pa_s,
                    ratio,
                ),
                enthalpy_j_per_kg=_lerp(lower.enthalpy_j_per_kg, upper.enthalpy_j_per_kg, ratio),
            )
    raise RuntimeError(f"Could not interpolate RefEquiv replacement row at {temperature_c:.6g} C.")


def _vapor_row_at_temperature(temperature_c: float, row: VaporRow) -> VaporRow:
    return VaporRow(
        temperature_c=temperature_c,
        density_kg_per_m3=row.density_kg_per_m3,
        equivalent_specific_heat_j_per_kg_k=row.equivalent_specific_heat_j_per_kg_k,
        equivalent_thermal_conductivity_w_per_m_k=row.equivalent_thermal_conductivity_w_per_m_k,
        equivalent_dynamic_viscosity_pa_s=row.equivalent_dynamic_viscosity_pa_s,
        enthalpy_j_per_kg=row.enthalpy_j_per_kg,
    )


def _lerp(start: float, end: float, ratio: float) -> float:
    return start + (end - start) * ratio
