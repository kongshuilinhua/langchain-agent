from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from core.db.models import User, WorkspaceMember
from core.db.session import get_db
from core.security.auth import decode_access_token
from core.security.permissions import can_manage


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return user


def get_current_membership(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceMember:
    membership = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == current_user.id)
        .order_by(WorkspaceMember.id.asc())
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No workspace membership")
    return membership


def require_manager(membership: WorkspaceMember = Depends(get_current_membership)) -> WorkspaceMember:
    if not can_manage(membership.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return membership
