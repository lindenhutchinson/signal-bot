from signal_chatbot.config import Settings


def test_new_command_settings_have_defaults() -> None:
    settings = Settings(deepseek_api_key="k", bot_number="+1", _env_file=None)

    assert settings.command_log_window == 40
    assert settings.reset_farewell_max_chars == 200
