from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from refprop_to_ccm.inlet_conditions import CoolantInletCondition, RefrigerantInletCondition
from refprop_to_ccm.models import CoolantCalculation, CoolantRow, LiquidRow, VaporRow
from refprop_to_ccm import star_apply
from refprop_to_ccm.star_apply import StarApplyConfig, apply_star_from_outputs, render_inlet_conditions_macro
from refprop_to_ccm.tables import write_coolant_xlsx


class StarApplyInletConditionsTests(unittest.TestCase):
    def test_renders_inlet_condition_macro_with_custom_regions_and_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = StarApplyConfig(
                source_type="coolant",
                sim_file=Path("input.sim"),
                output_sim_file=Path("output.sim"),
                continuum_name="Physics 1",
                liquid_phase_name="liquid",
                vapor_phase_name="gas",
                starccm_exe=None,
                output_directory=Path(tmp),
                coolant_region_name="water region",
                coolant_boundary_name="water inlet",
                refrigerant_region_name="ref region",
                refrigerant_boundary_name="ref inlet",
            )
            coolant = CoolantInletCondition(
                single_plate_mass_flow_kg_s=0.0138,
                inlet_temperature_c=42.0,
                heat_transfer_w=36832.8,
            )
            refrigerant = RefrigerantInletCondition(
                total_mass_flow_kg_s=0.0771,
                single_layer_mass_flow_kg_s=0.00428,
                inlet_temperature_c=98.0,
                quality=0.83,
                vapor_volume_fraction=0.975,
                liquid_volume_fraction=0.025,
                starccm_volume_fraction="[0.975,0.025]",
            )

            macro = render_inlet_conditions_macro(config, coolant, refrigerant)

        self.assertIn('REGION_NAME = "water region"', macro)
        self.assertIn('BOUNDARY_NAME = "water inlet"', macro)
        self.assertIn('REGION_NAME = "ref region"', macro)
        self.assertIn('BOUNDARY_NAME = "ref inlet"', macro)
        self.assertIn("0.0138", macro)
        self.assertIn("42", macro)
        self.assertIn("0.00428", macro)
        self.assertIn("98", macro)
        self.assertIn("[0.975,0.025]", macro)

    def test_generates_inlet_conditions_macro_from_direct_refrigerant_inputs(self) -> None:
        row = CoolantRow(
            temperature_c=57.0,
            density_kg_per_m3=1062.57,
            specific_heat_j_per_kg_k=3423.6,
            thermal_conductivity_w_per_m_k=0.3858,
            dynamic_viscosity_kg_per_m_s=0.00153,
        )
        calculation = CoolantCalculation(
            row=row,
            solve_mode="heat",
            volume_flow_l_min=25.0,
            mass_flow_kg_s=0.4427375,
            single_plate_mass_flow_kg_s=0.013835546875,
            inlet_temperature_c=42.0,
            outlet_temperature_c=66.5,
            heat_transfer_w=13885.0,
            plate_count=32,
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            coolant_xlsx = output_dir / "coolant.xlsx"
            write_coolant_xlsx(coolant_xlsx, row, calculation)
            config = StarApplyConfig(
                source_type="inlet_conditions",
                sim_file=Path("input.sim"),
                output_sim_file=Path("output.sim"),
                continuum_name="Physics 1",
                liquid_phase_name="liquid",
                vapor_phase_name="gas",
                starccm_exe=None,
                output_directory=output_dir,
                coolant_xlsx=coolant_xlsx,
                coolant_region_name="water region",
                coolant_boundary_name="water inlet",
                refrigerant_region_name="ref region",
                refrigerant_boundary_name="ref inlet",
                refrigerant_single_layer_mass_flow_kg_s=0.00428,
                refrigerant_inlet_temperature_c=98.0,
                refrigerant_vapor_volume_fraction=0.975,
            )

            result = apply_star_from_outputs(config, run_star=False)
            macro = result.macro_file.read_text(encoding="utf-8")

        self.assertEqual(result.macro_file.name, "apply_inlet_conditions_to_star.java")
        self.assertIn("0.013835546875", macro)
        self.assertIn("0.00428", macro)
        self.assertIn("[0.975,0.025]", macro)

    def test_generates_separate_coolant_inlet_macro(self) -> None:
        row = CoolantRow(
            temperature_c=57.0,
            density_kg_per_m3=1062.57,
            specific_heat_j_per_kg_k=3423.6,
            thermal_conductivity_w_per_m_k=0.3858,
            dynamic_viscosity_kg_per_m_s=0.00153,
        )
        calculation = CoolantCalculation(
            row=row,
            solve_mode="heat",
            volume_flow_l_min=25.0,
            mass_flow_kg_s=0.4427375,
            single_plate_mass_flow_kg_s=0.013835546875,
            inlet_temperature_c=42.0,
            outlet_temperature_c=66.5,
            heat_transfer_w=13885.0,
            plate_count=32,
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            coolant_xlsx = output_dir / "coolant.xlsx"
            write_coolant_xlsx(coolant_xlsx, row, calculation)
            config = StarApplyConfig(
                source_type="coolant_inlet_condition",
                sim_file=Path("input.sim"),
                output_sim_file=Path("output.sim"),
                continuum_name="unused",
                liquid_phase_name="liquid",
                vapor_phase_name="gas",
                starccm_exe=None,
                output_directory=output_dir,
                coolant_xlsx=coolant_xlsx,
                coolant_region_name="water region",
                coolant_boundary_name="water inlet",
            )

            result = apply_star_from_outputs(config, run_star=False)
            macro = result.macro_file.read_text(encoding="utf-8")

        self.assertEqual(result.macro_file.name, "apply_coolant_inlet_to_star.java")
        self.assertIn("water region", macro)
        self.assertIn("0.013835546875", macro)
        self.assertNotIn("RefrigerantTarget", macro)

    def test_generates_separate_refrigerant_inlet_macro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = StarApplyConfig(
                source_type="refrigerant_inlet_condition",
                sim_file=Path("input.sim"),
                output_sim_file=Path("output.sim"),
                continuum_name="unused",
                liquid_phase_name="liquid",
                vapor_phase_name="gas",
                starccm_exe=None,
                output_directory=Path(tmp),
                refrigerant_region_name="ref region",
                refrigerant_boundary_name="ref inlet",
                refrigerant_single_layer_mass_flow_kg_s=0.00428,
                refrigerant_inlet_temperature_c=98.0,
                refrigerant_vapor_volume_fraction=0.975,
            )

            result = apply_star_from_outputs(config, run_star=False)
            macro = result.macro_file.read_text(encoding="utf-8")

        self.assertEqual(result.macro_file.name, "apply_refrigerant_inlet_to_star.java")
        self.assertIn("ref region", macro)
        self.assertIn("0.00428", macro)
        self.assertIn("[0.975,0.025]", macro)
        self.assertNotIn("CoolantTarget", macro)

    def test_generates_refrigerant_inlet_macro_from_combined_workbook(self) -> None:
        row = CoolantRow(
            temperature_c=57.0,
            density_kg_per_m3=1062.57,
            specific_heat_j_per_kg_k=3423.6,
            thermal_conductivity_w_per_m_k=0.3858,
            dynamic_viscosity_kg_per_m_s=0.00153,
        )
        refrigerant = RefrigerantInletCondition(
            total_mass_flow_kg_s=0.0771,
            single_layer_mass_flow_kg_s=0.00428,
            inlet_temperature_c=98.0,
            quality=0.83,
            vapor_volume_fraction=0.975,
            liquid_volume_fraction=0.025,
            starccm_volume_fraction="[0.975,0.025]",
            heat_transfer_w=13885.0,
            outlet_temperature_c=57.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            coolant_xlsx = output_dir / "combined.xlsx"
            write_coolant_xlsx(
                coolant_xlsx,
                row,
                refrigerant=refrigerant,
                saturated_liquid_row=LiquidRow(40.0, 980.0, 1500.0, 0.08, 0.0002, 240000.0),
                saturated_vapor_row=VaporRow(40.0, 90.0, 1200.0, 0.02, 0.00001, 410000.0),
            )
            config = StarApplyConfig(
                source_type="refrigerant_inlet_condition",
                sim_file=Path("input.sim"),
                output_sim_file=Path("output.sim"),
                continuum_name="unused",
                liquid_phase_name="liquid",
                vapor_phase_name="gas",
                starccm_exe=None,
                output_directory=output_dir,
                coolant_xlsx=coolant_xlsx,
                refrigerant_region_name="ref region",
                refrigerant_boundary_name="ref inlet",
            )

            result = apply_star_from_outputs(config, run_star=False)
            macro = result.macro_file.read_text(encoding="utf-8")

        self.assertEqual(result.macro_file.name, "apply_refrigerant_inlet_to_star.java")
        self.assertIn("0.00428", macro)
        self.assertIn("98", macro)
        self.assertIn("[0.975,0.025]", macro)

    def test_star_apply_runner_uses_shared_five_minute_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_directory = Path(tmp)
            executable = output_directory / "starccm.exe"
            sim_file = output_directory / "input.sim"
            macro_file = output_directory / "macro.java"
            executable.touch()
            sim_file.touch()
            macro_file.touch()

            with patch.object(star_apply.subprocess, "run") as run:
                run.return_value.returncode = 0
                star_apply.run_starccm_macro(executable, sim_file, macro_file, output_directory)

        self.assertEqual(run.call_args.kwargs["timeout"], 5 * 60)

    def test_star_apply_runner_reports_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_directory = Path(tmp)
            executable = output_directory / "starccm.exe"
            sim_file = output_directory / "input.sim"
            macro_file = output_directory / "macro.java"
            executable.touch()
            sim_file.touch()
            macro_file.touch()

            with patch.object(
                star_apply.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd=["starccm"], timeout=5 * 60),
            ):
                with self.assertRaisesRegex(TimeoutError, "STAR-CCM\\+.*超时"):
                    star_apply.run_starccm_macro(executable, sim_file, macro_file, output_directory)


if __name__ == "__main__":
    unittest.main()
