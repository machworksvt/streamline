import pytest
from .utils import assert_has_minimal_api

pytestmark = pytest.mark.vsp

def test_openvsp_real_runtime_available(openvsp_runtime):
    assert_has_minimal_api(openvsp_runtime)