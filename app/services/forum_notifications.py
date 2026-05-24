from app.models.forum import ForumCategory, ForumUserSetting
from app.models.user import User
from app.models.role import Role
from app.services.mailer import send_email  # adjust to your actual mailer function
from app.database import SessionLocal
from app.models.forum import ForumTopic, ForumPost

def _full_name(user: User) -> str:
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    name = f"{first} {last}".strip()
    return name or getattr(user, "email", "Someone")


def _excerpt(text: str, limit: int = 500) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _user_role_names(user: User) -> set[str]:
    return {r.role_name for r in getattr(user, "roles", [])}


def _category_allows_user(category: ForumCategory, user: User) -> bool:
    roles = _user_role_names(user)

    if "admin" in roles:
        return True

    required = category.min_role

    if required == "member":
        return True

    if required == "evaluator":
        return bool({"evaluator", "supervisor"} & roles)

    if required == "supervisor":
        return "supervisor" in roles

    if required == "admin":
        return False

    return False


def _wants_email(db, user: User, category: ForumCategory, topic_type: str) -> bool:
    setting = (
        db.query(ForumUserSetting)
        .filter(ForumUserSetting.user_id == user.user_id)
        .first()
    )

    mode = setting.email_mode if setting else "category_default"

    if mode == "none":
        return False

    if mode == "all":
        return True

    if mode == "announcements":
        return topic_type == "announcement"

    # category_default
    notify_default = category.notify_default or "none"

    if notify_default == "none":
        return False

    if notify_default == "all":
        return True

    if notify_default == "announcements":
        return topic_type == "announcement"

    return False


def send_new_topic_notifications(
    *,
    category_id: int,
    topic_id: int,
    post_id: int,
    author_user_id: int,
    public_base_url: str,
):
    db = SessionLocal()
    try:
        category = db.query(ForumCategory).filter(
            ForumCategory.category_id == category_id
        ).first()

        topic = db.query(ForumTopic).filter(
            ForumTopic.topic_id == topic_id
        ).first()

        post = db.query(ForumPost).filter(
            ForumPost.post_id == post_id
        ).first()

        author = db.query(User).filter(
            User.user_id == author_user_id
        ).first()

        if not category or not topic or not post or not author:
            print("FORUM EMAIL skipped: missing category/topic/post/author", flush=True)
            return

        _send_forum_notifications(
            db=db,
            category=category,
            topic=topic,
            post=post,
            author=author,
            public_base_url=public_base_url,
            kind="topic",
        )

    finally:
        db.close()

def send_new_reply_notifications(
    *,
    category_id: int,
    topic_id: int,
    post_id: int,
    author_user_id: int,
    public_base_url: str,
):
    db = SessionLocal()
    try:
        category = db.query(ForumCategory).filter(
            ForumCategory.category_id == category_id
        ).first()

        topic = db.query(ForumTopic).filter(
            ForumTopic.topic_id == topic_id
        ).first()

        post = db.query(ForumPost).filter(
            ForumPost.post_id == post_id
        ).first()

        author = db.query(User).filter(
            User.user_id == author_user_id
        ).first()

        if not category or not topic or not post or not author:
            print("FORUM EMAIL skipped: missing category/topic/post/author", flush=True)
            return

        _send_forum_notifications(
            db=db,
            category=category,
            topic=topic,
            post=post,
            author=author,
            public_base_url=public_base_url,
            kind="reply",
        )

    finally:
        db.close()

def _send_forum_notifications(
    *,
    db,
    category: ForumCategory,
    topic: ForumTopic,
    post: ForumPost,
    author: User,
    public_base_url: str,
    kind: str,  # "topic" or "reply"
):
    users = db.query(User).filter(User.is_active == True).all()

    topic_url = (
        f"{public_base_url.rstrip('/')}/login"
        f"?next=/forums/topics/{topic.topic_id}"
    )

    if kind == "reply":
        subject = f"[TSK9SAR Forum] Reply: {topic.title}"
        action_text = "replied"
    else:
        subject = f"[TSK9SAR Forum] New Topic: {topic.title}"
        action_text = "posted"

    author_name = _full_name(author)

    body = f"""\
{author_name} {action_text} in {category.name}:

{_excerpt(post.body_md)}

Open topic:
{topic_url}
"""

    for user in users:
        if user.user_id == author.user_id:
            continue

        if not getattr(user, "email", None):
            continue

        if not _category_allows_user(category, user):
            continue

        if not _wants_email(db, user, category, topic.topic_type):
            continue

        try:
            print(f"FORUM EMAIL sending to {user.email}: {subject}", flush=True)

            ok = send_email(
                to_email=user.email,
                subject=subject,
                text_body=body,
                html_body=None,
                reply_to=None,
            )
            
            if ok:
                print(f"FORUM EMAIL sent to {user.email}", flush=True)
            else:
                print(f"FORUM EMAIL returned False for {user.email}", flush=True)

        except Exception as e:
            print(
                f"FORUM EMAIL FAILED to {user.email}: {type(e).__name__}: {e}",
                flush=True,
            )