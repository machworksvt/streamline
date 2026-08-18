"""The schema catches what it must, and the canonical writer is what makes hashes mean something."""

import copy
import json
import math

import numpy as np
import pytest

from aerodb_contract import canonical_json as cj, schema, synthetic


@pytest.fixture(scope="module")
def adb_doc():
    return synthetic.synthetic_aerodb()


def test_the_synthetic_artifacts_validate(adb_doc):
    assert schema.validate(adb_doc, "aerodb") == []
    assert schema.validate(synthetic.synthetic_massprops(), "massprops") == []
    assert schema.validate(synthetic.synthetic_engine_deck(), "engine_deck") == []


def test_canonical_json_is_byte_stable_and_key_order_independent(adb_doc):
    a = cj.dumps(adb_doc)
    shuffled = json.loads(json.dumps(adb_doc, sort_keys=False))
    b = cj.dumps(dict(reversed(list(shuffled.items()))))
    assert a == b
    assert a.endswith("\n") and "\n" not in a[:-1]
    assert cj.sha256_text(a) == cj.sha256_of(adb_doc)


def test_canonical_json_converts_numpy_and_refuses_nan():
    assert cj.dumps({"x": np.float32(0.5), "v": np.arange(3), "b": np.bool_(True)}) == '{"b":true,"v":[0,1,2],"x":0.5}\n'
    with pytest.raises(ValueError):
        cj.dumps({"x": float("nan")})
    with pytest.raises(ValueError):
        cj.dumps({"x": math.inf})


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.pop("reference"), "reference.S_m2: missing"),
    (lambda d: d["axes"]["alpha_rad"].reverse(), "not strictly increasing"),
    (lambda d: d["tables"]["base"]["CX"].pop(), "expected shape"),
    (lambda d: d["tables"]["control"].__setitem__("flap_left", d["tables"]["control"]["stabilator"]), "flaps enter via the axis"),
    (lambda d: d.__setitem__("conventions", {**d["conventions"], "body_frame": "FLU"}), "conventions: must equal the pinned value"),
    (lambda d: d.__setitem__("bogus", 1), "unknown top-level key"),
    (lambda d: d.__setitem__("id", "icarus-A.zzz"), "does not match"),
    (lambda d: d["provenance"]["backend"].__setitem__("unpinned", "no"), "expected bool"),
    (lambda d: d["lint"]["results"].append({"check": "x", "status": "maybe"}), "not in ['pass', 'warn', 'fail', 'waived']"),
])
def test_the_validator_names_the_violation(adb_doc, mutate, needle):
    d = copy.deepcopy(adb_doc)
    mutate(d)
    errs = schema.validate(d, "aerodb")
    assert any(needle in e for e in errs), errs


def test_a_nan_in_a_table_is_a_schema_error_not_a_token(adb_doc):
    d = copy.deepcopy(adb_doc)
    d["tables"]["base"]["Cm"][0][0][0][0] = float("nan")
    assert any("NaN" in e for e in schema.validate(d, "aerodb"))


def test_massprops_inertia_must_be_symmetric_positive_definite():
    d = synthetic.synthetic_massprops()
    d["inertia_kg_m2"][0][1] = 5.0
    assert any("not symmetric" in e for e in schema.validate(d, "massprops"))
    d = synthetic.synthetic_massprops()
    d["inertia_kg_m2"] = [[1, 0, 0], [0, -1, 0], [0, 0, 1]]
    assert any("positive definite" in e for e in schema.validate(d, "massprops"))


def test_check_raises_with_every_violation_listed(adb_doc):
    d = copy.deepcopy(adb_doc)
    d.pop("reference"); d.pop("validity")
    with pytest.raises(schema.ContractError) as ei:
        schema.check(d, "aerodb")
    msg = str(ei.value)
    assert "reference.S_m2: missing" in msg and "validity.notes: missing" in msg
