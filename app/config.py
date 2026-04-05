from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # InHire
    inhire_api_url: str = "https://api.inhire.app"
    inhire_auth_url: str = "https://auth.inhire.app"
    inhire_email: str = ""
    inhire_password: str = ""
    inhire_tenant: str = "inhire.app"

    # Slack
    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"

    # Server
    webhook_base_url: str = "https://agente.adianterecursos.com.br"
    redis_url: str = "redis://localhost:6379/2"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
