from sqlalchemy import Column, DateTime, Integer, String, JSON, func
from app.database import Base


class AdminCleanupEvent(Base):
    __tablename__ = "admin_cleanup_events"

    cleanup_event_id = Column(Integer, primary_key=True, index=True)

    actor_user_id = Column(Integer, nullable=False, index=True)
    actor_email = Column(String(255), nullable=True)
    actor_name = Column(String(255), nullable=True)

    action = Column(String(80), nullable=False)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(Integer, nullable=True)
    entity_label = Column(String(255), nullable=True)

    deleted_counts_json = Column(JSON, nullable=True)
    affected_ids_json = Column(JSON, nullable=True)
    warnings_json = Column(JSON, nullable=True)

    confirmation_text = Column(String(255), nullable=True)
    request_ip = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())