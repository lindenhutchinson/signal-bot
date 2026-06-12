"""Signal transport adapter.

Isolates the rest of the application from how we actually talk to Signal. Today
this is the ``signal-cli-rest-api`` (json-rpc mode) bridge; swapping to a direct
``signal-cli`` daemon would only touch this package.
"""

from signal_chatbot.transport.client import ProfileNameSetter, SignalClient
from signal_chatbot.transport.models import IncomingMessage, OutgoingMessage

__all__ = ["SignalClient", "ProfileNameSetter", "IncomingMessage", "OutgoingMessage"]
