from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://messenger:messenger@db:5432/messenger"
    secret_key: str = "dev-secret-change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    llm_api_key: str = ""
    llm_api_base: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost"


settings = Settings()
