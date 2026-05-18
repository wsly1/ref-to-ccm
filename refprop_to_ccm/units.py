from __future__ import annotations


def pressure_to_pa(value: float, unit: str) -> float:
    key = unit.strip().lower()
    factors = {
        "pa": 1.0,
        "kpa": 1.0e3,
        "mpa": 1.0e6,
        "bar": 1.0e5,
    }
    if key not in factors:
        raise ValueError(f"Unsupported pressure unit: {unit}")
    return value * factors[key]


def temperature_to_k(value: float, unit: str) -> float:
    key = unit.strip().lower()
    if key in {"c", "degc", "celsius"}:
        return value + 273.15
    if key in {"k", "kelvin"}:
        return value
    raise ValueError(f"Unsupported temperature unit: {unit}")


def k_to_c(value: float) -> float:
    return value - 273.15
