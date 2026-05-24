# app/routes/profile_routes.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.auth import get_current_user  # adjust if your import differs
from app.models.user import User
from app.models.handler import Handler
from app.schemas.profile_schema import ProfileOut, ProfileUpdate, HandlerFields

router = APIRouter(prefix="/profile", tags=["Profile"])

def _to_profile_out(u: User) -> ProfileOut:
    h = u.handler
    return ProfileOut(
        user_id=u.user_id,
        first_name=u.first_name,
        last_name=u.last_name,
        email=u.email,
        phone=u.phone,
        domicile_lat=u.domicile_lat,
        domicile_lng=u.domicile_lng,
        address_line1=u.address_line1,
        address_line2=u.address_line2,
        city=u.city,
        state_province=u.state_province,
        postal_code=u.postal_code,
        country=u.country,
        has_handler=bool(h),
        handler_id=h.handler_id if h else None,
        handler=HandlerFields(
            experience_level=h.experience_level if h else None,
            status=h.status if h else None,
            group_affiliation=h.group_affiliation if h else None,  
            notes=h.notes if h else None,
        ),
    )

@router.get("/me", response_model=ProfileOut)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    u = db.query(User).filter(User.user_id == current_user.user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_profile_out(u)

@router.patch("/me", response_model=ProfileOut)
def update_my_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    u = db.query(User).filter(User.user_id == current_user.user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    # --- update user fields ---
    for field in [
        "first_name","last_name","phone",
        "domicile_lat","domicile_lng",
        "address_line1","address_line2","city","state_province","postal_code","country",
    ]:
        val = getattr(payload, field)
        if val is not None:
            setattr(u, field, val)

    # --- handler: lazy create if any handler field present ---
    h = getattr(payload, "handler", None)

    handler_fields_present = bool(h) and any(
        getattr(h, f, None) is not None
        for f in ["experience_level", "status", "group_affiliation", "notes"]
    )

    if handler_fields_present:
        if not u.handler:
            u.handler = Handler(user_id=u.user_id)

        if h.experience_level is not None:
            u.handler.experience_level = h.experience_level
        if h.status is not None:
            u.handler.status = h.status
        if h.group_affiliation is not None:
            u.handler.group_affiliation = h.group_affiliation
        if h.notes is not None:
            u.handler.notes = h.notes


    db.add(u)
    db.commit()
    db.refresh(u)
    return _to_profile_out(u)
