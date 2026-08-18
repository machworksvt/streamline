"""Generic promotion (symbol grafting) utilities for thin namespace modules.

This is used to ensure the full OpenVSP (and other similar) APIs are exposed
at the top-level import after editable / namespace installs that otherwise
present only a partial wrapper.
"""
from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from typing import Iterable, Sequence

_SENTINEL_ATTR = "__streamline_promoted__"


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def promote_full_api(
    module_name: str,
    candidates: Sequence[str] | None = None,
    *,
    include_private: bool = False,
    version_aliases: Iterable[tuple[str, str]] | None = None,
) -> ModuleType:
    """Promote (graft) attributes from compiled candidate submodules.

    Parameters:
        module_name: Base module (already importable) whose namespace should receive symbols.
        candidates: Ordered list of candidate submodule names to probe for compiled / full API.
        include_private: If True, also graft dunder/underscore names (default False).
        version_aliases: Optional iterable of (existing_name, alias_name) pairs to add if alias missing.

    Returns:
        The (possibly modified) imported module object.
    """
    try:
        base = importlib.import_module(module_name)
    except Exception:  # pragma: no cover - defensive, caller should ensure import
        return None  # type: ignore

    # Avoid repeating work
    if getattr(base, _SENTINEL_ATTR, False):
        return base

    cand_list = list(candidates or [])
    # Heuristic: if user did not supply candidates and a dotted compiled layer convention exists
    if not cand_list:
        # Try common pattern: <module>._<lastpart> or <module>._core
        tail = module_name.rsplit('.', 1)[-1]
        cand_list = [f"{module_name}._{tail}", f"{module_name}._core"]

    for cand in cand_list:
        try:
            spec = importlib.util.find_spec(cand)
            if not spec or not spec.origin:
                continue
            # Prefer compiled extensions (.pyd / .so / .dll)
            if not any(spec.origin.lower().endswith(ext) for ext in (".pyd", ".so", ".dll")):
                continue
            full_mod = importlib.import_module(cand)
            grafted = 0
            for name in dir(full_mod):
                if not include_private and not _is_public(name):
                    continue
                if hasattr(base, name):
                    continue
                try:
                    setattr(base, name, getattr(full_mod, name))
                    grafted += 1
                except Exception:  # pragma: no cover - skip unassignable attributes
                    pass
            if grafted and not hasattr(base, _SENTINEL_ATTR):
                try:
                    setattr(base, _SENTINEL_ATTR, True)
                except Exception:
                    pass
            # Apply version alias pairs
            if version_aliases:
                for src, alias in version_aliases:
                    if hasattr(base, src) and not hasattr(base, alias):
                        try:
                            setattr(base, alias, getattr(base, src))
                        except Exception:
                            pass
            # Stop after first successful candidate
            if grafted:
                break
        except Exception:  # pragma: no cover
            continue

    return base


__all__ = ["promote_full_api"]
