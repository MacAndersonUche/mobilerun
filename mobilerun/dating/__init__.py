"""Dating mode automation for Mobilerun."""

from .dating_agent import DatingAgent
from .scheduler import DatingScheduler
from .stats import DatingStats
from .persona import PersonaManager
from .message_queue import SequentialMessageQueue, QueuedMessage, MessageType
from .openers import (
    OpenerLibrary,
    compose_dating_message,
    load_default_library,
    pick_template_opener,
)
from .date_flow import DateFlowConfig, DateFlowManager
from .matches import MatchRecord, MatchStore

__all__ = [
    "DatingAgent",
    "DatingScheduler",
    "DatingStats",
    "PersonaManager",
    "SequentialMessageQueue",
    "QueuedMessage",
    "MessageType",
    "OpenerLibrary",
    "compose_dating_message",
    "load_default_library",
    "pick_template_opener",
    "DateFlowConfig",
    "DateFlowManager",
    "MatchRecord",
    "MatchStore",
]
