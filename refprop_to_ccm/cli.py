from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .core import generate_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refprop-to-ccm",
        description="Generate REFPROP material data and a STAR-CCM+ import macro.",
    )
    parser.add_argument("--config", required=True, help="Path to YAML config.")
    parser.add_argument(
        "--no-run-star",
        action="store_true",
        help="Only generate REFPROP outputs and STAR-CCM+ macro.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(Path(args.config))
    result = generate_outputs(config, run_star=not args.no_run_star)
    print(result.to_display_text())
    print(f"Generated macro: {result.macro_file}")
    return 0
