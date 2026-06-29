# -*- coding: utf-8 -*-

"""TikTok page automation for recommendation and hashtag collection."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from APP.SHARED.constants import TASK_MODE_HASHTAG
from APP.SHARED.constants import TASK_MODE_RECOMMEND
from APP.WORKER.AI.Profile_Filter import ProfileFilter
from APP.WORKER.AI.Profile_Filter import VideoFilter
from APP.WORKER.TIKTOK.Local_Store import LocalCollectionStore


LogHandler = Callable[[str], None]
ControlStatusHandler = Callable[[], str]


@dataclass
class CollectResult:
    videos_seen: int = 0
    users_saved: int = 0
    skipped_videos: int = 0
    stopped: bool = False
    stop_reason: str = ""


class TikTokCollector:
    """Run one collection task inside an already-open environment page."""

    COMMENT_BUTTON_SELECTORS = [
        "[data-e2e='comment-icon']",
        "button[aria-label*='comment' i]",
        "button[aria-label*='komen' i]",
        "xpath=//*[name()='svg' and contains(@data-e2e, 'comment')]/ancestor::button[1]",
    ]
    NEXT_VIDEO_SELECTORS = [
        "button[aria-label*='next' i]",
        "button[aria-label*='berikut' i]",
        "xpath=//button[contains(., '↓') or contains(., 'Next')]",
    ]
    COMMENT_CONTAINER_SELECTORS = [
        "[data-e2e='comment-list']",
        "[class*='CommentList']",
        "div[role='dialog']",
    ]
    COMMENT_ITEM_SELECTORS = [
        "[data-e2e='comment-level-1']",
        "[class*='CommentItem']",
        "div:has(a[href*='/@'])",
    ]
    SEARCH_INPUT_SELECTORS = [
        "input[data-e2e='search-user-input']",
        "input[placeholder*='Search' i]",
        "input[placeholder*='Cari' i]",
        "input[type='search']",
        "input",
    ]
    VIDEO_TAB_SELECTORS = [
        "[data-e2e='search-tabs'] a:has-text('Video')",
        "a:has-text('Video')",
        "button:has-text('Video')",
        "a:has-text('视频')",
        "button:has-text('视频')",
    ]

    def __init__(
        self,
        page,
        store: LocalCollectionStore,
        task: dict,
        log: LogHandler | None = None,
        control_status: ControlStatusHandler | None = None,
    ):
        self.page = page
        self.store = store
        self.task = task
        self.log_handler = log or (lambda message: None)
        self.control_status_handler = control_status or (lambda: "")
        self.profile_filter = ProfileFilter()
        self.video_filter = VideoFilter()
        self.active_tag = ""

    def log(self, message: str) -> None:
        self.log_handler(message)
        self.store.log(
            self.task_code,
            self.environment_code,
            "INFO",
            message,
        )

    @property
    def task_code(self) -> str:
        return str(self.task.get("task_code", "LOCAL-TASK"))

    @property
    def environment_code(self) -> str:
        return str(self.task.get("environment_code", ""))

    def run(self) -> CollectResult:
        mode = str(self.task.get("mode", TASK_MODE_RECOMMEND))
        max_videos = int(self.task.get("max_videos") or 0)
        render_wait = max(5, int(self.task.get("render_wait_seconds", 30)))
        result = CollectResult()
        max_videos_label = '持续采集' if max_videos <= 0 else str(max_videos)

        self.log(f"任务开始：mode={mode}, max_videos={max_videos_label}")
        if mode == TASK_MODE_HASHTAG:
            self._run_hashtag_queue(result, max_videos, render_wait)
        else:
            self._open_entry(TASK_MODE_RECOMMEND, render_wait)
            self._collect_video_stream(
                result=result,
                mode=TASK_MODE_RECOMMEND,
                max_videos=max_videos,
                stop_at_end=False,
            )

        if result.stopped:
            self.log(
                f"任务已暂停：视频 {result.videos_seen}，新增用户 {result.users_saved}，原因 {result.stop_reason}"
            )
        else:
            self.log(
                f"任务完成：视频 {result.videos_seen}，新增用户 {result.users_saved}，跳过 {result.skipped_videos}"
            )
        return result

    def _run_hashtag_queue(
        self,
        result: CollectResult,
        max_videos: int,
        render_wait: int,
    ) -> None:
        hashtags = self.task.get("hashtags") or []
        normalized_tags = [
            str(tag).strip()
            for tag in hashtags
            if str(tag).strip()
        ]
        if not normalized_tags:
            self.log("标签模式没有可用标签，任务结束")
            return

        for tag in normalized_tags:
            if self._mark_stopped_if_requested(result):
                return
            self.active_tag = tag
            self.log(f"开始采集标签：{tag}")
            self._open_hashtag_entry(tag, render_wait)
            self._collect_video_stream(
                result=result,
                mode=TASK_MODE_HASHTAG,
                max_videos=max_videos,
                stop_at_end=True,
            )
            if result.stopped:
                return
            self.log(f"标签完成：{tag}")

        self.active_tag = ""

    def _collect_video_stream(
        self,
        result: CollectResult,
        mode: str,
        max_videos: int,
        stop_at_end: bool,
    ) -> None:
        max_videos_label = "持续采集" if max_videos <= 0 else str(max_videos)
        processed_keys: set[str] = set()
        local_index = 0
        stagnant_rounds = 0
        stagnant_limit = 4 if stop_at_end else 12

        while max_videos <= 0 or local_index < max_videos:
            if self._mark_stopped_if_requested(result):
                return

            self.page.wait_for_timeout(900)
            video = self._read_video_meta(mode)
            video_key = self._video_key(video)

            if video_key in processed_keys:
                stagnant_rounds += 1
                if stop_at_end and stagnant_rounds >= stagnant_limit:
                    self.log("当前标签没有新视频，准备切换下一个标签")
                    return
                if not self._next_video(video_key):
                    self.page.wait_for_timeout(1500)
                continue

            stagnant_rounds = 0
            processed_keys.add(video_key)

            if not self._video_matches_rules(video, mode):
                result.skipped_videos += 1
                local_index += 1
                if not self._next_video(video_key) and stop_at_end:
                    stagnant_rounds += 1
                continue

            self.store.save_video(video)
            users = self._collect_comment_users(video, result)
            saved = self.store.save_users(users)

            result.videos_seen += 1
            result.users_saved += saved
            local_index += 1
            self.log(
                f"视频 {local_index}/{max_videos_label} 完成：采集用户 {len(users)}，新增 {saved}"
            )

            if self._mark_stopped_if_requested(result):
                return
            if not self._next_video(video_key):
                stagnant_rounds += 1
                if stop_at_end and stagnant_rounds >= stagnant_limit:
                    self.log("当前标签已到可见视频底部")
                    return

    def _open_entry(self, mode: str, render_wait: int) -> None:
        if mode == TASK_MODE_HASHTAG:
            hashtags = self.task.get("hashtags") or []
            keyword = str(hashtags[0]).lstrip("#") if hashtags else ""
            self._open_hashtag_entry(keyword, render_wait)
        else:
            self.page.goto("https://www.tiktok.com/foryou?lang=ms-MY", wait_until="domcontentloaded")
            self.page.wait_for_timeout(render_wait * 1000)

    def _open_hashtag_entry(self, tag: str, render_wait: int) -> None:
        keyword = str(tag).lstrip("#")
        self.page.goto("https://www.tiktok.com", wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(render_wait * 1000)
        if keyword and self._search_keyword(keyword):
            self._click_video_tab()
        elif keyword:
            self.log("未能通过搜索框输入标签，使用搜索 URL 作为兜底入口")
            self.page.goto(
                f"https://www.tiktok.com/search/video?q={keyword}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            self.page.wait_for_timeout(2500)
        self._open_first_search_video()

    def _search_keyword(self, keyword: str) -> bool:
        for selector in self.SEARCH_INPUT_SELECTORS:
            try:
                search_input = self.page.locator(selector).first
                search_input.wait_for(state="visible", timeout=6000)
                search_input.click(timeout=3000)
                search_input.fill(keyword, timeout=5000)
                self.page.keyboard.press("Enter")
                self.page.wait_for_timeout(3500)
                self.log(f"已通过搜索框搜索标签：#{keyword}")
                return True
            except Exception:
                continue
        return False

    def _click_video_tab(self) -> None:
        for selector in self.VIDEO_TAB_SELECTORS:
            try:
                tab = self.page.locator(selector).first
                tab.wait_for(state="visible", timeout=5000)
                tab.click(timeout=5000)
                self.page.wait_for_timeout(2000)
                self.log("已切换到搜索结果的视频列表")
                return
            except Exception:
                continue
        self.log("未找到视频 Tab，继续使用当前搜索结果")

    def _open_first_search_video(self) -> None:
        candidates = [
            "a[href*='/video/']",
            "[data-e2e='search_top-item'] a",
            "div[data-e2e='search_video-item'] a",
        ]
        for selector in candidates:
            try:
                item = self.page.locator(selector).first
                item.wait_for(state="visible", timeout=8000)
                item.click(timeout=8000)
                self.page.wait_for_timeout(2500)
                return
            except Exception:
                continue
        self.log("标签搜索页未找到可点击视频，保留当前页面继续尝试")

    def _read_video_meta(self, mode: str) -> dict:
        url = self.page.url
        video_id = self._video_id_from_url(url)
        text = self._safe_page_text()
        tags = sorted(set(re.findall(r"#[\w\u4e00-\u9fff]+", text)))
        comment_count = self._extract_near_button_count(self.COMMENT_BUTTON_SELECTORS)

        return {
            "task_code": self.task_code,
            "environment_code": self.environment_code,
            "video_id": video_id or url,
            "url": url,
            "description": text[:1200],
            "tags": tags,
            "comment_count": comment_count,
            "source_mode": mode,
            "source_tag": self.active_tag or ",".join(self.task.get("hashtags") or []),
        }

    @staticmethod
    def _video_key(video: dict) -> str:
        video_id = str(video.get("video_id", "")).strip()
        if video_id:
            return video_id
        return f"{video.get('url', '')}|{str(video.get('description', ''))[:180]}"

    @staticmethod
    def _video_id_from_url(url: str) -> str:
        match = re.search(r"/video/(\d+)", url)
        return match.group(1) if match else ""

    def _safe_page_text(self) -> str:
        try:
            return self.page.locator("body").inner_text(timeout=4000)
        except Exception:
            return ""

    def _extract_near_button_count(self, selectors: list[str]) -> int:
        for selector in selectors:
            try:
                text = self.page.locator(selector).first.locator("xpath=..").inner_text(timeout=1500)
                value = self._parse_count(text)
                if value >= 0:
                    return value
            except Exception:
                continue
        return -1

    @staticmethod
    def _parse_count(text: str) -> int:
        matches = re.findall(r"(\d+(?:\.\d+)?)([KkMm万]?)", text.replace(",", ""))
        if not matches:
            return -1
        number, suffix = matches[-1]
        value = float(number)
        if suffix.lower() == "k":
            value *= 1000
        elif suffix.lower() == "m":
            value *= 1000000
        elif suffix == "万":
            value *= 10000
        return int(value)

    def _video_matches_rules(self, video: dict, mode: str) -> bool:
        if self.task.get("skip_zero_comment_video", True) and video.get("comment_count") == 0:
            self.log("跳过零评论视频")
            return False

        blocked_tags = set(self.task.get("blocked_tags") or [])
        tags = set(video.get("tags") or [])
        if blocked_tags and tags.intersection(blocked_tags):
            self.log(f"跳过黑名单标签视频：{sorted(tags.intersection(blocked_tags))}")
            return False

        allow_tags = set(self.task.get("hashtags") or []) if mode == TASK_MODE_HASHTAG else set()
        if allow_tags and not tags.intersection(allow_tags):
            self.log("跳过未命中指定标签的视频")
            return False

        decision = self.video_filter.decide(
            description=str(video.get("description", "")),
            tags=list(video.get("tags") or []),
            allowed_tags=list(allow_tags),
            blocked_tags=list(self.task.get("blocked_tags") or []),
        )
        video["ai_decision"] = decision.decision
        video["ai_score"] = decision.score
        video["ai_reason"] = decision.reason
        if (
            self.task.get("ai_video_filter_enabled", True)
            and decision.decision == "UNQUALIFIED"
        ):
            self.log(f"跳过 AI 视频判断未达标：{decision.reason}")
            return False

        return True

    def _collect_comment_users(self, video: dict, result: CollectResult) -> list[dict]:
        max_comments = int(self.task.get("max_comments_per_video") or 0)
        if not self._open_comments():
            return []

        users: dict[str, dict] = {}
        stable_rounds = 0
        max_stable_rounds = 8 if max_comments <= 0 else 4
        previous_scroll_state = None

        while (max_comments <= 0 or len(users) < max_comments) and stable_rounds < max_stable_rounds:
            if self._mark_stopped_if_requested(result):
                break
            before = len(users)
            for user in self._visible_comment_users(video):
                users.setdefault(user["tiktok_id"], user)
                if max_comments > 0 and len(users) >= max_comments:
                    break

            scroll_state = self._comment_scroll_state()
            if len(users) == before and scroll_state == previous_scroll_state:
                stable_rounds += 1
            else:
                stable_rounds = 0

            self._scroll_comments()
            previous_scroll_state = self._comment_scroll_state()
            time.sleep(0.35)

        self._close_comments_if_needed()
        if max_comments > 0:
            return list(users.values())[:max_comments]
        return list(users.values())

    def _open_comments(self) -> bool:
        for selector in self.COMMENT_BUTTON_SELECTORS:
            try:
                button = self.page.locator(selector).first
                button.wait_for(state="visible", timeout=5000)
                button.click(timeout=5000)
                self.page.wait_for_timeout(1800)
                return True
            except Exception:
                continue
        self.log("未找到评论按钮")
        return False

    def _visible_comment_users(self, video: dict) -> list[dict]:
        users: list[dict] = []
        for selector in self.COMMENT_ITEM_SELECTORS:
            try:
                items = self.page.locator(selector)
                count = min(items.count(), 500)
            except Exception:
                continue

            for index in range(count):
                try:
                    item = items.nth(index)
                    link = item.locator("a[href*='/@']").first
                    href = link.get_attribute("href", timeout=1000) or ""
                    tiktok_id = self._user_id_from_href(href)
                    if not tiktok_id:
                        continue
                    nickname = link.inner_text(timeout=1000).strip()
                    comment_text = item.inner_text(timeout=1000)[:800]
                    decision = self.profile_filter.decide(
                        tiktok_id=tiktok_id,
                        nickname=nickname,
                        bio=comment_text,
                    )
                    if (
                        self.task.get("ai_user_filter_enabled", True)
                        and decision.decision == "UNQUALIFIED"
                    ):
                        continue
                    users.append(
                        {
                            "task_code": self.task_code,
                            "environment_code": self.environment_code,
                            "tiktok_id": tiktok_id,
                            "nickname": nickname,
                            "comment_text": comment_text,
                            "source_video_id": video.get("video_id", ""),
                            "source_tag": video.get("source_tag", ""),
                            "ai_decision": decision.decision,
                            "ai_score": decision.score,
                            "ai_reason": decision.reason,
                        }
                    )
                except Exception:
                    continue
            if users:
                return users
        return users

    @staticmethod
    def _user_id_from_href(href: str) -> str:
        match = re.search(r"/@([^/?#]+)", href)
        return match.group(1) if match else ""

    def _comment_scroll_state(self):
        for selector in self.COMMENT_CONTAINER_SELECTORS:
            try:
                container = self.page.locator(selector).first
                return container.evaluate(
                    "(el) => [Math.round(el.scrollTop), Math.round(el.scrollHeight), Math.round(el.clientHeight)]",
                    timeout=1500,
                )
            except Exception:
                continue
        return None

    def _scroll_comments(self) -> None:
        for selector in self.COMMENT_CONTAINER_SELECTORS:
            try:
                container = self.page.locator(selector).first
                container.evaluate("(el) => { el.scrollTop = el.scrollHeight; }", timeout=1500)
                return
            except Exception:
                continue
        self.page.mouse.wheel(0, 900)

    def _close_comments_if_needed(self) -> None:
        for selector in [
            "button[aria-label*='close' i]",
            "button[aria-label*='tutup' i]",
            "button[data-e2e='browse-close']",
        ]:
            try:
                self.page.locator(selector).first.click(timeout=1000)
                self.page.wait_for_timeout(500)
                return
            except Exception:
                continue

    def _next_video(self, before_key: str = "") -> bool:
        for selector in self.NEXT_VIDEO_SELECTORS:
            try:
                button = self.page.locator(selector).first
                button.click(timeout=1800)
                self.page.wait_for_timeout(1800)
                return self._wait_for_video_change(before_key)
            except Exception:
                continue
        self.page.keyboard.press("ArrowDown")
        self.page.wait_for_timeout(1800)
        return self._wait_for_video_change(before_key)

    def _wait_for_video_change(self, before_key: str) -> bool:
        if not before_key:
            return True
        for _ in range(5):
            try:
                current = self._read_video_meta(str(self.task.get("mode", TASK_MODE_RECOMMEND)))
                if self._video_key(current) != before_key:
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(500)
        return False

    def _control_status(self) -> str:
        try:
            return str(self.control_status_handler() or "").upper()
        except Exception:
            return ""

    def _mark_stopped_if_requested(self, result: CollectResult) -> bool:
        status = self._control_status()
        if status in {"PAUSE_REQUESTED", "STOP_REQUESTED", "CANCEL_REQUESTED"}:
            result.stopped = True
            result.stop_reason = status
            return True
        return False

