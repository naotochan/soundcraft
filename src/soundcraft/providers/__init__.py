"""Music generation backends.

Bundled providers are imported lazily by the registry on first lookup, which
keeps :mod:`soundcraft.settings` (which needs the base classes) free of a
circular import.
"""

from soundcraft.providers import registry
from soundcraft.providers.base import (
    Availability,
    GeneratedAudio,
    GenerationRequest,
    Option,
    ParamSpec,
    Provider,
    ProviderError,
    ProviderUnavailable,
    SettingSpec,
)

__all__ = [
    "Availability",
    "GeneratedAudio",
    "GenerationRequest",
    "Option",
    "ParamSpec",
    "Provider",
    "ProviderError",
    "ProviderUnavailable",
    "SettingSpec",
    "registry",
]
