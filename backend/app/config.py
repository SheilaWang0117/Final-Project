"""Application configuration.

Load order (first value wins, nothing is overwritten):
1. Variables already set in the process environment.
2. The repository's own `.env` (``<repo>/.env``).
3. The `.env` one directory above the repository (``<repo>/../.env``).

Paths are resolved from this file, so the working directory does not matter.
Secrets are never logged; use :func:`redact` before printing any text that
might contain them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

# The course key may only be used with this model through this gateway.
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
PORTKEY_MODEL = "gpt-6-luna"

SECRET_NAMES = ("PORTKEY_API_KEY", "OPENAI_API_KEY")


def env_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    return [repo_root / ".env", repo_root.parent / ".env"]


def load_environment(repo_root: Path = REPO_ROOT, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Fill missing variables from the repo `.env`, then the parent `.env`.

    Returns a mapping of variable name -> origin ("environment", "repo .env",
    "parent .env") so the Settings page can show where values came from
    without showing the values themselves.
    """
    target = os.environ if environ is None else environ
    origins = {k: "environment" for k in target}
    for path, label in zip(env_files(repo_root), ("repo .env", "parent .env")):
        if not path.is_file():
            continue
        for key, value in dotenv_values(path).items():
            if value is None or key in target:
                continue
            target[key] = value
            origins[key] = label
    return origins


ENV_ORIGINS = load_environment()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_mode: str  # "demo" or "live"
    llm_provider: str  # "portkey", "openai", or "none"
    model_name: str | None
    database_path: Path
    research_cache_path: Path
    upload_max_bytes: int
    import_max_rows: int
    research_cache_ttl_hours: int
    http_timeout_seconds: float
    http_max_bytes: int
    http_concurrency: int
    http_retries: int
    run_request_limit: int
    run_tool_calls_limit: int
    run_total_tokens_limit: int
    run_timeout_seconds: float
    daily_token_limit: int
    daily_run_limit: int
    daily_cost_limit_usd: float
    sec_user_agent: str
    sec_contact_configured: bool
    default_timezone: str
    briefing_hour: int
    enable_scheduler: bool
    errors: list[str] = field(default_factory=list)

    @property
    def is_demo(self) -> bool:
        return self.app_mode == "demo"

    def provider_status(self) -> dict:
        """Describe the configured provider without revealing secrets."""
        return {
            "mode": self.app_mode,
            "provider": self.llm_provider,
            "model": self.model_name,
            "gateway": PORTKEY_BASE_URL if self.llm_provider == "portkey" else None,
            "portkey_key_present": bool(os.getenv("PORTKEY_API_KEY")),
            "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
            "key_origin": {k: ENV_ORIGINS.get(k) for k in SECRET_NAMES if os.getenv(k)},
            "ready": self.llm_ready,
            "errors": self.errors,
        }

    @property
    def llm_ready(self) -> bool:
        if self.is_demo or self.errors:
            return False
        if self.llm_provider == "portkey":
            return bool(os.getenv("PORTKEY_API_KEY"))
        if self.llm_provider == "openai":
            return bool(os.getenv("OPENAI_API_KEY")) and bool(self.model_name)
        return False


def build_settings() -> Settings:
    errors: list[str] = []
    mode = (os.getenv("APP_MODE") or "demo").strip().lower()
    if mode not in {"demo", "live"}:
        errors.append(f"APP_MODE must be 'demo' or 'live' (got {mode!r}); using demo.")
        mode = "demo"

    provider = (os.getenv("LLM_PROVIDER") or "portkey").strip().lower()
    model: str | None
    if provider == "portkey":
        requested = (os.getenv("PORTKEY_MODEL") or PORTKEY_MODEL).strip()
        if requested != PORTKEY_MODEL:
            # Never silently switch: refuse instead of using another model.
            errors.append(
                f"PORTKEY_MODEL={requested!r} is not allowed. The course Portkey key may only be used with {PORTKEY_MODEL}."
            )
        model = PORTKEY_MODEL
    elif provider == "openai":
        model = (os.getenv("OPENAI_MODEL") or "").strip() or None
        if not model:
            errors.append("LLM_PROVIDER=openai requires OPENAI_MODEL to be set explicitly.")
    elif provider == "none":
        model = None
    else:
        errors.append(f"Unknown LLM_PROVIDER {provider!r}; expected portkey, openai, or none.")
        provider, model = "none", None

    data_dir = REPO_ROOT / "data"
    default_db = data_dir / ("demo.db" if mode == "demo" else "ocra_live.db")
    db_path = Path(os.getenv("DATABASE_PATH") or default_db)
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    cache_path = Path(os.getenv("RESEARCH_CACHE_PATH") or data_dir / "public_research_cache.db")
    if not cache_path.is_absolute():
        cache_path = REPO_ROOT / cache_path

    return Settings(
        app_mode=mode,
        llm_provider=provider,
        model_name=model,
        database_path=db_path,
        research_cache_path=cache_path,
        upload_max_bytes=_int("UPLOAD_MAX_BYTES", 5 * 1024 * 1024),
        import_max_rows=_int("IMPORT_MAX_ROWS", 5000),
        research_cache_ttl_hours=_int("RESEARCH_CACHE_TTL_HOURS", 20),
        http_timeout_seconds=_float("HTTP_TIMEOUT_SECONDS", 20.0),
        http_max_bytes=_int("HTTP_MAX_BYTES", 45 * 1024 * 1024),
        http_concurrency=_int("HTTP_CONCURRENCY", 4),
        http_retries=_int("HTTP_RETRIES", 2),
        run_request_limit=_int("AGENT_RUN_REQUEST_LIMIT", 8),
        run_tool_calls_limit=_int("AGENT_RUN_TOOL_CALLS_LIMIT", 12),
        run_total_tokens_limit=_int("AGENT_RUN_TOTAL_TOKENS_LIMIT", 60000),
        run_timeout_seconds=_float("AGENT_RUN_TIMEOUT_SECONDS", 120.0),
        daily_token_limit=_int("DAILY_TOKEN_LIMIT", 1_500_000),
        daily_run_limit=_int("DAILY_RUN_LIMIT", 300),
        daily_cost_limit_usd=_float("DAILY_COST_LIMIT_USD", 5.0),
        sec_user_agent=os.getenv("SEC_USER_AGENT") or "OcraPipelineIntelligence/0.1 (local research prototype)",
        sec_contact_configured=bool(os.getenv("SEC_USER_AGENT")),
        default_timezone=os.getenv("APP_TIMEZONE") or "Asia/Hong_Kong",
        briefing_hour=_int("BRIEFING_HOUR", 7),
        enable_scheduler=(os.getenv("ENABLE_SCHEDULER") or "true").lower() in {"1", "true", "yes"},
        errors=errors,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()


_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|x-portkey-api-key)(\"?\s*[:=]\s*\"?)([^\s\"',}]+)"),
]


def secret_values() -> list[str]:
    return [v for k in SECRET_NAMES if (v := os.getenv(k)) and len(v) >= 6]


def redact(text: str) -> str:
    """Remove configured secret values and key-like strings from text."""
    if not text:
        return text
    for value in secret_values():
        text = text.replace(value, "[REDACTED]")
    text = _KEY_PATTERNS[0].sub("[REDACTED]", text)
    text = _KEY_PATTERNS[1].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    return text


def contains_secret(text: str) -> bool:
    return bool(text) and any(v in text for v in secret_values())
