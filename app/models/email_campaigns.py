# app/models/email_campaigns.py

from sqlalchemy import Column, BigInteger, Integer, String, Text, DateTime, Enum, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"

    campaign_id = Column(BigInteger, primary_key=True, autoincrement=True)
    sent_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    enable_reply: bool = False
    subject = Column(String(255), nullable=False)
    body_text = Column(Text, nullable=False)
    filter_json = Column(JSON, nullable=False)
    recipient_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    sent_at = Column(DateTime, nullable=True)

    status = Column(
        Enum("draft", "sending", "sent", "partial_failed", "failed"),
        nullable=False,
        default="draft",
    )

    error_text = Column(Text, nullable=True)


class EmailCampaignRecipient(Base):
    __tablename__ = "email_campaign_recipients"

    campaign_recipient_id = Column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id = Column(BigInteger, ForeignKey("email_campaigns.campaign_id", ondelete="CASCADE"), nullable=False)

    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)

    email = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)

    status = Column(
        Enum("pending", "sent", "failed", "skipped"),
        nullable=False,
        default="pending",
    )

    error_text = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    