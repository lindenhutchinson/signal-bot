"""Per-group runtime state, split into focused sub-stores behind one connection.

``Database`` owns the connection and exposes the sub-stores (directives, command
log, disclaimers, arming, profiles); ``__main__`` wires the specific sub-store
into each consumer.
"""

from signal_chatbot.state.commands import LoggedCommand
from signal_chatbot.state.database import Database
from signal_chatbot.state.directives import Directive, DirectiveSet
from signal_chatbot.state.disclaimers import Disclaimer
from signal_chatbot.state.profiles import Profile

__all__ = [
    "Database",
    "Directive",
    "DirectiveSet",
    "Disclaimer",
    "LoggedCommand",
    "Profile",
]
