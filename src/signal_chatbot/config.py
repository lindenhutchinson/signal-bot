"""Application configuration, loaded from the environment / a .env file."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

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
    # deepseek-v4-* models default to thinking mode; off is faster/cheaper and lets us
    # force tool_choice. Sent explicitly as {"thinking": {"type": "..."}} on every call.
    deepseek_thinking: bool = False

    # Signal transport
    signal_api_url: str = "http://signal-cli-rest-api:8080"
    bot_number: str

    # Lockdown / behaviour
    allowed_group_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allowed_senders: Annotated[list[str], NoDecode] = Field(default_factory=list)
    trigger_alias: str = "@bot"
    # Probability (0..1) the bot chimes in unprompted on a message that didn't summon it.
    # Low by design; set 0 to disable.
    unprompted_reply_chance: float = 0.05
    system_prompt_path: Path = Path("prompts/identity.md")
    history_window_max: int = 40
    database_path: Path = Path("data/history.sqlite")
    max_tool_iterations: int = 25
    command_log_window: int = 40
    reset_farewell_max_chars: int = 200
    default_display_name: str = "bot"
    # IANA timezone for all human-facing timestamps (summon prompt, command lists).
    # Australia/Sydney auto-switches AEST (UTC+10) ⇄ AEDT (UTC+11) with daylight saving.
    display_timezone: str = "Australia/Sydney"

    # Wikipedia lookup
    wikipedia_language: str = "en"
    wikipedia_cache_ttl_seconds: int = 21600  # 6h
    wikipedia_search_limit: int = 5
    wikipedia_max_section_chars: int = 2000
    wikipedia_user_agent: str = "signal-chatbot/0.1 (contact: you@example.com)"

    @field_validator("allowed_group_ids", "allowed_senders", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept a comma-separated string for list-typed settings."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @cached_property
    def display_tz(self) -> ZoneInfo:
        """The resolved timezone for human-facing timestamps."""
        return ZoneInfo(self.display_timezone)

    def load_system_prompt(self) -> str:
        """Read the system prompt file from disk."""
        return self.system_prompt_path.read_text(encoding="utf-8").strip()
