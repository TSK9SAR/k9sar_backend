from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.auth import get_current_user, require_mfa_verified, require_admin


from app.models.user import User
from app.models.discipline_group import DisciplineGroup

from app.schemas.user_group_schema import UserGroupUpdate

router = APIRouter(prefix="/users", tags=["Evaluator Groups"])


@router.put("/{user_id}/discipline-groups")
def replace_user_groups(
    user_id: int,
    payload: UserGroupUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    groups = []
    if payload.group_ids:
        groups = db.query(DisciplineGroup).filter(DisciplineGroup.group_id.in_(payload.group_ids)).all()
        found = {g.group_id for g in groups}
        missing = [gid for gid in payload.group_ids if gid not in found]
        if missing:
            raise HTTPException(status_code=404, detail=f"Discipline groups not found: {missing}")

    user.discipline_groups = groups
    db.commit()
    db.refresh(user)

    return {
        "user_id": user.user_id,
        "group_ids": [g.group_id for g in user.discipline_groups],
    }
