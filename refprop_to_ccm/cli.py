from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .core import generate_outputs
from .egasp_client import build_coolant_calculation, build_coolant_row
from .tables import write_coolant_xlsx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refprop-to-ccm",
        description="Generate REFPROP material data and a STAR-CCM+ import macro.",
    )
    parser.add_argument("--config", help="Path to YAML config.")
    parser.add_argument(
        "--no-run-star",
        action="store_true",
        help="Only generate REFPROP outputs and STAR-CCM+ macro.",
    )
    parser.add_argument(
        "--coolant-xlsx",
        action="store_true",
        help="Generate an EGASP coolant property workbook instead of REFPROP outputs.",
    )
    parser.add_argument("--coolant-temperature", type=float, default=57.0, help="Coolant temperature in C.")
    parser.add_argument(
        "--coolant-query-type",
        default="volume",
        help="EGASP concentration query type. Default: volume.",
    )
    parser.add_argument(
        "--coolant-query-value",
        type=float,
        default=0.5,
        help="EGASP concentration query value. Default: 0.5.",
    )
    parser.add_argument(
        "--coolant-solve",
        choices=("heat", "outlet-temperature", "volume-flow"),
        default="heat",
        help="Coolant calculation mode. Default: heat.",
    )
    parser.add_argument(
        "--coolant-volume-flow-l-min",
        type=float,
        default=25.0,
        help="Coolant volume flow in L/min. Default: 25.",
    )
    parser.add_argument(
        "--coolant-inlet-temperature",
        type=float,
        default=42.0,
        help="Coolant inlet temperature in C. Default: 42.",
    )
    parser.add_argument(
        "--coolant-outlet-temperature",
        type=float,
        default=66.5,
        help="Coolant outlet temperature in C. Default: 66.5.",
    )
    parser.add_argument(
        "--coolant-heat-transfer-w",
        type=float,
        help="Coolant heat transfer in W. Required for solve=outlet-temperature or volume-flow.",
    )
    parser.add_argument(
        "--coolant-outlet-direction",
        choices=("heating", "cooling"),
        default="heating",
        help="Direction used when solving the outlet temperature. Default: heating.",
    )
    parser.add_argument(
        "--coolant-plate-count",
        type=int,
        default=32,
        help="Plate count used to calculate single-plate mass flow. Default: 32.",
    )
    parser.add_argument(
        "--coolant-output",
        default="out/coolant_properties.xlsx",
        help="Output workbook path for coolant properties.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.coolant_xlsx:
        output_path = Path(args.coolant_output)
        coolant_row = build_coolant_row(
            temperature_c=args.coolant_temperature,
            query_type=args.coolant_query_type,
            query_value=args.coolant_query_value,
        )
        coolant_calculation = build_coolant_calculation(
            coolant_row,
            solve_mode=args.coolant_solve,
            volume_flow_l_min=args.coolant_volume_flow_l_min,
            inlet_temperature_c=args.coolant_inlet_temperature,
            outlet_temperature_c=args.coolant_outlet_temperature,
            heat_transfer_w=args.coolant_heat_transfer_w,
            outlet_direction=args.coolant_outlet_direction,
            plate_count=args.coolant_plate_count,
        )
        write_coolant_xlsx(output_path, coolant_row, coolant_calculation)
        print(f"Generated coolant workbook: {output_path.resolve()}")
        return 0

    if not args.config:
        raise SystemExit("--config is required unless --coolant-xlsx is used.")

    config = load_config(Path(args.config))
    result = generate_outputs(config, run_star=not args.no_run_star)
    print(result.to_display_text())
    print(f"Generated macro: {result.macro_file}")
    return 0
