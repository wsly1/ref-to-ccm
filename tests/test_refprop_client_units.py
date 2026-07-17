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


class _LegacyPqRefprop:
    _REFPROPdll = None

    def __init__(self) -> None:
        self.pq_calls: list[dict[str, object]] = []
        self.transport_calls: list[dict[str, object]] = []

    def REFPROPdll(self, *args):
        raise ValueError("The function REFPROPdll could not be loaded from the shared library.")

    def PQFLSHdll(self, pressure_kpa, quality, z, kq):
        self.pq_calls.append({"pressure_kpa": pressure_kpa, "quality": quality, "z": z, "kq": kq})
        return SimpleNamespace(
            ierr=0,
            herr="",
            T=300.0,
            D=2.0,
            Dl=10.0,
            Dv=0.5,
            x=[0.25, 0.75],
            y=[0.6, 0.4],
            e=90.0,
            h=120.0,
            s=1.5,
            Cv=0.25,
            Cp=0.3,
        )

    def THERMdll(self, temperature_k, density_mol_l, composition):
        if density_mol_l == 10.0:
            return SimpleNamespace(Cp=220.0)
        if density_mol_l == 0.5:
            return SimpleNamespace(Cp=110.0)
        raise AssertionError(f"unexpected density: {density_mol_l}")

    def TRNPRPdll(self, temperature_k, density_mol_l, composition):
        self.transport_calls.append(
            {
                "temperature_k": temperature_k,
                "density_mol_l": density_mol_l,
                "composition": composition,
            }
        )
        return SimpleNamespace(ierr=0, herr="", eta=15.0, tcx=0.08)

    def WMOLdll(self, composition):
        if composition == [1.0]:
            return 100.0
        if composition == [0.25, 0.75]:
            return 80.0
        if composition == [0.6, 0.4]:
            return 40.0
        raise AssertionError(f"unexpected composition: {composition}")


class _TpFlashRefprop:
    def __init__(self) -> None:
        self.therm_called = False

    def TPFLSHdll(self, temperature_k, pressure_kpa, z):
        assert temperature_k == 320.0
        assert pressure_kpa == 800.0
        assert z == [1.0]
        return SimpleNamespace(ierr=0, herr="", D=2.0, h=120.0)

    def WMOLdll(self, composition):
        assert composition == [1.0]
        return 100.0

    def THERMdll(self, temperature_k, density_mol_l, composition):
        self.therm_called = True
        return SimpleNamespace(h=999.0, Cp=200.0)

    def TRNPRPdll(self, temperature_k, density_mol_l, composition):
        return SimpleNamespace(ierr=0, herr="", eta=15.0, tcx=0.08)


class _TpFlashWithoutEnthalpyRefprop:
    def TPFLSHdll(self, temperature_k, pressure_kpa, z):
        return SimpleNamespace(ierr=0, herr="", D=2.0)


class _TwoPhaseTpFlashRefprop(_TpFlashRefprop):
    def TPFLSHdll(self, temperature_k, pressure_kpa, z):
        flash = super().TPFLSHdll(temperature_k, pressure_kpa, z)
        flash.q = 0.4
        return flash


def test_refprop_pq_outputs_uses_mass_base_si_when_available() -> None:
    rp = _MassBaseSiRefprop()
    client = _client_for(rp)

    values = client._refprop_pq_outputs(800000.0, 0.5, "T;H;VIS")

    assert values == pytest.approx((300.0, 120000.0, 2.5e-5))
    assert rp.calls[0]["inputs"] == "PQMASS"
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


def test_refprop_pq_outputs_falls_back_to_legacy_pqflsh_when_refpropdll_is_missing() -> None:
    rp = _LegacyPqRefprop()
    client = _client_for(rp)

    values = client._refprop_pq_outputs(800000.0, 0.0, "T;P;H;S;D;DLIQ;DVAP;CPLIQ;CPVAP;TCX;VIS")

    assert values == pytest.approx(
        (
            300.0,
            800000.0,
            1200.0,
            15.0,
            200.0,
            800.0,
            20.0,
            2750.0,
            2750.0,
            0.08,
            15.0e-6,
        )
    )
    assert rp.pq_calls == [{"pressure_kpa": 800.0, "quality": 0.0, "z": [1.0], "kq": 2}]
    assert rp.transport_calls == [{"temperature_k": 300.0, "density_mol_l": 10.0, "composition": [0.25, 0.75]}]


def test_enthalpy_tp_uses_flash_enthalpy_instead_of_recalculating_td_state() -> None:
    rp = _TpFlashRefprop()
    client = _client_for(rp)

    enthalpy = client.enthalpy_tp("R454C", 800_000.0, 320.0)

    assert enthalpy == pytest.approx(1_200.0)
    assert rp.therm_called is False


def test_enthalpy_tp_falls_back_when_legacy_flash_has_no_enthalpy_field() -> None:
    client = _client_for(_TpFlashWithoutEnthalpyRefprop())
    client._properties_td = lambda temperature_k, density_mol_l, composition: {
        "enthalpy": 4_321.0
    }

    enthalpy = client.enthalpy_tp("R454C", 800_000.0, 320.0)

    assert enthalpy == pytest.approx(4_321.0)


def test_enthalpy_tp_single_phase_rejects_two_phase_flash_quality() -> None:
    client = _client_for(_TwoPhaseTpFlashRefprop())

    with pytest.raises(ValueError, match="饱和/两相状态"):
        client.enthalpy_tp_single_phase("R454C", 800_000.0, 320.0)
