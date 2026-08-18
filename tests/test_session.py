"""The session: the pin, the one-shot graphics choice, and the results-accumulation rule."""

import pytest

from streamline.vsp import session as sm


@pytest.mark.vsp
def test_the_running_openvsp_is_the_pinned_one(session):
    """The whole point of the flake. If this fails in CI the environment is not what
    nix/openvsp.nix says it is, and nothing produced by the run is releasable."""
    assert session.version == sm.PINNED_OPENVSP
    assert session.pinned
    assert session.graphics is False


@pytest.mark.vsp
def test_the_session_is_a_process_singleton(session):
    assert sm.require_openvsp() is session


@pytest.mark.vsp
def test_switching_to_graphics_after_a_headless_import_is_refused(session):
    """openvsp_config is read once at import; a second import with the other flag would silently
    hand back the first module. Refusing is the honest behaviour."""
    with pytest.raises(sm.GraphicsModeFixed):
        sm.require_openvsp(graphics=True)


def test_version_parsing_takes_the_triplet_out_of_the_banner():
    assert sm._parse_version("OpenVSP 3.51.2") == "3.51.2"
    with pytest.raises(sm.OpenVSPMissing):
        sm._parse_version("no numbers here")


@pytest.mark.vsp
def test_latest_raises_when_the_result_set_does_not_exist(session):
    """`FindResultsID(name, 0)` on a missing set returns an empty id and every read after it is a
    guess; the wrapper turns that into an error at the point of the mistake."""
    session.fresh_results()
    with pytest.raises(LookupError):
        session.latest("VSPAERO_Stab")
