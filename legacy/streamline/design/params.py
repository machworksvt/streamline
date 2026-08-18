from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

@dataclass
class EditBatch:
    config_id: str
    udp_changes: Dict[str, float] = field(default_factory=dict)
    control_deflections_deg: Dict[str, float] = field(default_factory=dict)
    hinges: Dict[str, float] = field(default_factory=dict)
    payloads_toggle: Dict[str, bool] = field(default_factory=dict)
    notes: str = ""

    def add_udp(self, name: str, value: float): self.udp_changes[name] = value
    def add_deflection(self, group: str, deg: float): self.control_deflections_deg[group] = deg
    def add_hinge(self, device: str, position: float): self.hinges[device] = position
    def set_payload(self, geom: str, enabled: bool): self.payloads_toggle[geom] = enabled

    def as_dict(self) -> dict:
        return {
            "config_id": self.config_id,
            "udp": self.udp_changes,
            "controls_deg": self.control_deflections_deg,
            "hinges": self.hinges,
            "payloads": self.payloads_toggle,
            "notes": self.notes
        }
