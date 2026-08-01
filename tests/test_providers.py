from __future__ import annotations

import pytest

from soundcraft.providers import registry
from soundcraft.providers.base import Option, ParamSpec, ProviderError


class TestParamSpec:
    def test_number_returns_int_when_bounds_are_integral(self):
        spec = ParamSpec("duration", "Duration", "number", default=30, minimum=1, maximum=60)
        assert spec.coerce("45") == 45
        assert isinstance(spec.coerce("45"), int)

    def test_number_keeps_float_when_step_is_fractional(self):
        spec = ParamSpec("guidance", "Guidance", "number", default=3.0, step=0.5)
        assert spec.coerce("2.5") == 2.5

    def test_number_rejects_out_of_range(self):
        spec = ParamSpec("duration", "Duration", "number", default=30, minimum=1, maximum=60)
        with pytest.raises(ValueError, match="must be <= 60"):
            spec.coerce(120)
        with pytest.raises(ValueError, match="must be >= 1"):
            spec.coerce(0)

    def test_number_rejects_non_numeric(self):
        spec = ParamSpec("duration", "Duration", "number", default=30)
        with pytest.raises(ValueError, match="expected a number"):
            spec.coerce("soon")

    def test_select_rejects_unlisted_value(self):
        spec = ParamSpec(
            "model", "Model", "select", default="a", options=(Option("a", "A"),)
        )
        with pytest.raises(ValueError, match="choose one of"):
            spec.coerce("z")

    def test_bool_accepts_common_spellings(self):
        spec = ParamSpec("stereo", "Stereo", "bool", default=False)
        assert spec.coerce("yes") is True
        assert spec.coerce("off") is False
        assert spec.coerce(True) is True

    def test_empty_optional_becomes_none_not_default(self):
        spec = ParamSpec("seed", "Seed", "number", default=None, optional=True)
        assert spec.coerce("") is None

    def test_empty_required_falls_back_to_default(self):
        spec = ParamSpec("duration", "Duration", "number", default=30)
        assert spec.coerce(None) == 30


class TestCoerceParams:
    def test_fills_defaults_for_missing_params(self, fake_provider):
        assert fake_provider.coerce_params({}) == {"duration": 10, "model": "a", "seed": None}

    def test_rejects_unknown_param(self, fake_provider):
        with pytest.raises(ValueError, match="unknown parameter"):
            fake_provider.coerce_params({"tempo": 120})

    def test_validates_through_to_the_spec(self, fake_provider):
        with pytest.raises(ValueError, match="must be <= 60"):
            fake_provider.coerce_params({"duration": 999})


class TestRegistry:
    def test_every_builtin_is_describable(self):
        for provider in registry.all_providers():
            described = provider.describe()
            assert described["id"] and described["label"]
            assert "status" in described
            assert isinstance(described["params"], list)

    def test_provider_ids_are_unique(self):
        ids = registry.ids()
        assert len(ids) == len(set(ids))

    def test_unknown_backend_names_the_alternatives(self):
        with pytest.raises(ProviderError, match="Available:"):
            registry.get("nope")

    def test_settings_keys_do_not_collide_across_providers(self):
        owners: dict[str, str] = {}
        for provider in registry.all_providers():
            for spec in provider.settings:
                assert spec.key not in owners, (
                    f"{spec.key} claimed by both {owners.get(spec.key)} and {provider.id}"
                )
                owners[spec.key] = provider.id

    def test_default_id_prefers_a_ready_provider(self, monkeypatch):
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
        assert registry.get(registry.default_id()).availability().ready


class TestRegistryOrdering:
    def test_a_third_party_provider_can_register(self, fake_provider):
        """`list.sort` empties the list while the key function runs, so display
        order must not be derived from the list being sorted."""
        from soundcraft.providers import registry

        registry._ensure_loaded()
        try:
            registry.register(fake_provider)
            assert fake_provider.id in registry.ids()
            # Bundled backends keep their curated order, newcomers follow.
            assert registry.ids()[: len(registry.BUILTIN_ORDER)] == list(
                registry.BUILTIN_ORDER
            )
            assert registry.ids()[-1] == fake_provider.id
        finally:
            registry._providers.pop(fake_provider.id, None)
            registry._registered_at.pop(fake_provider.id, None)
            if fake_provider.id in registry._order:
                registry._order.remove(fake_provider.id)


class TestOptionalDependencyProbes:
    def test_lyria_reports_missing_deps_instead_of_raising(self, monkeypatch):
        """find_spec raises when the parent package is absent — the normal case
        for a core install without the [lyria] extra."""
        import importlib.util

        from soundcraft.providers import registry

        def explode(name, *args, **kwargs):
            if name.startswith("google"):
                raise ModuleNotFoundError("No module named 'google'")
            return importlib.util.find_spec(name, *args, **kwargs)

        monkeypatch.setattr("importlib.util.find_spec", explode)
        status = registry.get("lyria").availability()
        assert status.ready is False
        assert "google-genai" in status.reason

    def test_describe_all_survives_a_missing_optional_dependency(self, monkeypatch):
        import importlib.util

        from soundcraft.providers import registry

        def explode(name, *args, **kwargs):
            if name.startswith(("google", "torch", "transformers")):
                raise ModuleNotFoundError(f"No module named {name!r}")
            return importlib.util.find_spec(name, *args, **kwargs)

        monkeypatch.setattr("importlib.util.find_spec", explode)
        assert len(registry.describe_all()) == len(registry.ids())
        assert registry.default_id()
