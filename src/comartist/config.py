"""Environment-based application settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Base for application settings as configuration needs emerge."""

    model_config = SettingsConfigDict(env_prefix="COMARTIST_")
