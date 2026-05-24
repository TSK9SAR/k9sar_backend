import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, Boolean, func
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base



class ForumCategory(Base):
    __tablename__ = "forum_categories"

    category_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(120), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    sortorder = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    min_role = Column(String(50), nullable=False, default="member")
    notify_default = Column(
        Enum("all", "announcements", "none"),
        nullable=False,
        default="none",
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    topics = relationship("ForumTopic", back_populates="category")


class ForumTopic(Base):
    __tablename__ = "forum_topics"

    topic_id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("forum_categories.category_id"), nullable=False)
    title = Column(String(200), nullable=False)

    topic_type = Column(
        Enum("general", "standard", "search", "event", "website", "announcement"),
        nullable=False,
        default="general",
    )

    related_standard_id = Column(Integer, nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    is_pinned = Column(Boolean, nullable=False, default=False)
    is_locked = Column(Boolean, nullable=False, default=False)

    last_post_at = Column(DateTime, server_default=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    category = relationship("ForumCategory", back_populates="topics")
    posts = relationship("ForumPost", back_populates="topic", cascade="all, delete-orphan")


class ForumPost(Base):
    __tablename__ = "forum_posts"

    post_id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("forum_topics.topic_id"), nullable=False)
    body_md = Column(Text, nullable=False)
    post_type = Column(String(40), nullable=False, default="comment")
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)

    edited_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    sort_order = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    topic = relationship("ForumTopic", back_populates="posts")

    created_by = relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )


class ForumUserSetting(Base):
    __tablename__ = "forum_user_settings"

    user_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)

    email_mode = Column(
        Enum("category_default", "all", "announcements", "none"),
        nullable=False,
        default="category_default",
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class ForumTopicRead(Base):
    __tablename__ = "forum_topic_reads"

    user_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)
    topic_id = Column(Integer, ForeignKey("forum_topics.topic_id"), primary_key=True)

    last_read_at = Column(DateTime, server_default=func.now(), nullable=False)

class ForumBallot(Base):
    __tablename__ = "forum_ballots"

    ballot_id = Column(Integer, primary_key=True, autoincrement=True)
    topic_id = Column(Integer, ForeignKey("forum_topics.topic_id"), nullable=False)
    post_id = Column(Integer, ForeignKey("forum_posts.post_id"), nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    title = Column(String(255), nullable=False)
    description_md = Column(Text, nullable=True)

    ballot_type = Column(String(40), nullable=False, default="poll")

    opens_at = Column(DateTime, nullable=True)
    closes_at = Column(DateTime, nullable=True)

    allow_vote_changes = Column(Boolean, nullable=False, default=True)
    show_live_results = Column(Boolean, nullable=False, default=True)
    max_choices_per_vote = Column(Integer, nullable=False, default=1)
    show_results_before_vote = Column(Boolean, nullable=False, default=True)

    status = Column(String(40), nullable=False, default="open")

    # NEW

    is_required = Column(Boolean, nullable=False, default=True)
    is_test = Column(Boolean, nullable=False, default=False)

    archived_at = Column(DateTime, nullable=True)

    display_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now(), nullable=True)

    choices = relationship(
        "ForumBallotChoice",
        cascade="all, delete-orphan",
        back_populates="ballot",
        order_by="ForumBallotChoice.sort_order",
    )

    votes = relationship(
        "ForumBallotVote",
        cascade="all, delete-orphan",
        back_populates="ballot",
    )


class ForumBallotChoice(Base):
    __tablename__ = "forum_ballot_choices"

    choice_id = Column(Integer, primary_key=True, autoincrement=True)
    ballot_id = Column(Integer, ForeignKey("forum_ballots.ballot_id"), nullable=False)
    allows_free_text = Column(Boolean, nullable=False, default=False)
    free_text_label = Column(String(255), nullable=True)
    label = Column(String(255), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    ballot = relationship("ForumBallot", back_populates="choices")
    votes = relationship("ForumBallotVote", back_populates="choice")


class ForumBallotVote(Base):
    __tablename__ = "forum_ballot_votes"

    vote_id = Column(Integer, primary_key=True, autoincrement=True)

    ballot_id = Column(
        Integer,
        ForeignKey("forum_ballots.ballot_id"),
        nullable=False,
    )

    choice_id = Column(
        Integer,
        ForeignKey("forum_ballot_choices.choice_id"),
        nullable=False,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.user_id"),
        nullable=False,
    )

    voted_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    ballot = relationship("ForumBallot", back_populates="votes")
    choice = relationship("ForumBallotChoice", back_populates="votes")

class ForumBallotFeedback(Base):
    __tablename__ = "forum_ballot_feedback"

    feedback_id = Column(Integer, primary_key=True, autoincrement=True)
    ballot_id = Column(Integer, ForeignKey("forum_ballots.ballot_id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    choice_id = Column(Integer, ForeignKey("forum_ballot_choices.choice_id"), nullable=True)
    feedback_text = Column(Text, nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now(), nullable=True)

    ballot = relationship("ForumBallot")
    choice = relationship("ForumBallotChoice")