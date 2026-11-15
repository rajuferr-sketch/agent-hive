"""Communication subpackage."""

from agent_hive.communication.bus import BROADCAST, MASTER, MessageBus

__all__ = ["MessageBus", "MASTER", "BROADCAST"]
