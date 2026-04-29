from __future__ import annotations

from enum import Enum

from fastapi import Depends, HTTPException

from api.security import AuthenticatedUser, require_user


class Role(str, Enum):
    VIEWER   = "viewer"    # read-only: dashboard, forecast, status
    OPERATOR = "operator"  # run optimizations, trigger scenarios
    ADMIN    = "admin"     # battery config, API key management, audit log


_HIERARCHY: dict[Role, int] = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


def require_role(minimum: Role):
    """FastAPI dependency factory — raises 403 if user's role is below *minimum*."""
    def _dep(user: AuthenticatedUser = Depends(require_user)) -> AuthenticatedUser:
        try:
            user_level = _HIERARCHY[Role(user.role)]
        except (ValueError, KeyError):
            user_level = -1
        if user_level < _HIERARCHY[minimum]:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{minimum.value}' or higher required",
            )
        return user

    _dep.__name__ = f"require_{minimum.value}"
    return _dep


require_viewer   = require_role(Role.VIEWER)
require_operator = require_role(Role.OPERATOR)
require_admin    = require_role(Role.ADMIN)
