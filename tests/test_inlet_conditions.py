from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from refprop_to_ccm.inlet_conditions import (
    RefrigerantInletCondition,
    calculate_refrigerant_inlet,
    load_coolant_calculation_from_xlsx,
)
from refprop_to_ccm.models import CoolantCalculation, CoolantRow, LiquidRow, VaporRow
from refprop_to_ccm.tables import write_coolant_xlsx


class InletConditionsTests(unittest.TestCase):
    def test_loads_coolant_calculation_from_generated_workbook(self) -> None:
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
            heat_transfer_w=37122.0,
            plate_count=32,
        )
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "coolant.xlsx"
            write_coolant_xlsx(workbook, row, calculation)

            loaded = load_coolant_calculation_from_xlsx(workbook)

        self.assertAlmostEqual(loaded.single_plate_mass_flow_kg_s, 0.013835546875)
        self.assertAlmostEqual(loaded.inlet_temperature_c, 42.0)
        self.assertAlmostEqual(loaded.heat_transfer_w, 37122.0)

    def test_calculates_refrigerant_inlet_heat_transfer_for_condenser_direction(self) -> None:
        inlet = calculate_refrigerant_inlet(
            solve_mode="heat_transfer",
            heat_transfer_w=13885.0,
            layer_count=18,
            inlet_temperature_c=98.0,
            outlet_temperature_c=80.0,
            inlet_enthalpy_j_per_kg=430000.0,
            outlet_enthalpy_j_per_kg=250000.0,
            saturated_liquid_enthalpy_j_per_kg=240000.0,
            saturated_vapor_enthalpy_j_per_kg=410000.0,
            saturated_liquid_density_kg_per_m3=980.0,
            saturated_vapor_density_kg_per_m3=90.0,
        )

        self.assertAlmostEqual(inlet.total_mass_flow_kg_s, 13885.0 / 180000.0)
        self.assertAlmostEqual(inlet.single_layer_mass_flow_kg_s, 13885.0 / 180000.0 / 18.0)
        self.assertAlmostEqual(inlet.quality, (430000.0 - 240000.0) / (410000.0 - 240000.0))
        self.assertAlmostEqual(inlet.vapor_volume_fraction, 1.0)
        self.assertAlmostEqual(inlet.liquid_volume_fraction, 0.0)
        self.assertEqual(inlet.starccm_volume_fraction, "[1,0]")
        self.assertEqual(inlet.solve_mode, "heat_transfer")
        self.assertAlmostEqual(inlet.heat_transfer_w, 13885.0)
        self.assertAlmostEqual(inlet.outlet_temperature_c, 80.0)

    def test_calculates_refrigerant_inlet_mass_flow_for_evaporator_direction(self) -> None:
        inlet = calculate_refrigerant_inlet(
            solve_mode="mass_flow",
            total_mass_flow_kg_s=0.2,
            layer_count=20,
            inlet_temperature_c=5.0,
            outlet_temperature_c=15.0,
            inlet_enthalpy_j_per_kg=250000.0,
            outlet_enthalpy_j_per_kg=430000.0,
            saturated_liquid_enthalpy_j_per_kg=240000.0,
            saturated_vapor_enthalpy_j_per_kg=410000.0,
            saturated_liquid_density_kg_per_m3=980.0,
            saturated_vapor_density_kg_per_m3=90.0,
        )

        self.assertAlmostEqual(inlet.total_mass_flow_kg_s, 0.2)
        self.assertAlmostEqual(inlet.single_layer_mass_flow_kg_s, 0.01)
        self.assertAlmostEqual(inlet.heat_transfer_w, 0.2 * 180000.0)
        self.assertAlmostEqual(inlet.quality, (250000.0 - 240000.0) / (410000.0 - 240000.0))
        self.assertGreater(inlet.vapor_volume_fraction, 0.0)
        self.assertLess(inlet.vapor_volume_fraction, 1.0)
        self.assertEqual(inlet.solve_mode, "mass_flow")

    def test_writes_refrigerant_a25_f32_section(self) -> None:
        row = CoolantRow(
            temperature_c=57.0,
            density_kg_per_m3=1062.57,
            specific_heat_j_per_kg_k=3423.6,
            thermal_conductivity_w_per_m_k=0.3858,
            dynamic_viscosity_kg_per_m_s=0.00153,
        )
        refrigerant = RefrigerantInletCondition(
            total_mass_flow_kg_s=0.0771388888889,
            single_layer_mass_flow_kg_s=0.00428549382716,
            inlet_temperature_c=98.0,
            quality=0.83,
            vapor_volume_fraction=0.975,
            liquid_volume_fraction=0.025,
            starccm_volume_fraction="[0.975,0.025]",
            solve_mode="heat_transfer",
            heat_transfer_w=13885.0,
            outlet_temperature_c=57.0,
            inlet_enthalpy_j_per_kg=430000.0,
            outlet_enthalpy_j_per_kg=250000.0,
        )
        saturated_liquid_row = LiquidRow(
            temperature_c=57.0,
            density_kg_per_m3=980.0,
            equivalent_specific_heat_j_per_kg_k=1500.0,
            equivalent_thermal_conductivity_w_per_m_k=0.08,
            equivalent_dynamic_viscosity_pa_s=0.0002,
            enthalpy_j_per_kg=240000.0,
        )
        saturated_vapor_row = VaporRow(
            temperature_c=57.0,
            density_kg_per_m3=90.0,
            equivalent_specific_heat_j_per_kg_k=1800.0,
            equivalent_thermal_conductivity_w_per_m_k=0.03,
            equivalent_dynamic_viscosity_pa_s=0.00001,
            enthalpy_j_per_kg=410000.0,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "coolant.xlsx"
            write_coolant_xlsx(
                workbook,
                row,
                refrigerant=refrigerant,
                saturated_liquid_row=saturated_liquid_row,
                saturated_vapor_row=saturated_vapor_row,
            )
            root = _load_sheet_root(workbook)

        self.assertEqual(_read_inline_string(root, "A25"), "制冷剂物性参数")
        self.assertEqual(_read_inline_string(root, "A27"), "饱和液相")
        self.assertEqual(_read_inline_string(root, "A28"), "饱和气相")
        self.assertAlmostEqual(_read_number(root, "D31"), 0.975)
        self.assertEqual(_read_inline_string(root, "F31"), "[0.975,0.025]")
        self.assertAlmostEqual(_read_number(root, "D32"), 0.0771388888889)
        self.assertAlmostEqual(_read_number(root, "F32"), 0.00428549382716)


def _load_sheet_root(path: Path) -> ElementTree.Element:
    with ZipFile(path) as workbook:
        return ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))


def _read_number(root: ElementTree.Element, cell_ref: str) -> float:
    cell = root.find(f'.//{{http://schemas.openxmlformats.org/spreadsheetml/2006/main}}c[@r="{cell_ref}"]')
    if cell is None:
        raise AssertionError(f"Missing cell {cell_ref}")
    value_node = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
    if value_node is None or value_node.text is None:
        raise AssertionError(f"Missing numeric value in {cell_ref}")
    return float(value_node.text)


def _read_inline_string(root: ElementTree.Element, cell_ref: str) -> str:
    cell = root.find(f'.//{{http://schemas.openxmlformats.org/spreadsheetml/2006/main}}c[@r="{cell_ref}"]')
    if cell is None:
        raise AssertionError(f"Missing cell {cell_ref}")
    text_node = cell.find(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
    if text_node is None or text_node.text is None:
        raise AssertionError(f"Missing string value in {cell_ref}")
    return text_node.text


if __name__ == "__main__":
    unittest.main()
