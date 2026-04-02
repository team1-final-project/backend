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

    jwt_secret_key: str = "change-this"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""

    email_code_expire_minutes: int = 10
    email_signup_token_expire_minutes: int = 20

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    frontend_google_callback_url: str = ""

    kakao_rest_api_key: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = ""
    frontend_kakao_callback_url: str = ""

    naver_client_id: str = ""
    naver_client_secret: str = ""
    naver_redirect_uri: str = ""
    frontend_naver_callback_url: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()