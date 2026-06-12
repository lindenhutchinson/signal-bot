"""Application configuration, loaded from the environment / a .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings for the bot.

    Values are read from environment variables (and a local ``.env`` file in
    development). Everything the bot needs to run lives here so the rest of the
    code never reaches for ``os.environ`` directly.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DeepSeek
    deepseek_api_key: str
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"

    # Signal transport
    signal_api_url: str = "http://signal-cli-rest-api:8080"
    bot_number: str

    # Lockdown / behaviour
    allowed_group_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allowed_senders: Annotated[list[str], NoDecode] = Field(default_factory=list)
    trigger_alias: str = "@bot"
    system_prompt_path: Path = Path("prompts/identity.md")
    history_window_max: int = 40
    database_path: Path = Path("data/history.sqlite")
    max_tool_iterations: int = 5
    command_log_window: int = 40
    reset_farewell_max_chars: int = 200

    @field_validator("allowed_group_ids", "allowed_senders", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept a comma-separated string for list-typed settings."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def load_system_prompt(self) -> str:
        """Read the system prompt file from disk."""
        return self.system_prompt_path.read_text(encoding="utf-8").strip()
