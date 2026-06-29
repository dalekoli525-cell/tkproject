"""Pydantic schemas shared by the API and workers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from APP.SHARED.constants import TASK_MODE_HASHTAG
from APP.SHARED.constants import TASK_MODE_RECOMMEND


class ProxyNode(BaseModel):
    name: str = Field(min_length=1)
    provider: str = "clash-verge"
    remark: str = ""


class BrowserEnvironment(BaseModel):
    code: str = Field(min_length=1, examples=["001"])
    name: str = Field(min_length=1, examples=["TikTok-MY-001"])
    proxy_node: str = Field(min_length=1, examples=["Residential-1"])
    local_proxy_port: int = Field(ge=1024, le=65535)
    profile_dir: Path
    tiktok_username: str = ""
    tiktok_password: str = ""
    status: str = "NEW"
    task_mode: str = TASK_MODE_RECOMMEND
    tag_class: str = "A类"

    @property
    def proxy_group_name(self) -> str:
        return f"ENV_{self.code}_PROXY".replace("-", "_").upper()

    @property
    def listener_name(self) -> str:
        return f"env-{self.code}".lower()


class BrowserEnvironmentPublic(BaseModel):
    code: str
    name: str
    proxy_node: str
    local_proxy_port: int
    profile_dir: Path
    tiktok_username: str = ""
    status: str = "NEW"
    task_mode: str = TASK_MODE_RECOMMEND
    tag_class: str = "A类"


class CollectTaskConfig(BaseModel):
    task_id: str
    environment_code: str
    mode: Literal[TASK_MODE_RECOMMEND, TASK_MODE_HASHTAG]
    hashtags: list[str] = Field(default_factory=list)
    render_wait_seconds: int = Field(default=30, ge=5, le=180)
    max_videos: int = Field(
        default=0,
        ge=0,
        le=100000,
        description="0 means keep collecting until the task or browser is stopped.",
    )
    max_comments_per_video: int = Field(
        default=0,
        ge=0,
        le=100000,
        description="0 means collect every comment user reachable in the comment panel.",
    )
    skip_zero_comment_video: bool = True
    ai_video_filter_enabled: bool = True
    ai_user_filter_enabled: bool = True


class CollectedCommentUser(BaseModel):
    tiktok_id: str
    nickname: str = ""
    comment_text: str = ""
    source_video_id: str = ""
    source_tag: str = ""
    collected_by_environment: str = ""
