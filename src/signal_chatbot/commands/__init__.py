"""The @-prefixed command subsystem: parsing, dispatch, and reply text."""

from signal_chatbot.commands.parser import Command, CommandName, parse

__all__ = ["Command", "CommandName", "parse"]
