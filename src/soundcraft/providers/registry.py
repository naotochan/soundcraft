"""Provider registry — the single place that knows which backends exist."""

from __future__ import annotations

import threading

from soundcraft.providers.base import Provider, ProviderError

#: Presentation order for the bundled backends, most recommended first. Ids that
#: are not listed here (third-party registrations) follow in registration order.
BUILTIN_ORDER = ("comfyui", "local", "replicate", "huggingface", "lyria")

_providers: dict[str, Provider] = {}
_order: list[str] = []
#: Registration index per id, so display order never has to read `_order`
#: itself — `list.sort` empties the list while the key function runs.
_registered_at: dict[str, int] = {}
_loaded = False
# Reentrant: load_builtin() runs under this lock and calls register().
_lock = threading.RLock()


def _ensure_loaded() -> None:
    """Import bundled providers on first use.

    Deferred rather than done at package import so that provider modules are
    free to import :mod:`soundcraft.settings`, which itself depends on the
    provider base classes.
    """
    global _loaded
    with _lock:
        if _loaded:
            return
        try:
            load_builtin()
        finally:
            # Set last: a caller racing on a half-built registry would get
            # "unknown backend" for providers that are merely still importing.
            _loaded = True


def register(provider: Provider) -> Provider:
    if not provider.id:
        raise ValueError("Provider must define an id")
    with _lock:
        if provider.id not in _providers:
            _registered_at[provider.id] = len(_registered_at)
            _order.append(provider.id)
            _order.sort(key=_display_rank)
        _providers[provider.id] = provider
    return provider


def _display_rank(provider_id: str) -> tuple[int, int]:
    """Bundled backends keep a curated order; others keep registration order."""
    if provider_id in BUILTIN_ORDER:
        return (0, BUILTIN_ORDER.index(provider_id))
    return (1, _registered_at[provider_id])


def get(provider_id: str) -> Provider:
    _ensure_loaded()
    try:
        return _providers[provider_id]
    except KeyError:
        raise ProviderError(
            f"Unknown backend {provider_id!r}. Available: {', '.join(ids())}"
        ) from None


def has(provider_id: str) -> bool:
    _ensure_loaded()
    return provider_id in _providers


def ids() -> list[str]:
    _ensure_loaded()
    with _lock:
        return list(_order)


def all_providers() -> list[Provider]:
    _ensure_loaded()
    with _lock:
        return [_providers[i] for i in _order]


def describe_all() -> list[dict]:
    return [p.describe() for p in all_providers()]


def default_id() -> str:
    """First provider that is ready to run, else the first registered one."""
    providers = all_providers()
    for provider in providers:
        if provider.availability().ready:
            return provider.id
    return providers[0].id if providers else ""


def snapshot() -> dict:
    """Everything the API exposes, computing each availability once."""
    described = []
    default = ""
    for provider in all_providers():
        entry = provider.describe()
        described.append(entry)
        if not default and entry["status"]["ready"]:
            default = provider.id
    if not default and described:
        default = described[0]["id"]
    return {"providers": described, "default": default}


def load_builtin() -> None:
    """Import the bundled providers; each module registers itself on import.

    Display order comes from :data:`BUILTIN_ORDER`, not from import order, so
    an import sorter cannot silently reshuffle the UI.
    """
    from soundcraft.providers import (  # noqa: F401
        comfyui,
        gemini,
        huggingface,
        local,
        replicate,
    )
