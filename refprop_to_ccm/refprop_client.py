from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import LiquidProperties, LiquidRow, SaturationState, VaporRow
from .units import k_to_c


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
            liquid_standard_state_enthalpy_j_per_kg=props["enthalpy"],
            vapor_standard_state_enthalpy_j_per_kg=vapor_props["enthalpy"],
            heat_of_formation_input_j_per_kg=props["enthalpy"],
            vapor_heat_of_formation_input_j_per_kg=vapor_props["enthalpy"],
            density_temperature_derivative_kg_per_m3_k=0.0,
        )

    def vapor_table(
        self,
        fluid_name: str,
        pressure_pa: float,
        temperature_start_k: float,
        temperature_end_k: float,
        temperature_step_k: float,
    ) -> list[VaporRow]:
        rows: list[VaporRow] = []
        pressure_kpa = pressure_pa / 1000.0
        t = temperature_start_k
        while t <= temperature_end_k + 1.0e-9:
            flash = self.rp.TPFLSHdll(t, pressure_kpa, self.z)
            self._check(flash.ierr, flash.herr, f"calculating vapor state for {fluid_name} at {t} K")
            props = self._properties_td(t, flash.D, self.z)
            rows.append(
                VaporRow(
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
            "thermal_conductivity": transport.tcx,
            "dynamic_viscosity": transport.eta * 1.0e-6,
            "molecular_weight": molecular_weight,
        }

    @staticmethod
    def _check(ierr: int, herr: str, action: str) -> None:
        if ierr != 0:
            raise RuntimeError(f"REFPROP error while {action}: {ierr} {herr}")


def _as_fld_name(name: str) -> str:
    upper = name.strip().upper()
    if upper.endswith(".FLD"):
        return upper
    return upper + ".FLD"
