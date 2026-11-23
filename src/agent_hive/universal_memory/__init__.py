"""Universal shared memory package (cross-client persistent store)."""

from agent_hive.universal_memory.universal import (
    UniversalMemoryError,
    UniversalMemoryManager,
)

__all__ = ["UniversalMemoryError", "UniversalMemoryManager"]
