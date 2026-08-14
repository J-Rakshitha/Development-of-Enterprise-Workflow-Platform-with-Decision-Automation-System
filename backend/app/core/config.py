"""
Central configuration for the Development of Enterprise Workflow Platform with Decision Automation System.
Loads values from environment variables / .env file.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Development of Enterprise Workflow Platform with Decision Automation System"
    ENV: str = "development"
    DEBUG: bool = True

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./coordination_engine.db"

    # LLM (Hybrid AI strategy)
    GEMINI_API_KEY: str = ""
    LLM_PROVIDER: str = "gemini"
    LLM_ENABLED: bool = True
    LLM_TIMEOUT_SECONDS: int = 6
    LLM_MODEL: str = "gemini-flash-latest"

    # CORS
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # Synthetic data generator toggle (backend simulate APIs for pytest only)
    SYNTHETIC_DATA_ENABLED: bool = True
    SIMULATE_UI_ENABLED: bool = False
    MONITORING_UI_ENABLED: bool = False

    # Real GitHub Integration (Phase A — replaces simulated dev-collab data)
    GITHUB_TOKEN: str = ""
    GITHUB_REPO_OWNER: str = "J-Rakshitha"
    GITHUB_REPO_NAME: str = "dev-collab-test-repo"
    # GitHub webhook — set in repo Settings → Webhooks; verifies X-Hub-Signature-256
    GITHUB_WEBHOOK_SECRET: str = ""
    # Public URL of this backend (for webhook setup docs); e.g. https://your-app.onrender.com
    PUBLIC_BACKEND_URL: str = "http://localhost:8000"

    # Real Observability Integration — Grafana/Prometheus alert webhook (AIOps)
    METRICS_WEBHOOK_SECRET: str = ""

    # Anomaly detection thresholds (configurable per environment — not hardcoded in agents)
    MONITORING_RESPONSE_TIME_MS_THRESHOLD: int = 1500
    MONITORING_ERROR_RATE_PCT_THRESHOLD: int = 10
    MONITORING_DB_POOL_USAGE_PCT_THRESHOLD: int = 85

    # Phase B — Real Server Monitoring (background HTTP probes)
    MONITORING_ENABLED: bool = True
    MONITOR_INTERVAL_SECONDS: int = 30
    MONITOR_BACKEND_NAME: str = "coordination-engine-backend"
    MONITOR_BACKEND_URL: str = "http://127.0.0.1:8000/api/system/health"
    MONITOR_EXTERNAL_NAME: str = "github-external-api"
    MONITOR_EXTERNAL_URL: str = "https://api.github.com"

    # Phase C — Multi-user Login (JWT)
    AUTH_SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"

    # Notification Agent — team alerts (WebSocket + email)
    NOTIFICATION_EMAIL_ENABLED: bool = True
    NOTIFICATION_FROM_EMAIL: str = "aiops@infosys.com"
    NOTIFICATION_ONCALL_EMAIL: str = "oncall@infosys.com"
    # Comma-separated real inboxes for conflict/other team alerts (overrides demo addresses when set)
    NOTIFICATION_TEAM_EMAILS: str = ""
    NOTIFICATION_SMTP_HOST: str = ""
    NOTIFICATION_SMTP_PORT: int = 587
    NOTIFICATION_SMTP_USER: str = ""
    NOTIFICATION_SMTP_PASSWORD: str = ""

    # Slack / Discord / Microsoft Teams — optional real-time team alerts (incoming webhook URLs)
    SLACK_WEBHOOK_URL: str = ""
    DISCORD_WEBHOOK_URL: str = ""
    TEAMS_WEBHOOK_URL: str = ""

    # Rate limiting (public API abuse protection)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_PER_MINUTE: int = 20
    RATE_LIMIT_API_PER_MINUTE: int = 120

    # Redis + background job queue (workflows run async — API returns immediately)
    REDIS_URL: str = ""
    JOB_QUEUE_ENABLED: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Singleton settings instance used across the app
settings = Settings()

_PLACEHOLDER_API_KEYS = {
    "",
    "your_gemini_api_key_here",
    "your-gemini-api-key-here",
    "changeme",
}


def is_llm_key_valid() -> bool:
    """True only when a real (non-placeholder) Gemini key is configured."""
    key = (settings.GEMINI_API_KEY or "").strip()
    return key not in _PLACEHOLDER_API_KEYS and len(key) > 10


def is_production() -> bool:
    """True when ENV=production — demo simulate endpoints and UI controls are disabled."""
    return (settings.ENV or "").strip().lower() == "production"


def simulate_endpoints_enabled() -> bool:
    """Simulate APIs allowed only outside production (buttons hidden, not deleted)."""
    return not is_production() and settings.SYNTHETIC_DATA_ENABLED


def redis_configured() -> bool:
    return bool((settings.REDIS_URL or "").strip())
