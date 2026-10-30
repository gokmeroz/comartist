"""Environment-based application settings and the provider catalog."""

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Base for application settings as configuration needs emerge."""

    model_config = SettingsConfigDict(env_prefix="COMARTIST_", env_file=".env", extra="ignore")

    runs_dir: Path = Path("runs")


class ModelPrice(BaseModel):
    """USD list prices; unset fields mean the price is unknown."""

    input_per_m_tokens: float | None = None
    output_per_m_tokens: float | None = None
    per_image: float | None = None


class EndpointSettings(BaseSettings):
    """An OpenAI-style endpoint. UI model labels map to provider model IDs."""

    api_key: SecretStr | None = None
    base_url: str
    api_style: Literal["responses", "chat_completions"] = "chat_completions"
    image_style: Literal["responses", "images", "flux_workflow"] = "images"
    text_model_ids: dict[str, str] = {}
    image_model_ids: dict[str, str] = {}
    prices: dict[str, ModelPrice] = {}  # keyed by provider model ID
    timeout_s: float = 120.0


class MetaSettings(EndpointSettings):
    """Meta Model API: text and images both go through `/v1/responses` (dev.meta.ai/docs)."""

    model_config = SettingsConfigDict(env_prefix="COMARTIST_META_", env_file=".env", extra="ignore")

    base_url: str = "https://api.meta.ai/v1"
    api_style: Literal["responses", "chat_completions"] = "responses"
    image_style: Literal["responses", "images", "flux_workflow"] = "responses"
    text_model_ids: dict[str, str] = {"Muse Wonder": "muse-wonder-1.0"}
    image_model_ids: dict[str, str] = {"Muse Image": "muse-image-1.0"}
    prices: dict[str, ModelPrice] = {
        "muse-wonder-1.0": ModelPrice(input_per_m_tokens=4.0, output_per_m_tokens=20.0),
        "muse-image-1.0": ModelPrice(per_image=0.01),
    }


class FireworksSettings(EndpointSettings):
    """Fallback for text and images when Meta credits run out or the API is down.

    FLUX takes no reference images, so fallback panels lose character conditioning.
    """

    model_config = SettingsConfigDict(env_prefix="COMARTIST_FIREWORKS_", env_file=".env", extra="ignore")

    base_url: str = "https://api.fireworks.ai/inference/v1"
    text_model_ids: dict[str, str] = {
        "Llama (open weights)": "accounts/fireworks/models/llama-v3p3-70b-instruct"
    }
    image_style: Literal["responses", "images", "flux_workflow"] = "flux_workflow"
    image_model_ids: dict[str, str] = {"FLUX.1 schnell": "accounts/fireworks/models/flux-1-schnell-fp8"}


class ProviderOption(BaseModel):
    """A model backend the sidebar can offer."""

    label: str
    text_models: list[str]
    image_models: list[str]
    api_key_env: str | None = None
    implemented: bool = False
    note: str = ""

    def key_present(self) -> bool:
        if self.api_key_env is None:
            return True
        return bool(os.environ.get(self.api_key_env) or dotenv_values(".env").get(self.api_key_env))


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
        text_models=["Muse Wonder"],
        image_models=["Muse Image"],
        api_key_env="COMARTIST_META_API_KEY",
        implemented=True,
        note="Primary provider ($150 credits). Story, script, Critic, and visual planning are live; images onward are simulated.",
    ),
    "fireworks": ProviderOption(
        label="Fireworks (Meta open weights)",
        text_models=["Llama (open weights)"],
        image_models=["FLUX.1 schnell"],
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
