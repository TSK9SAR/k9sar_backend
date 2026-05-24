from sqlalchemy import Column, Integer, String, Text, BigInteger, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base

class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    credential_id = Column(String(512), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)

    public_key = Column(Text, nullable=False)
    sign_count = Column(BigInteger, nullable=False, default=0)

    transports = Column(String(255), nullable=True)
    device_name = Column(String(120), nullable=True)
    backed_up = Column(Boolean, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User")