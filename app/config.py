"""Central settings. Env vars win; sane local defaults otherwise."""
import os


class Settings:
    app_env: str = os.getenv("APP_ENV", "dev")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./invoicehub.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    jwt_exp_minutes: int = int(os.getenv("JWT_EXP_MINUTES", "480"))


settings = Settings()
