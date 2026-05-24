from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.database import Base

class AppSetting(Base):
    __tablename__ = "app_settings"

    setting_key = Column(String(100), primary_key=True)
    setting_value = Column(String(255), nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
