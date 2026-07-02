# -*- coding: utf-8 -*-

"""SQLAlchemy models for the rewritten product baseline."""

from datetime import datetime

from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from APP.SERVER.database import Base


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="operator")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProxyNode(Base):
    __tablename__ = "proxy_nodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(100), default="direct-proxy")
    region: Mapped[str] = mapped_column(String(50), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BrowserEnvironment(Base):
    __tablename__ = "browser_environments"
    __table_args__ = (
        UniqueConstraint("owner_username", "code", name="uq_browser_env_owner_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_username: Mapped[str] = mapped_column(String(100), default="", index=True)
    proxy_node_name: Mapped[str] = mapped_column(String(120), index=True)
    local_proxy_port: Mapped[int] = mapped_column(Integer)
    profile_dir: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50), default="NEW")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class TikTokAccount(Base):
    __tablename__ = "tiktok_accounts"
    __table_args__ = (
        UniqueConstraint("username", name="uq_tiktok_account_username"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    environment_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_ciphertext: Mapped[str] = mapped_column(String(1000), default="")
    assigned_owner_username: Mapped[str] = mapped_column(String(100), default="", index=True)
    nickname: Mapped[str] = mapped_column(String(255), default="")
    login_status: Mapped[str] = mapped_column(String(50), default="UNKNOWN")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CollectTask(Base):
    __tablename__ = "collect_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    environment_code: Mapped[str] = mapped_column(String(50), index=True)
    mode: Mapped[str] = mapped_column(String(50), default="recommend")
    hashtags: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="PENDING")
    max_videos: Mapped[int] = mapped_column(Integer, default=0)
    max_comments_per_video: Mapped[int] = mapped_column(Integer, default=0)
    render_wait_seconds: Mapped[int] = mapped_column(Integer, default=30)
    skip_zero_comment_video: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_video_filter_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_user_filter_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TikTokVideo(Base):
    __tablename__ = "tiktok_videos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    author_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")
    like_count: Mapped[int] = mapped_column(BigInteger, default=0)
    comment_count: Mapped[int] = mapped_column(BigInteger, default=0)
    collect_count: Mapped[int] = mapped_column(BigInteger, default=0)
    share_count: Mapped[int] = mapped_column(BigInteger, default=0)
    source_mode: Mapped[str] = mapped_column(String(50), default="")
    source_tag: Mapped[str] = mapped_column(String(120), default="")
    ai_decision: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CollectedUser(Base):
    __tablename__ = "collected_users"
    __table_args__ = (
        UniqueConstraint("tiktok_id", "source_video_id", name="uq_user_video"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tiktok_id: Mapped[str] = mapped_column(String(120), index=True)
    nickname: Mapped[str] = mapped_column(String(255), default="")
    comment_text: Mapped[str] = mapped_column(Text, default="")
    source_video_id: Mapped[str] = mapped_column(String(120), index=True)
    source_tag: Mapped[str] = mapped_column(String(120), default="", index=True)
    environment_code: Mapped[str] = mapped_column(String(50), default="", index=True)
    ai_decision: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_code: Mapped[str] = mapped_column(String(100), index=True)
    environment_code: Mapped[str] = mapped_column(String(50), default="", index=True)
    level: Mapped[str] = mapped_column(String(20), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
