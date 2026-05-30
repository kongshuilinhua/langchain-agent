from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


ROLE_ALIASES = {
    "owner": Role.ADMIN,
    "admin": Role.ADMIN,
    "member": Role.USER,
    "user": Role.USER,
}


def normalize_role(role: str | None) -> str:
    return str(ROLE_ALIASES.get(str(role or "").lower(), Role.USER))


def can_manage(role: str | None) -> bool:
    return normalize_role(role) == Role.ADMIN
