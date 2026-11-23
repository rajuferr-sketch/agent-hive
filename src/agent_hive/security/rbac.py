"""Role-based access control: roles expand to default scope sets.

Scopes are ``resource:action`` strings; ``*`` grants everything and
``resource:*`` grants every action on a resource. Tools and endpoints
declare the scope they require; callers present token scopes.
"""

from typing import Final

ADMIN: Final = "admin"
OPERATOR: Final = "operator"
CLIENT: Final = "client"
READONLY: Final = "readonly"

Role = str  # one of the four names above

ROLE_SCOPES: Final[dict[str, tuple[str, ...]]] = {
    ADMIN: ("*",),
    OPERATOR: (
        "agents:read", "agents:execute",
        "tasks:read", "tasks:write", "tasks:cancel",
        "memory:read", "memory:write",
        "system:read", "system:diagnose", "system:tests",
        "reports:read", "workflows:manage", "github:read", "github:write",
    ),
    CLIENT: (
        "agents:read", "agents:execute",
        "tasks:read", "tasks:write", "tasks:cancel",
        "memory:read", "memory:write",
        "system:read", "reports:read", "workflows:manage",
    ),
    READONLY: (
        "agents:read", "tasks:read", "memory:read",
        "system:read", "reports:read",
    ),
}

ALL_SCOPES: Final[tuple[str, ...]] = (
    "agents:read", "agents:execute",
    "tasks:read", "tasks:write", "tasks:cancel",
    "memory:read", "memory:write",
    "system:read", "system:diagnose", "system:tests",
    "reports:read", "workflows:manage",
    "github:read", "github:write",
    "security:manage",
)


def role_scopes(role: str) -> list[str]:
    """Default scope set for a role name (empty for unknown roles)."""
    return list(ROLE_SCOPES.get(role, ()))


def all_scopes() -> list[str]:
    return list(ALL_SCOPES)
