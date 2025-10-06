# streamline/vsp/contracts/base.py
from __future__ import annotations

import hashlib
import json
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field

from ...core.schema import RunManifest


class Ticket(BaseModel):
    """Base marker for analysis input tickets."""
    config_id: Optional[str] = None
    mode_id: Optional[str] = None
    use_mode_flag: Optional[bool] = None
    set_name: Optional[str] = None
    set_index: Optional[int] = None

    # global pre-run knobs
    control_group_deflections_deg: Dict[int, float] = Field(default_factory=dict)
    udp_overrides: Dict[str, float] = Field(default_factory=dict)  # ParmID -> value
    runtime_overrides: Dict[str, float] = Field(default_factory=dict)

    def sha256(self, extra: Optional[Dict[str, Any]] = None) -> str:
        payload = {
            "ticket": json.loads(self.model_dump_json(exclude_none=True, exclude_defaults=False))
        }
        if extra:
            payload["context"] = extra
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


class Receipt(BaseModel):
    """Base marker for analysis output receipts."""
    run_manifest: RunManifest
    ticket_sha256: str
    artifact_dir: Optional[str] = None
    artifacts: Dict[str, str] = Field(default_factory=dict)

