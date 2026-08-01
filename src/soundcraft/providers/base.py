"""Provider contract shared by every generation backend.

A provider describes itself well enough that the CLI, the HTTP API and the GUI
can all be built from metadata alone — adding a backend must not require
touching argument parsers, request validators or HTML.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

ParamType = Literal["text", "number", "select", "bool"]


class ProviderError(RuntimeError):
    """Generation failed for a reason worth showing the user verbatim."""


class ProviderUnavailable(ProviderError):
    """Provider cannot run yet (missing credential, missing dependency, …)."""


@dataclass(frozen=True)
class Option:
    value: str
    label: str

    def as_dict(self) -> dict[str, str]:
        return {"value": self.value, "label": self.label}


@dataclass(frozen=True)
class ParamSpec:
    """A per-request knob. Rendered as a form control, validated server-side."""

    name: str
    label: str
    type: ParamType = "text"
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: tuple[Option, ...] = ()
    unit: str = ""
    help: str = ""
    optional: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "options": [o.as_dict() for o in self.options],
            "unit": self.unit,
            "help": self.help,
            "optional": self.optional,
        }

    def coerce(self, value: Any) -> Any:
        """Validate and normalise one incoming value. Raises ValueError."""
        if value is None or value == "":
            if self.optional:
                return None
            return self.default

        if self.type == "number":
            try:
                number = float(value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"{self.label}: expected a number, got {value!r}") from e
            if self.minimum is not None and number < self.minimum:
                raise ValueError(f"{self.label}: must be >= {self.minimum}")
            if self.maximum is not None and number > self.maximum:
                raise ValueError(f"{self.label}: must be <= {self.maximum}")
            is_int = all(
                v is None or float(v).is_integer()
                for v in (self.default, self.step, self.minimum, self.maximum)
            )
            return int(number) if is_int and number.is_integer() else number

        if self.type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")

        if self.type == "select":
            allowed = [o.value for o in self.options]
            if allowed and str(value) not in allowed:
                raise ValueError(f"{self.label}: choose one of {allowed}")
            return str(value)

        return str(value)


@dataclass(frozen=True)
class SettingSpec:
    """A persisted configuration value (API key, endpoint, model id, …)."""

    key: str
    label: str
    default: str = ""
    secret: bool = False
    help: str = ""
    url: str = ""
    placeholder: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "default": self.default,
            "secret": self.secret,
            "help": self.help,
            "url": self.url,
            "placeholder": self.placeholder,
        }


@dataclass(frozen=True)
class Availability:
    ready: bool
    reason: str = ""
    fix: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "reason": self.reason, "fix": self.fix}


READY = Availability(True)


@dataclass
class GenerationRequest:
    prompt: str
    params: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, fallback: Any = None) -> Any:
        value = self.params.get(name, fallback)
        return fallback if value is None else value


@dataclass
class GeneratedAudio:
    """Raw audio handed back to the pipeline, which owns naming and writing."""

    data: bytes
    suffix: str = ".wav"
    extra: dict[str, Any] = field(default_factory=dict)


class Provider(ABC):
    """Base class for a music generation backend."""

    id: str = ""
    label: str = ""
    summary: str = ""
    tags: tuple[str, ...] = ()
    docs_url: str = ""
    #: Roughly how long a request takes, for UI copy only.
    speed: str = ""

    #: Per-request knobs.
    params: tuple[ParamSpec, ...] = ()
    #: Persisted configuration this provider reads.
    settings: tuple[SettingSpec, ...] = ()

    def availability(self) -> Availability:  # pragma: no cover - trivial default
        return READY

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GeneratedAudio:
        """Produce one audio clip. Raise ProviderError on failure."""

    # -- helpers ---------------------------------------------------------

    def param(self, name: str) -> ParamSpec | None:
        for spec in self.params:
            if spec.name == name:
                return spec
        return None

    def defaults(self) -> dict[str, Any]:
        return {p.name: p.default for p in self.params}

    def coerce_params(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        """Validate incoming params against this provider's specs."""
        raw = raw or {}
        unknown = set(raw) - {p.name for p in self.params}
        if unknown:
            raise ValueError(
                f"{self.label}: unknown parameter(s): {', '.join(sorted(unknown))}"
            )
        return {spec.name: spec.coerce(raw.get(spec.name)) for spec in self.params}

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "tags": list(self.tags),
            "docs_url": self.docs_url,
            "speed": self.speed,
            "params": [p.as_dict() for p in self.params],
            "settings": [s.as_dict() for s in self.settings],
            "status": self.availability().as_dict(),
        }
