"""VSP integration public API.

`import_vsp()` mirrors the manual workflow: it prepares the environment and
returns the imported `openvsp` module.
"""
from .session import import_vsp

__all__ = ["import_vsp"]
