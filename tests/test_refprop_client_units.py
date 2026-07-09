from __future__ import annotations

from types import SimpleNamespace

import pytest

from refprop_to_ccm.refprop_client import RefpropClient, _resolve_refprop_pq_units


def _client_for(rp: object) -> RefpropClient:
    client = object.__new__(RefpropClient)
    client.rp = rp
    client.loaded_fluid = "R454C.MIX"
    client.z = [1.0]
    return client


class _MassBaseSiRefprop:
    MASS_BASE_SI = 21

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def REFPROPdll(self, fluid, inputs, outputs, units, i_mass, i_flag, prop1, prop2, z):
        self.calls.append(
            {
                "fluid": fluid,
                "inputs": inputs,
                "outputs": outputs,
                "units": units,
                "i_mass": i_mass,
                "i_flag": i_flag,
                "prop1": prop1,
                "prop2": prop2,
                "z": z,
            }
        )
        return SimpleNamespace(ierr=0, herr="", Output=[300.0, 120000.0, 2.5e-5])


class _MassSiRefprop:
    MASS_SI = 2

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def REFPROPdll(self, fluid, inputs, outputs, units, i_mass, i_flag, prop1, prop2, z):
        self.calls.append(
            {
                "fluid": fluid,
                "inputs": inputs,
                "outputs": outputs,
                "units": units,
                "i_mass": i_mass,
                "i_flag": i_flag,
                "prop1": prop1,
                "prop2": prop2,
                "z": z,
            }
        )
        return SimpleNamespace(
            ierr=0,
            herr="",
            Output=[0.8, 120.0, 1.5, 200.0, 25.0, 12.0, 30.0, 280.0],
        )


class _GetEnumRefprop:
    def GETENUMdll(self, _flag: int, enum_name: str):
        if enum_name == "MASS BASE SI":
            return SimpleNamespace(iEnum=21, ierr=0, herr="")
        raise AssertionError(f"unexpected enum lookup: {enum_name}")


def test_refprop_pq_outputs_uses_mass_base_si_when_available() -> None:
    rp = _MassBaseSiRefprop()
    client = _client_for(rp)

    values = client._refprop_pq_outputs(800000.0, 0.5, "T;H;VIS")

    assert values == pytest.approx((300.0, 120000.0, 2.5e-5))
    assert rp.calls[0]["units"] == 21
    assert rp.calls[0]["prop1"] == 800000.0
    assert rp.calls[0]["prop2"] == 0.5


def test_refprop_pq_outputs_falls_back_to_mass_si_and_converts_units() -> None:
    rp = _MassSiRefprop()
    client = _client_for(rp)

    values = client._refprop_pq_outputs(800000.0, 0.5, "P;H;S;TCX;VIS;D;DLIQ;CPLIQ")

    assert values == pytest.approx((800000.0, 120000.0, 1500.0, 0.2, 25.0e-6, 12.0, 30.0, 280000.0))
    assert rp.calls[0]["units"] == 2
    assert rp.calls[0]["prop1"] == 0.8
    assert rp.calls[0]["prop2"] == 0.5


def test_refprop_unit_resolution_can_use_getenum_when_instance_attr_is_missing() -> None:
    assert _resolve_refprop_pq_units(_GetEnumRefprop()) == (21, "mass_base_si")
