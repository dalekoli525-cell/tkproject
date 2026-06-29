# -*- coding: utf-8 -*-

"""AI-ready profile filtering for collected TikTok users."""

from __future__ import annotations

import re
from dataclasses import dataclass


CHINESE_NAME_HINTS = {
    "chen",
    "tan",
    "lim",
    "lee",
    "wong",
    "ng",
    "ong",
    "teoh",
    "low",
    "chong",
    "zhang",
    "wang",
    "li",
    "liu",
}
MARKET_SIGNAL_HINTS = {
    "malaysia",
    "my",
    "kl",
    "shop",
    "business",
    "老板",
    "创业",
    "大马",
    "马来西亚",
    "华人",
    "中文",
}
VIDEO_SIGNAL_HINTS = {
    "大马",
    "马来西亚",
    "华人",
    "华侨",
    "中文",
    "kl",
    "malaysia",
    "chinese",
    "business",
    "shop",
}


@dataclass(frozen=True)
class ProfileDecision:
    decision: str
    score: int
    reason: str


@dataclass(frozen=True)
class VideoDecision:
    decision: str
    score: int
    reason: str


class VideoFilter:
    """Local video relevance filter; replace with server AI when available."""

    def decide(
        self,
        description: str,
        tags: list[str] | None = None,
        allowed_tags: list[str] | None = None,
        blocked_tags: list[str] | None = None,
    ) -> VideoDecision:
        tags = tags or []
        allowed_tags = allowed_tags or []
        blocked_tags = blocked_tags or []
        tag_set = set(tags)
        allowed_set = set(allowed_tags)
        blocked_set = set(blocked_tags)
        text = f"{description} {' '.join(tags)}".strip()
        lower_text = text.lower()
        score = 0
        reasons: list[str] = []

        if blocked_set and tag_set.intersection(blocked_set):
            return VideoDecision(
                decision="UNQUALIFIED",
                score=0,
                reason=f"blocked_tag:{','.join(sorted(tag_set.intersection(blocked_set)))}",
            )

        if allowed_set and tag_set.intersection(allowed_set):
            score += 45
            reasons.append("allowed_tag_match")

        if re.search(r"[\u4e00-\u9fff]", text):
            score += 35
            reasons.append("contains_chinese")

        if any(hint in lower_text for hint in VIDEO_SIGNAL_HINTS):
            score += 25
            reasons.append("market_signal_hint")

        if score >= 55:
            decision = "QUALIFIED"
        elif score >= 30:
            decision = "REVIEW"
        else:
            decision = "UNQUALIFIED"

        return VideoDecision(
            decision=decision,
            score=min(score, 100),
            reason=",".join(reasons) or "no_signal",
        )


class ProfileFilter:
    """Local heuristic filter; replace provider later with server AI."""

    def decide(self, tiktok_id: str, nickname: str = "", bio: str = "") -> ProfileDecision:
        text = f"{tiktok_id} {nickname} {bio}".strip()
        lower_text = text.lower()
        score = 0
        reasons: list[str] = []

        if re.search(r"[\u4e00-\u9fff]", text):
            score += 45
            reasons.append("contains_chinese")

        if any(hint in lower_text for hint in CHINESE_NAME_HINTS):
            score += 30
            reasons.append("chinese_name_hint")

        if any(hint in lower_text for hint in MARKET_SIGNAL_HINTS):
            score += 15
            reasons.append("market_signal_hint")

        if score >= 60:
            decision = "QUALIFIED"
        elif score >= 30:
            decision = "REVIEW"
        else:
            decision = "UNQUALIFIED"

        return ProfileDecision(
            decision=decision,
            score=min(score, 100),
            reason=",".join(reasons) or "no_signal",
        )
