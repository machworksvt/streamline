"""The no-implicit-defaults register: it refuses an incomplete or over-complete input set, and
coerces types. Needs the real API to enumerate inputs, so it is vsp-marked but not a solve."""

import pytest

from streamline.vsp import settings as sm


@pytest.mark.vsp
def test_describe_reports_openvsp_defaults(session):
    specs = sm.describe(session, "VSPAEROSweep")
    assert "Vinf" in specs and specs["Vinf"].kind == "double"
    assert "NCPU" in specs and specs["NCPU"].kind == "int"
    assert "WingID" in specs and specs["WingID"].kind == "string"
    # OpenVSP's imperial-flavoured defaults are exactly what the register exists to override.
    assert specs["Rho"].default[0] == pytest.approx(0.002377, rel=1e-3)


@pytest.mark.vsp
def test_a_missing_input_is_refused_by_name(session):
    specs = sm.describe(session, "VSPAEROSweep")
    supplied = {n: list(s.default) for n, s in specs.items()}
    supplied.pop("Vinf")
    with pytest.raises(sm.SettingsError, match="missing.*Vinf"):
        sm.resolve(session, "VSPAEROSweep", supplied)


@pytest.mark.vsp
def test_an_unknown_input_is_refused_by_name(session):
    specs = sm.describe(session, "VSPAEROSweep")
    supplied = {n: list(s.default) for n, s in specs.items()}
    supplied["NewFlagFromSomeFutureVersion"] = [1]
    with pytest.raises(sm.SettingsError, match="unknown.*NewFlagFromSomeFutureVersion"):
        sm.resolve(session, "VSPAEROSweep", supplied)


@pytest.mark.vsp
def test_a_complete_set_resolves_and_coerces_types(session):
    specs = sm.describe(session, "VSPAEROSweep")
    supplied = {n: list(s.default) for n, s in specs.items()}
    supplied["Vinf"] = 30          # scalar, int → double
    supplied["NCPU"] = 2.0         # float that is integral → int
    r = sm.resolve(session, "VSPAEROSweep", supplied)
    assert r.values["Vinf"] == [30.0]
    assert r.values["NCPU"] == [2]
    assert set(r.values) == set(specs), "every input is recorded for provenance"


@pytest.mark.vsp
def test_a_non_integral_value_for_an_int_input_is_refused(session):
    specs = sm.describe(session, "VSPAEROSweep")
    supplied = {n: list(s.default) for n, s in specs.items()}
    supplied["NCPU"] = 2.5
    with pytest.raises(sm.SettingsError, match="NCPU: expected integer"):
        sm.resolve(session, "VSPAEROSweep", supplied)
