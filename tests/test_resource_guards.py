from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from refprop_to_ccm import core, starccm
from refprop_to_ccm.config import ToolConfig
from refprop_to_ccm.starccm import StarCcmRunner


class TemperatureTableSizeLimitTests(unittest.TestCase):
    def test_rejects_excessive_gas_table_before_loading_refprop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(
                output_directory=Path(tmp),
                gas_temperature_start=0.0,
                gas_temperature_end=120.0,
                gas_temperature_step=0.000001,
            )

            with patch.object(core, "RefpropClient") as refprop_client:
                with self.assertRaisesRegex(ValueError, "气态温度表.*行数上限"):
                    core.generate_outputs(config)

        refprop_client.assert_not_called()

    def test_rejects_excessive_liquid_temperature_table(self) -> None:
        config = _config(
            liquid_property_mode="table",
            liquid_temperature_start=0.0,
            liquid_temperature_end=120.0,
            liquid_temperature_step=0.000001,
        )

        with self.assertRaisesRegex(ValueError, "液态温度表.*行数上限"):
            core.validate_temperature_table_sizes(config)


class StarCcmRunnerTimeoutTests(unittest.TestCase):
    def test_passes_a_bounded_timeout_to_starccm_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_directory = Path(tmp)
            executable = output_directory / "starccm.exe"
            sim_file = output_directory / "input.sim"
            macro_file = output_directory / "macro.java"
            executable.touch()
            sim_file.touch()
            macro_file.touch()
            config = _config(
                output_directory=output_directory,
                starccm_exe=executable,
                sim_file=sim_file,
            )

            with patch.object(starccm.subprocess, "run") as run:
                run.return_value.returncode = 0
                StarCcmRunner(config).run(macro_file)

        self.assertEqual(starccm.STARCCM_RUN_TIMEOUT_SECONDS, 5 * 60)
        self.assertEqual(run.call_args.kwargs["timeout"], starccm.STARCCM_RUN_TIMEOUT_SECONDS)

    def test_reports_when_starccm_exceeds_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_directory = Path(tmp)
            executable = output_directory / "starccm.exe"
            sim_file = output_directory / "input.sim"
            macro_file = output_directory / "macro.java"
            executable.touch()
            sim_file.touch()
            macro_file.touch()
            config = _config(
                output_directory=output_directory,
                starccm_exe=executable,
                sim_file=sim_file,
            )

            with patch.object(
                starccm.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd=["starccm"], timeout=1),
            ):
                with self.assertRaisesRegex(TimeoutError, "STAR-CCM\\+.*超时"):
                    StarCcmRunner(config).run(macro_file)


def _config(**overrides) -> ToolConfig:
    values = {
        "fluid_name": "R134a",
        "fluid_components": None,
        "saturation_type": "pressure",
        "saturation_value": 1.0,
        "saturation_unit": "MPa",
        "gas_pressure_value": None,
        "gas_pressure_unit": "MPa",
        "gas_temperature_start": 80.0,
        "gas_temperature_end": 90.0,
        "gas_temperature_step": 1.0,
        "gas_temperature_unit": "C",
        "liquid_property_mode": "saturation",
        "liquid_temperature_start": 0.0,
        "liquid_temperature_end": 0.0,
        "liquid_temperature_step": 1.0,
        "liquid_temperature_unit": "C",
        "sim_file": Path("input.sim"),
        "output_sim_file": Path("output.sim"),
        "continuum_name": "Physics 1",
        "liquid_phase_name": "liquid",
        "vapor_phase_name": "gas",
        "vapor_specific_heat_source": "cp_table",
        "starccm_exe": None,
        "output_directory": Path("out"),
    }
    values.update(overrides)
    return ToolConfig(**values)


if __name__ == "__main__":
    unittest.main()
