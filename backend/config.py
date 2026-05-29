from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    gemini_api_key: str = ""
    revenuecat_api_key: str = ""
    revenuecat_project_id: str = ""
    stripe_secret_key: str = ""
    click_merchant_id: str = ""
    click_service_id: str = ""
    click_secret_key: str = ""
    uzum_merchant_id: str = ""
    uzum_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
