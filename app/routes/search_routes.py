from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app import models
from app.models.user import User
from app.models.certification import Certification
from app.models.team import Team
from app.utils.geolocation import haversine

router = APIRouter(prefix="/search", tags=["Search"])

@router.get("/teams")
def list_active_certified(db: Session = Depends(get_db)):
    results = (
        db.query(Team)
        # join Team → Certification via the relationship
        .join(Team.certifications)                 # ✅ replaces .join(Team, Certification)
        # optionally, if you need Standard too:
        .join(Certification.standard)
        # add your filters here, e.g.:
        .filter(Team.status == "active")
        .filter(Certification.status == "current")
        .options(
            joinedload(Team.handler),
            joinedload(Team.dog),
            joinedload(Team.certifications).joinedload(Certification.standard),
        )
        .all()
    )
    return results

@router.get("/incident")
def search_by_location(
    lat: float,
    lng: float,
    radius_km: float = 100,
    db: Session = Depends(get_db),
):
    """
    Return certified, active teams within radius_km of an incident location.

    Logic:
    - Team.status == "active"
    - Certification.status == "active"
    - Team → Handler → User has a domicile location
    - Compute distance incident ↔ domicile
    """
    results: list[dict] = []

    teams = (
        db.query(models.Team)
        # Certification join via relationship
        .join(models.Team.certifications)
        # Handler and User joins via relationships
        .join(models.Team.handler)
        .join(models.Handler.user)
        .filter(models.Team.status == "active")
        .filter(models.Certification.status == "active")
        .options(
            joinedload(models.Team.handler)
            .joinedload(models.Handler.user),
            joinedload(models.Team.dog),
            joinedload(models.Team.certifications),
        )
        .all()
    )

    for team in teams:
        # adjust depending on where domicile_* live
        user = team.handler.user

        # if domicile is on Handler instead, use team.handler.domicile_lat, etc.
        if user.domicile_lat is not None and user.domicile_lng is not None:
            dist = haversine(lat, lng, user.domicile_lat, user.domicile_lng)
            if dist <= radius_km:
                results.append({
                    "member": f"{user.first_name} {user.last_name}",  # or handler name
                    "city": user.city,
                    "distance_km": round(dist, 2),
                    "team_id": team.team_id,
                    "dog_id": team.dog_id,
                })

    return sorted(results, key=lambda x: x["distance_km"])
