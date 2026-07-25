import os
import sys
from pathlib import Path

from dotenv import load_dotenv

APP_NAME = "soundcraft"

MODELS = ["melody-large", "stereo-melody-large", "large", "stereo-large"]

DEFAULT_MODEL = "melody-large"
DEFAULT_DURATION = 30

REPLICATE_MODEL_VERSION = "671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"

BACKENDS = ["musicgen", "lyria3"]
DEFAULT_BACKEND = "musicgen"
LYRIA3_MODEL = "lyria-3-clip-preview"

DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 8765

_ENV_KEYS = (
    "REPLICATE_API_TOKEN",
    "GEMINI_API_KEY",
    "LM_STUDIO_URL",
    "LM_STUDIO_MODEL",
)


def is_app_mode() -> bool:
    """True when running as desktop app / PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False)) or os.getenv("SOUNDCRAFT_APP") == "1"


def app_support_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".config" / APP_NAME


def app_env_path() -> Path:
    return app_support_dir() / ".env"


def default_output_dir() -> Path:
    if is_app_mode():
        return Path.home() / "Documents" / APP_NAME / "output"
    return Path("output")


# Mutable default used by CLI/server; refreshed when app mode is enabled.
DEFAULT_OUTPUT_DIR = default_output_dir()


def _candidate_env_paths() -> list[Path]:
    """Prefer Application Support in app mode; otherwise cwd then app support."""
    app_env = app_env_path()
    cwd_env = Path.cwd() / ".env"
    if is_app_mode():
        return [app_env, cwd_env]
    return [cwd_env, app_env]


def load_settings(*, override: bool = False) -> None:
    """Load .env files into os.environ (and refresh module getters)."""
    for path in _candidate_env_paths():
        if path.is_file():
            load_dotenv(path, override=override)


def ensure_app_dirs() -> None:
    app_support_dir().mkdir(parents=True, exist_ok=True)
    default_output_dir().mkdir(parents=True, exist_ok=True)


def enable_app_mode() -> None:
    """Mark process as desktop app and reload paths/settings."""
    os.environ["SOUNDCRAFT_APP"] = "1"
    global DEFAULT_OUTPUT_DIR
    DEFAULT_OUTPUT_DIR = default_output_dir()
    ensure_app_dirs()
    load_settings(override=True)


def get_replicate_api_token() -> str:
    return os.getenv("REPLICATE_API_TOKEN", "")


def get_gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "")


def get_lm_studio_url() -> str:
    return os.getenv("LM_STUDIO_URL", "http://localhost:1234")


def get_lm_studio_model() -> str:
    return os.getenv("LM_STUDIO_MODEL", "liquid/lfm2-24b-a2b")


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "…" + value[-4:]


def read_settings_public() -> dict:
    """Settings for GUI/API: secrets masked, paths absolute."""
    out = default_output_dir().expanduser().resolve()
    return {
        "replicate_api_token_set": bool(get_replicate_api_token()),
        "replicate_api_token_masked": _mask_secret(get_replicate_api_token()),
        "gemini_api_key_set": bool(get_gemini_api_key()),
        "gemini_api_key_masked": _mask_secret(get_gemini_api_key()),
        "lm_studio_url": get_lm_studio_url(),
        "lm_studio_model": get_lm_studio_model(),
        "output_dir": str(out),
        "env_path": str(app_env_path()),
        "app_mode": is_app_mode(),
    }


def save_settings(
    *,
    replicate_api_token: str | None = None,
    gemini_api_key: str | None = None,
    lm_studio_url: str | None = None,
    lm_studio_model: str | None = None,
) -> dict:
    """Persist settings to Application Support .env and update os.environ."""
    ensure_app_dirs()
    current = {
        "REPLICATE_API_TOKEN": get_replicate_api_token(),
        "GEMINI_API_KEY": get_gemini_api_key(),
        "LM_STUDIO_URL": get_lm_studio_url(),
        "LM_STUDIO_MODEL": get_lm_studio_model(),
    }

    if replicate_api_token is not None and replicate_api_token.strip():
        # Empty string after strip with intentional clear: allow explicit ""
        current["REPLICATE_API_TOKEN"] = replicate_api_token.strip()
    elif replicate_api_token is not None and replicate_api_token == "":
        current["REPLICATE_API_TOKEN"] = ""

    if gemini_api_key is not None and gemini_api_key.strip():
        current["GEMINI_API_KEY"] = gemini_api_key.strip()
    elif gemini_api_key is not None and gemini_api_key == "":
        current["GEMINI_API_KEY"] = ""

    if lm_studio_url is not None:
        current["LM_STUDIO_URL"] = lm_studio_url.strip() or "http://localhost:1234"
    if lm_studio_model is not None:
        current["LM_STUDIO_MODEL"] = lm_studio_model.strip() or "liquid/lfm2-24b-a2b"

    lines = [f"{k}={current[k]}" for k in _ENV_KEYS]
    path = app_env_path()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)

    for key in _ENV_KEYS:
        os.environ[key] = current[key]

    # Invalidate cached Lyria client if key changed
    try:
        from soundcraft import generate_lyria

        generate_lyria.reset_client()
    except Exception:
        pass

    return read_settings_public()


# Load on import (CLI / serve). App entry calls enable_app_mode() first.
load_settings(override=False)

# Back-compat aliases (prefer getters for runtime-updated secrets).
REPLICATE_API_TOKEN = get_replicate_api_token()
GEMINI_API_KEY = get_gemini_api_key()
LM_STUDIO_URL = get_lm_studio_url()
LM_STUDIO_MODEL = get_lm_studio_model()
