"""
config.py — Configuração da API via variáveis de ambiente / .env

Usa pydantic-settings: lê de variáveis de ambiente E de um arquivo .env, com a
variável de ambiente tendo precedência. Em produção, defina DATABASE_URL e
DASHBOARD_TOKEN como variáveis de ambiente reais (sem arquivo).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Conexão com o PostgreSQL (driver async asyncpg).
    # O valor real vem do .env em dev; o default abaixo é apenas um placeholder
    # que NÃO contém segredo de produção.
    database_url: str = "postgresql+asyncpg://argus:CHANGE_ME@localhost:5432/argus"

    # Token único para os endpoints de consulta do dashboard.
    dashboard_token: str = "argus-dashboard-dev-token"

    app_env: str = "dev"
    log_level: str = "INFO"

    # Sessões de login do dashboard
    session_ttl_hours: int = 12

    # Sem payload por mais que isso → servidor considerado OFFLINE
    offline_after_seconds: int = 600

    # Intervalo do loop em background que detecta servidores OFFLINE
    offline_check_seconds: int = 60


settings = Settings()
