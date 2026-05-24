from sqlalchemy.orm import Session
from app.models.handler import Handler

def get_or_create_handler_for_user(db: Session, user_id: int) -> Handler:
    h = db.query(Handler).filter(Handler.user_id == user_id).first()
    if h:
        return h

    h = Handler(user_id=user_id, status="active")  # adjust fields as needed
    db.add(h)
    db.commit()
    db.refresh(h)
    return h
