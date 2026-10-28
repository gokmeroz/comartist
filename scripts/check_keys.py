"""Print which provider keys are configured (set / not set). Never prints key values."""

from comartist.config import PROVIDERS

for provider_id, option in PROVIDERS.items():
    if option.api_key_env:
        state = "set" if option.key_present() else "not set"
        print(f"{provider_id:10} {option.api_key_env:30} {state}")
