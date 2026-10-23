import os
from typing import Optional, Set
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PORT: int = int(os.environ.get("PORT", "8000"))
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PUBLIC_BASE_URL: str = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000/a2a")
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./a2a_invoice_agent.db")

    # Optional fixed bearer token or comma-separated tokens. If not set, any valid Bearer token acts as an isolated principal.
    AUTH_BEARER_TOKEN: Optional[str] = os.environ.get("AUTH_BEARER_TOKEN", None)

    # AI Model Settings
    TEST_MODE: bool = os.environ.get("TEST_MODE", "true").lower() in ("true", "1", "yes")
    AI_PROVIDER: str = os.environ.get("AI_PROVIDER", "openai")
    AI_BASE_URL: Optional[str] = os.environ.get("AI_BASE_URL", None)
    AI_API_KEY: Optional[str] = os.environ.get("AI_API_KEY", None)
    AI_MODEL: str = os.environ.get("AI_MODEL", "gpt-4o-mini")

    @property
    def normalized_public_base_url(self) -> str:
        # 1. If explicit non-localhost PUBLIC_BASE_URL is set, use it
        configured = self.PUBLIC_BASE_URL.strip().rstrip("/")
        if configured and "localhost" not in configured and "127.0.0.1" not in configured:
            url = configured
        # 2. Render automatically injects RENDER_EXTERNAL_URL (e.g. https://my-service.onrender.com)
        elif os.environ.get("RENDER_EXTERNAL_URL"):
            url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
        elif os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
            url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME').strip().rstrip('/')}"
        else:
            url = configured

        if not url.endswith("/a2a"):
            url = f"{url}/a2a"
        return url

    @property
    def allowed_tokens(self) -> Optional[Set[str]]:
        if not self.AUTH_BEARER_TOKEN:
            return None
        tokens = {t.strip() for t in self.AUTH_BEARER_TOKEN.split(",") if t.strip()}
        return tokens if tokens else None



settings = Settings()
