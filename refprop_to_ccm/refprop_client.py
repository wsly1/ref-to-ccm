from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from .models import LiquidProperties, LiquidRow, SaturationState, VaporRow
from .units import k_to_c

ALLOWED_REFPROP_WARNINGS = {-319, -320, -113}
EPSILON = 1.0e-10
TEMPERATURE_EPSILON = 1.0e-6


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
            liquid_standard_state_entropy_j_per_kg_k=props["entropy"],
            vapor_standard_state_entropy_j_per_kg_k=vapor_props["entropy"],
        )

    def enthalpy_tp(self, fluid_name: str, pressure_pa: float, temperature_k: float) -> float:
        pressure_kpa = pressure_pa / 1000.0
        flash = self.rp.TPFLSHdll(temperature_k, pressure_kpa, self.z)
        self._check(flash.ierr, flash.herr, f"calculating enthalpy for {fluid_name} at T={temperature_k} K, P={pressure_pa} Pa")
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
            actual_temperature_k, enthalpy_j_per_kg, density_kg_per_m3 = self._refprop_pq_outputs(
                pressure_pa,
                quality,
                "T;H;D",
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
        return {
            "density": density_kg_m3,
            "cp": thermo.Cp * 1000.0 / molecular_weight,
            "enthalpy": thermo.h * 1000.0 / molecular_weight,
            "entropy": thermo.s * 1000.0 / molecular_weight,
            "thermal_conductivity": transport.tcx,
            "dynamic_viscosity": transport.eta * 1.0e-6,
            "molecular_weight": molecular_weight,
        }

    def _refprop_pq(self, pressure_pa: float, quality: float, output: str) -> float:
        return self._refprop_pq_outputs(pressure_pa, quality, output)[0]

    def _refprop_pq_outputs(self, pressure_pa: float, quality: float, outputs: str) -> tuple[float, ...]:
        result = self.rp.REFPROPdll(
            self.loaded_fluid,
            "PQ",
            outputs,
            self.rp.MASS_BASE_SI,
            0,
            0,
            pressure_pa,
            quality,
            self.z,
        )
        self._check(result.ierr, result.herr, f"calculating PQ state ({outputs}) at P={pressure_pa} Pa, Q={quality}")
        values = tuple(float(result.Output[index]) for index in range(len(outputs.split(";"))))
        if any(math.isnan(value) for value in values):
            raise RuntimeError(f"REFPROP returned NaN while calculating PQ state ({outputs})")
        return values

    @staticmethod
    def _check(ierr: int, herr: str, action: str) -> None:
        if ierr in ALLOWED_REFPROP_WARNINGS:
            return
        if ierr != 0:
            raise RuntimeError(f"REFPROP error while {action}: {ierr} {herr}")


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
