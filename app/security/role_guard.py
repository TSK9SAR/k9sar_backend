# from typing import List
# from fastapi import HTTPException, status
# from app.models import User


# def require_role(user: User, allowed_roles: List[str]) -> None:
#     """Check if user has permission based on their role names."""
#     # Collect the role names from the user's roles relationship
#     user_role_names = [r.role_name for r in user.roles]

#     # If none of the user's roles is in the allowed list, deny access
#     if not any(role in user_role_names for role in allowed_roles):
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="You do not have permission for this action.",
#         )


# def require_admin(user: User) -> None:
#     require_role(user, ["admin"])


# def require_supervisor(user: User) -> None:
#     require_role(user, ["admin", "supervisor"])


# def require_member(user: User) -> None:
#     require_role(user, ["admin", "supervisor", "member"])
