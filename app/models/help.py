from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.database import Base

class HelpSection(Base):
    __tablename__ = "help_sections"

    section_id = Column(Integer, primary_key=True, index=True)
    title = Column(String(150), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    items = relationship("HelpItem", back_populates="section")


class HelpItem(Base):
    __tablename__ = "help_items"

    help_id = Column(Integer, primary_key=True, index=True)
    section_id = Column(Integer, ForeignKey("help_sections.section_id"), nullable=False)
    slug = Column(String(120), nullable=False, unique=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    markdown_md = Column(Text)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    section = relationship("HelpSection", back_populates="items")
    videos = relationship(
        "HelpItemVideo",
        back_populates="help_item",
        cascade="all, delete-orphan",
    )


class HelpItemVideo(Base):
    __tablename__ = "help_item_videos"

    video_id = Column(Integer, primary_key=True, index=True)
    help_id = Column(Integer, ForeignKey("help_items.help_id"), nullable=False)
    video_key = Column(String(150), nullable=False)
    label = Column(String(200))
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    help_item = relationship("HelpItem", back_populates="videos")