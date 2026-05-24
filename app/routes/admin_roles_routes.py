from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.auth import get_current_user, require_supervisor
from app.models.role import Role  # adjust import if your model path differs
from app.schemas.role_schema import RoleOut

router = APIRouter(prefix="/admin", tags=["Admin"])

@router.get("/roles", response_model=List[RoleOut])
def list_roles(
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),
):
    # Only supervisors/admins can see roles (change if you want everyone to read roles)

    roles = db.query(Role).order_by(Role.role_name.asc()).all()
    return roles
