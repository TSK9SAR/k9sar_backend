from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class StoredFile(Base):
    __tablename__ = "stored_files"

    file_id = Column(BigInteger, primary_key=True, autoincrement=True)

    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False, unique=True)

    mime_type = Column(String(150), nullable=True)
    file_size = Column(BigInteger, nullable=False)

    sha256_hash = Column(String(64), nullable=False, index=True)

    # Relative to the configured storage root, NOT an absolute path.
    storage_path = Column(String(500), nullable=False, unique=True)

    uploaded_by_user_id = Column(
        Integer,
        ForeignKey("users.user_id"),
        nullable=False,
        index=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )


class ForumPostAttachment(Base):
    __tablename__ = "forum_post_attachments"

    attachment_id = Column(BigInteger, primary_key=True, autoincrement=True)

    post_id = Column(
        Integer,
        ForeignKey("forum_posts.post_id"),
        nullable=False,
        index=True,
    )

    file_id = Column(
        BigInteger,
        ForeignKey("stored_files.file_id"),
        nullable=False,
        index=True,
    )

    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "post_id",
            "file_id",
            name="uq_forum_post_attachment_file",
        ),
    )


class EmailCampaignAttachment(Base):
    __tablename__ = "email_campaign_attachments"

    attachment_id = Column(BigInteger, primary_key=True, autoincrement=True)

    campaign_id = Column(
        BigInteger,
        ForeignKey("email_campaigns.campaign_id"),
        nullable=False,
        index=True,
    )

    file_id = Column(
        BigInteger,
        ForeignKey("stored_files.file_id"),
        nullable=False,
        index=True,
    )

    delivery_mode = Column(
        String(20),
        nullable=False,
        default="attachment",
    )
    # Future values:
    # attachment
    # link

    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "file_id",
            name="uq_email_campaign_attachment_file",
        ),
    )