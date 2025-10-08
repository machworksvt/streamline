"""VSP integration public API.

Use import_vsp() to obtain a validated OpenVSP module object with required
symbols grafted if necessary.
"""
from .session import import_vsp  # canonical

__all__ = ["import_vsp"]
