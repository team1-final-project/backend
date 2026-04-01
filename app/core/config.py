from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Stocker API"
    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    mysql_user: str = "root"
    mysql_password: str = "1234"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_db: str = "stocker"

    database_url: str = "mysql+pymysql://root:1234@127.0.0.1:3306/stocker"

    jwt_secret_key: str = "change-this-to-a-long-random-secret-key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    admin_username: str = "admin"
    admin_password: str = "admin1234"
    admin_full_name: str = "Stocker Admin"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()