from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Environment variables

    app_name: str = Field(default="Learning Management Service", alias="NAME")
    debug: bool = Field(default=False, alias="DEBUG")
    address: str = Field(default="127.0.0.1", alias="ADDRESS")
    port: int = Field(default=8000, alias="PORT")
    reload: bool = Field(default=False, alias="RELOAD")

    api_key: str = Field(alias="API_KEY")

    cors_origins: list[str] = Field(default=[], alias="CORS_ORIGINS")

    enable_interactions: bool = Field(default=False, alias="APP_ENABLE_INTERACTIONS")
    enable_learners: bool = Field(default=False, alias="APP_ENABLE_LEARNERS")

    autochecker_api_url: str = Field(
        default="https://auche.namaz.live", alias="AUTOCHECKER_API_URL"
    )
    autochecker_email: str = Field(default="", alias="AUTOCHECKER_EMAIL")
    autochecker_password: str = Field(default="", alias="AUTOCHECKER_PASSWORD")

    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="lab-5", alias="DB_NAME")
    db_user: str = Field(default="postgres", alias="DB_USER")
    db_password: str = Field(default="postgres", alias="DB_PASSWORD")

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: object) -> object:
        """Accept both boolean values and common mode strings."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"debug", "dev", "development"}:
                return True
        return value

    model_config = SettingsConfigDict(
        env_file=".env.secret",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow",
    )


settings = Settings.model_validate({})
