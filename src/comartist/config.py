"""Environment-based application settings and the provider catalog."""

import os
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Base for application settings as configuration needs emerge."""

    model_config = SettingsConfigDict(env_prefix="COMARTIST_")

    runs_dir: Path = Path("runs")


class ProviderOption(BaseModel):
    """A model backend the sidebar can offer."""

    label: str
    text_models: list[str]
    image_models: list[str]
    api_key_env: str | None = None
    implemented: bool = False
    note: str = ""

    def key_present(self) -> bool:
        return self.api_key_env is None or bool(os.environ.get(self.api_key_env))


PROVIDERS: dict[str, ProviderOption] = {
    "stub": ProviderOption(
        label="Stub (offline, free)",
        text_models=["stub-text"],
        image_models=["stub-image"],
        implemented=True,
        note="Deterministic fake outputs. Counts tokens, costs $0.",
    ),
    "meta": ProviderOption(
        label="Meta Model API",
        text_models=["Muse Spark", "Muse Wonder"],
        image_models=["Muse Image"],
        api_key_env="COMARTIST_META_API_KEY",
        note="Primary provider ($150 credits).",
    ),
    "fireworks": ProviderOption(
        label="Fireworks (Meta open weights)",
        text_models=["Llama (open weights)"],
        image_models=["(none)"],
        api_key_env="COMARTIST_FIREWORKS_API_KEY",
    ),
    "modal": ProviderOption(
        label="Modal (serverless GPU)",
        text_models=["Llama (open weights)"],
        image_models=["Diffusers pipeline"],
        api_key_env="COMARTIST_MODAL_TOKEN",
    ),
    "local": ProviderOption(
        label="Local (vLLM + Diffusers)",
        text_models=["Llama (local)"],
        image_models=["Diffusers (local)"],
    ),
}
