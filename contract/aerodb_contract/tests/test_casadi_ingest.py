"""The ingest proof (plan §2.6): every table of an AeroDB becomes a CasADi bspline interpolant that
matches the contract's evaluator, and codegens to C that includes only <math.h> and compiles under
`-std=c99 -Wall -Wextra`.

This settles, before the icarus-dynamics follow-on starts, the one thing that repo's export path
cannot tolerate: an interpolant flavour that drags the CasADi runtime into the generated plant.
casadi is a test-only dependency of THIS repo's flake; the contract package itself never imports it.
"""

import shutil
import subprocess

import numpy as np
import pytest

ca = pytest.importorskip("casadi")

from aerodb_contract import load, synthetic  # noqa: E402


def _bspline(adb: load.AeroDB, table: np.ndarray, name: str):
    """grid = [alpha, beta, V, flap] so that alpha varies fastest — which is exactly the C-order
    ravel of a (n_flap, n_V, n_beta, n_alpha) table.

    The consumer's rule, pinned here: cubic along an axis with >= 4 breakpoints, LINEAR along a
    shorter one (CasADi 3.7 implements not-a-knot knots for degree 3 only; degree 2 is "Not
    implemented" and 3 points cannot carry a cubic), and singleton axes squeezed out. On the v0
    grid that is cubic in α and β, linear in V and flap — V effects are flat for a VLM and flap
    detents are discrete settings, so the kinks land where they cost nothing."""
    axes = [adb.alpha, adb.beta, adb.airspeed, adb.flap]
    keep = [i for i, a in enumerate(axes) if a.size > 1]
    grid = [axes[i].tolist() for i in keep]
    degree = [3 if len(g) >= 4 else 1 for g in grid]
    values = table.ravel(order="C").tolist()  # (flap, V, beta, alpha) row-major == alpha fastest
    f = ca.interpolant(name, "bspline", grid, values, {"degree": degree})
    return f, keep


def _point(keep, alpha, beta, V, flap):
    full = [alpha, beta, V, flap]
    return ca.DM([full[i] for i in keep])


@pytest.fixture(scope="module")
def adb():
    return load.AeroDB.from_doc(synthetic.synthetic_aerodb())


def test_every_table_becomes_an_interpolating_bspline_that_agrees_with_the_reference_evaluator(adb):
    tables = {f"base_{c}": adb.base[c] for c in adb.base}
    tables.update({f"rate_{r}_{c}": t for r, cs in adb.rate.items() for c, t in cs.items()})
    tables.update({f"ctl_{s}_{c}": t for s, cs in adb.control.items() for c, t in cs.items()})
    assert len(tables) == 6 + 18 + 30

    fi, vi, bi, ai = 1, 1, 3, 4
    for name, table in tables.items():
        f, keep = _bspline(adb, table, name)
        # exact at a grid point
        p = _point(keep, adb.alpha[ai], adb.beta[bi], adb.airspeed[vi], adb.flap[fi])
        assert float(f(p)) == pytest.approx(float(table[fi, vi, bi, ai]), abs=1e-9), name
        # close to the multilinear reference between grid points (spline vs linear differ by the
        # curvature of the data; the synthetic is near-linear so this is tight)
        a = 0.5 * (adb.alpha[ai] + adb.alpha[ai + 1]); b = 0.5 * (adb.beta[bi] + adb.beta[bi + 1])
        V = 0.5 * (adb.airspeed[0] + adb.airspeed[1]); fl = 0.5 * (adb.flap[0] + adb.flap[1])
        ref = load.multilinear(adb.axes, table, (fl, V, b, a))
        assert float(f(_point(keep, a, b, V, fl))) == pytest.approx(ref, abs=2e-3), name


def test_the_bspline_codegens_to_plain_c_with_only_math_h(adb, tmp_path):
    f, keep = _bspline(adb, adb.base["Cm"], "adb_Cm")
    x = ca.MX.sym("x", len(keep))
    fn = ca.Function("adb_cm", [x], [f(x)])
    gen = ca.CodeGenerator("adb_cm.c", {"with_header": False, "casadi_int": "long long int"})
    gen.add(fn)
    gen.generate(str(tmp_path) + "/")
    src = (tmp_path / "adb_cm.c").read_text()
    includes = [ln.strip() for ln in src.splitlines() if ln.strip().startswith("#include")]
    assert includes == ["#include <math.h>"], includes
    gcc = shutil.which("gcc")
    assert gcc, "gcc must be in the dev shell for this proof"
    r = subprocess.run([gcc, "-std=c99", "-Wall", "-Wextra", "-c", str(tmp_path / "adb_cm.c"),
                        "-o", str(tmp_path / "adb_cm.o")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_bspline_is_twice_differentiable_where_the_consumer_needs_it(adb):
    """trim (Newton) and linearize (Jacobians) in icarus-dynamics need C1 at least; a cubic
    bspline is C2 inside the grid. Evaluate ∂Cm/∂α analytically and by finite difference."""
    f, keep = _bspline(adb, adb.base["Cm"], "adb_Cm")
    x = ca.MX.sym("x", len(keep))
    J = ca.Function("J", [x], [ca.jacobian(f(x), x)])
    p = _point(keep, np.radians(3.0), np.radians(2.0), 30.0, np.radians(5.0))
    j = np.asarray(J(p)).ravel()
    h = 1e-6
    p2 = ca.DM(p); p2[0] += h
    fd = (float(f(p2)) - float(f(p))) / h
    assert j[0] == pytest.approx(fd, rel=1e-4)
    # and it is the model's Cm_α to within spline error on near-linear data
    assert j[0] == pytest.approx(synthetic.DERIVS["Cm_a"], rel=2e-2)
