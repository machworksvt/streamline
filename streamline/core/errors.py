from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional


@dataclass
class ErrorPayload:
    message: str
    code: str
    context: Dict[str, Any]
    hint: Optional[str] = None


class StreamlineError(RuntimeError):
    """Base exception carrying structured diagnostic information."""

    code = "streamline.error"

    def __init__(
        self,
        message: str,
        *,
        context: Optional[Mapping[str, Any]] = None,
        hint: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context = dict(context or {})
        self.hint = hint

    def payload(self) -> ErrorPayload:
        return ErrorPayload(message=self.message, code=self.code, context=dict(self.context), hint=self.hint)

    def with_context(self, **extra: Any) -> "StreamlineError":
        updated = dict(self.context)
        updated.update({k: v for k, v in extra.items() if v is not None})
        self.context = updated
        return self


class CatalogError(StreamlineError):
    code = "streamline.catalog"


class ConfigCatalogError(CatalogError):
    code = "streamline.catalog.config"


class OperatingPointCatalogError(CatalogError):
    code = "streamline.catalog.operating_point"


class AnalysisError(StreamlineError):
    code = "streamline.analysis"


class VSPSessionError(StreamlineError):
    code = "streamline.vsp.session"
