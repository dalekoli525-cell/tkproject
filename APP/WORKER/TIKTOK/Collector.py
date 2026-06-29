# -*- coding: utf-8 -*-

"""TikTok page automation for recommendation and hashtag collection."""

from __future__ import annotations

import re
import time
from datetime import datetime
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
        "button:has([data-e2e='comment-icon'])",
        "[data-e2e='comment-button']",
        "[data-e2e='comment-icon']",
        "span[data-e2e='comment-icon']",
        "div[data-e2e='comment-icon']",
        "button[aria-label*='comment' i]",
        "button[aria-label*='komen' i]",
        "xpath=//*[contains(translate(@aria-label, 'COMMENTKOMEN', 'commentkomen'), 'comment') or contains(translate(@aria-label, 'COMMENTKOMEN', 'commentkomen'), 'komen')]/ancestor-or-self::button[1]",
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
        self.profile_metric_cache: dict[str, tuple[bool, dict]] = {}
        self.registration_filter_warned = False

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
        enabled_filters = {
            key: value
            for key, value in self._target_filters().items()
            if self._safe_filter_int(value) > 0
        }
        if enabled_filters:
            self.log(f"目标筛选参数已接收：{enabled_filters}")
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
                if stagnant_rounds >= stagnant_limit:
                    if stop_at_end:
                        self.log("当前标签没有新视频，准备切换下一个标签")
                    else:
                        self.log("推荐流连续多次未切换到新视频，结束当前任务以避免卡死")
                    return
                if not self._next_video(video_key):
                    self.page.wait_for_timeout(1500)
                continue

            stagnant_rounds = 0
            processed_keys.add(video_key)

            if not self._video_matches_rules(video, mode):
                result.skipped_videos += 1
                local_index += 1
                if max_videos > 0 and local_index >= max_videos:
                    return
                if not self._next_video(video_key) and stop_at_end:
                    stagnant_rounds += 1
                continue

            self.store.save_video(video)
            users = self._collect_comment_users(video, result)
            if video.get("comment_collect_status") == "NO_COMMENT_BUTTON":
                result.skipped_videos += 1
                local_index += 1
                self.log(f"视频 {local_index}/{max_videos_label} 跳过：未找到评论入口")
                if max_videos > 0 and local_index >= max_videos:
                    return
                if not self._next_video(video_key):
                    stagnant_rounds += 1
                    if stagnant_rounds >= stagnant_limit:
                        if stop_at_end:
                            self.log("当前标签已到可见视频底部")
                        else:
                            self.log("推荐流连续多次未切换到新视频，结束当前任务以避免卡死")
                        return
                continue

            saved = self.store.save_users(users)

            result.videos_seen += 1
            result.users_saved += saved
            local_index += 1
            self.log(
                f"视频 {local_index}/{max_videos_label} 完成：采集用户 {len(users)}，新增 {saved}"
            )

            if self._mark_stopped_if_requested(result):
                return
            if max_videos > 0 and local_index >= max_videos:
                return
            if not self._next_video(video_key):
                stagnant_rounds += 1
                if stagnant_rounds >= stagnant_limit:
                    if stop_at_end:
                        self.log("当前标签已到可见视频底部")
                    else:
                        self.log("推荐流连续多次未切换到新视频，结束当前任务以避免卡死")
                    return

    def _open_entry(self, mode: str, render_wait: int) -> None:
        if mode == TASK_MODE_HASHTAG:
            hashtags = self.task.get("hashtags") or []
            keyword = str(hashtags[0]).lstrip("#") if hashtags else ""
            self._open_hashtag_entry(keyword, render_wait)
        else:
            self._safe_goto(
                "https://www.tiktok.com/foryou?lang=ms-MY",
                "推荐流入口",
                timeout=45000,
            )
            self.page.wait_for_timeout(render_wait * 1000)

    def _open_hashtag_entry(self, tag: str, render_wait: int) -> None:
        keyword = str(tag).lstrip("#")
        self._safe_goto("https://www.tiktok.com", "TikTok 首页", timeout=60000)
        self.page.wait_for_timeout(render_wait * 1000)
        if keyword and self._search_keyword(keyword):
            self._click_video_tab()
        elif keyword:
            self.log("未能通过搜索框输入标签，使用搜索 URL 作为兜底入口")
            self._safe_goto(
                f"https://www.tiktok.com/search/video?q={keyword}",
                f"标签搜索 #{keyword}",
                timeout=60000,
            )
            self.page.wait_for_timeout(2500)
        self._open_first_search_video()

    def _safe_goto(self, url: str, label: str, timeout: int = 45000) -> bool:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except Exception as exc:
            short_error = str(exc).splitlines()[0][:180]
            self.log(f"{label}打开失败，继续使用当前页面：{short_error}")
            return False

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
        description = str(video.get("description", ""))
        playback_error_markers = (
            "Kami menghadapi masalah untuk memainkan video ini",
            "We're having trouble playing this video",
            "Something went wrong",
            "无法播放此视频",
        )
        if any(marker in description for marker in playback_error_markers):
            self.log("跳过播放异常视频")
            return False

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
            video["comment_collect_status"] = "NO_COMMENT_BUTTON"
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
        users: dict[str, dict] = {}
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
                    comment_text = item.inner_text(timeout=1000)[:800]
                    if not self._comment_matches_time_window(comment_text):
                        continue
                    profile_matches, profile_metrics = self._profile_matches_target_filters(tiktok_id)
                    if not profile_matches:
                        continue
                    nickname = self._comment_nickname(
                        link_text=link.inner_text(timeout=1000).strip(),
                        comment_text=comment_text,
                        tiktok_id=tiktok_id,
                    )
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
                    users.setdefault(
                        tiktok_id,
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
                            "profile_metrics": profile_metrics,
                        }
                    )
                except Exception:
                    continue

        for user in self._visible_comment_users_from_dom(video):
            users.setdefault(user["tiktok_id"], user)

        return list(users.values())

    def _visible_comment_users_from_dom(self, video: dict) -> list[dict]:
        try:
            rows = self.page.evaluate(
                """
                () => {
                  const anchors = Array.from(document.querySelectorAll("a[href*='/@']"));
                  return anchors.map((anchor) => {
                    const root = anchor.closest("[data-e2e='comment-level-1'], [class*='CommentItem'], div") || anchor;
                    const rect = root.getBoundingClientRect();
                    return {
                      href: anchor.href || anchor.getAttribute("href") || "",
                      anchorText: anchor.innerText || "",
                      text: root.innerText || "",
                      y: Math.round(rect.y),
                      height: Math.round(rect.height),
                    };
                  }).filter((item) => {
                    const text = item.text || "";
                    const looksLikeComment =
                      text.includes("Balas") || text.includes("Reply") ||
                      text.includes("yang lalu") || text.includes("ago") ||
                      text.includes("小时前") || text.includes("分钟前");
                    const isPageShell =
                      text.includes("Tajuk i18n TikTok") ||
                      text.includes("Untuk Anda") ||
                      text.includes("Kami menghadapi masalah untuk memainkan video ini") ||
                      text.includes("Komen\\n");
                    return item.href && looksLikeComment && !isPageShell &&
                      item.height > 0 && item.height < 520 &&
                      text.length < 1600 &&
                      item.y > -200 && item.y < window.innerHeight + 900;
                  }).slice(0, 500);
                }
                """,
            )
        except Exception:
            return []

        users: list[dict] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            tiktok_id = self._user_id_from_href(str(row.get("href", "")))
            if not tiktok_id:
                continue
            comment_text = str(row.get("text", ""))[:800]
            if not self._comment_matches_time_window(comment_text):
                continue
            profile_matches, profile_metrics = self._profile_matches_target_filters(tiktok_id)
            if not profile_matches:
                continue
            nickname = self._comment_nickname(
                link_text=str(row.get("anchorText", "")).strip(),
                comment_text=comment_text,
                tiktok_id=tiktok_id,
            )
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
                    "profile_metrics": profile_metrics,
                }
            )
        return users

    def _target_filters(self) -> dict:
        filters = self.task.get("target_filters") or {}
        return filters if isinstance(filters, dict) else {}

    def _comment_matches_time_window(self, comment_text: str) -> bool:
        filters = self._target_filters()
        min_days = self._safe_filter_int(filters.get("comment_min_days_ago", 0))
        max_days = self._safe_filter_int(filters.get("comment_max_days_ago", 0))
        if min_days <= 0 and max_days <= 0:
            return True

        age_days = self._comment_age_days(comment_text)
        if age_days is None:
            return True
        if min_days > 0 and age_days < min_days:
            return False
        if max_days > 0 and age_days > max_days:
            return False
        return True

    def _profile_matches_target_filters(self, tiktok_id: str) -> tuple[bool, dict]:
        filters = self._target_filters()
        followers_min = self._safe_filter_int(filters.get("followers_min", 0))
        followers_max = self._safe_filter_int(filters.get("followers_max", 0))
        following_min = self._safe_filter_int(filters.get("following_min", 0))
        following_max = self._safe_filter_int(filters.get("following_max", 0))
        registered_years = self._safe_filter_int(filters.get("registered_within_years", 0))

        needs_profile = any(
            value > 0
            for value in (followers_min, followers_max, following_min, following_max)
        )
        if not needs_profile:
            if registered_years > 0 and not self.registration_filter_warned:
                self.registration_filter_warned = True
                self.log("TikTok 主页通常不公开注册日期，注册日期条件已记录但暂不作为硬过滤。")
            return True, {}

        if tiktok_id in self.profile_metric_cache:
            return self.profile_metric_cache[tiktok_id]

        metrics = self._read_public_profile_metrics(tiktok_id)
        followers = metrics.get("followers")
        following = metrics.get("following")

        if followers is not None:
            if followers_min > 0 and followers < followers_min:
                result = (False, metrics)
                self.profile_metric_cache[tiktok_id] = result
                return result
            if followers_max > 0 and followers > followers_max:
                result = (False, metrics)
                self.profile_metric_cache[tiktok_id] = result
                return result

        if following is not None:
            if following_min > 0 and following < following_min:
                result = (False, metrics)
                self.profile_metric_cache[tiktok_id] = result
                return result
            if following_max > 0 and following > following_max:
                result = (False, metrics)
                self.profile_metric_cache[tiktok_id] = result
                return result

        result = (True, metrics)
        self.profile_metric_cache[tiktok_id] = result
        return result

    def _read_public_profile_metrics(self, tiktok_id: str) -> dict:
        profile_page = None
        metrics = {
            "followers": None,
            "following": None,
            "profile_checked": False,
        }
        try:
            profile_page = self.page.context.new_page()
            profile_page.goto(
                f"https://www.tiktok.com/@{tiktok_id}",
                wait_until="domcontentloaded",
                timeout=35000,
            )
            profile_page.wait_for_timeout(2500)
            text = profile_page.locator("body").inner_text(timeout=6000)
            metrics["followers"] = self._parse_profile_metric(
                text,
                ("followers", "pengikut", "粉丝", "粉絲"),
            )
            metrics["following"] = self._parse_profile_metric(
                text,
                ("following", "mengikuti", "关注", "正在关注"),
            )
            metrics["profile_checked"] = True
        except Exception as exc:
            metrics["profile_error"] = str(exc).splitlines()[0][:160]
        finally:
            try:
                if profile_page is not None:
                    profile_page.close()
            except Exception:
                pass
        return metrics

    @classmethod
    def _parse_profile_metric(cls, text: str, labels: tuple[str, ...]) -> int | None:
        if not text:
            return None

        label_pattern = "|".join(re.escape(label) for label in labels)
        patterns = [
            rf"(\d[\d,.\s]*\s*[KkMmBb万千]?)\s*(?:{label_pattern})",
            rf"(?:{label_pattern})\s*(\d[\d,.\s]*\s*[KkMmBb万千]?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return cls._parse_human_count(match.group(1))
        return None

    @staticmethod
    def _parse_human_count(value: str) -> int | None:
        raw = str(value or "").strip().replace(",", "").replace(" ", "")
        if not raw:
            return None

        suffix = raw[-1]
        multiplier = 1
        if suffix in {"K", "k"}:
            multiplier = 1_000
            raw = raw[:-1]
        elif suffix in {"M", "m"}:
            multiplier = 1_000_000
            raw = raw[:-1]
        elif suffix in {"B", "b"}:
            multiplier = 1_000_000_000
            raw = raw[:-1]
        elif suffix == "万":
            multiplier = 10_000
            raw = raw[:-1]
        elif suffix == "千":
            multiplier = 1_000
            raw = raw[:-1]

        try:
            return int(float(raw) * multiplier)
        except ValueError:
            return None

    @staticmethod
    def _safe_filter_int(value) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _comment_age_days(comment_text: str) -> int | None:
        text = str(comment_text or "").lower()
        if not text:
            return None

        if re.search(r"(just now|刚刚|baru saja|sekarang)", text):
            return 0

        minute_match = re.search(r"(\d+)\s*(分钟|分钟前|m|min|mins|minute|minutes)", text)
        if minute_match:
            return 0

        hour_match = re.search(r"(\d+)\s*(小时|小时前|h|hr|hrs|hour|hours|j|jam)", text)
        if hour_match:
            return 0

        day_match = re.search(r"(\d+)\s*(天|天前|d|day|days|hari)", text)
        if day_match:
            return int(day_match.group(1))

        week_match = re.search(r"(\d+)\s*(周|周前|w|week|weeks|minggu)", text)
        if week_match:
            return int(week_match.group(1)) * 7

        month_match = re.search(r"(\d+)\s*(个月|月前|mo|month|months|bulan)", text)
        if month_match:
            return int(month_match.group(1)) * 30

        date_match = re.search(r"\b(\d{1,2})[-/](\d{1,2})\b", text)
        if not date_match:
            return None

        first = int(date_match.group(1))
        second = int(date_match.group(2))
        now = datetime.now()
        candidates = []
        for month, day in ((first, second), (second, first)):
            if 1 <= month <= 12 and 1 <= day <= 31:
                try:
                    parsed = datetime(now.year, month, day)
                except ValueError:
                    continue
                if parsed > now:
                    parsed = datetime(now.year - 1, month, day)
                candidates.append((now - parsed).days)

        return min(candidates) if candidates else None

    @staticmethod
    def _comment_nickname(link_text: str, comment_text: str, tiktok_id: str) -> str:
        link_text = str(link_text or "").strip()
        if link_text and link_text not in {"·", "•"}:
            return link_text

        for line in str(comment_text or "").splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            if candidate in {"Balas", "Reply", "· Pencipta", "Pencipta"}:
                continue
            if re.search(r"^\d+[smhdw]?$", candidate, flags=re.I):
                continue
            return candidate[:120]

        return tiktok_id

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
        try:
            return self.page.evaluate(
                """
                () => {
                  const candidates = Array.from(document.querySelectorAll("div, section, main"))
                    .filter((el) => {
                      const style = window.getComputedStyle(el);
                      const overflow = `${style.overflowY} ${style.overflow}`;
                      return el.scrollHeight > el.clientHeight + 40 &&
                        /(auto|scroll)/.test(overflow) &&
                        el.querySelector("a[href*='/@']");
                    })
                    .sort((a, b) => b.scrollHeight - a.scrollHeight);
                  const el = candidates[0] || document.scrollingElement || document.documentElement;
                  return [Math.round(el.scrollTop), Math.round(el.scrollHeight), Math.round(el.clientHeight)];
                }
                """,
            )
        except Exception:
            return None

    def _scroll_comments(self) -> None:
        for selector in self.COMMENT_CONTAINER_SELECTORS:
            try:
                container = self.page.locator(selector).first
                container.evaluate(
                    "(el) => { el.scrollBy(0, Math.max(520, Math.round(el.clientHeight * 0.85))); }",
                    timeout=1500,
                )
                return
            except Exception:
                continue
        try:
            scrolled = self.page.evaluate(
                """
                () => {
                  const candidates = Array.from(document.querySelectorAll("div, section, main"))
                    .filter((el) => {
                      const style = window.getComputedStyle(el);
                      const overflow = `${style.overflowY} ${style.overflow}`;
                      return el.scrollHeight > el.clientHeight + 40 &&
                        /(auto|scroll)/.test(overflow) &&
                        el.querySelector("a[href*='/@']");
                    })
                    .sort((a, b) => b.scrollHeight - a.scrollHeight);
                  const el = candidates[0] || document.scrollingElement || document.documentElement;
                  if (!el) return false;
                  el.scrollBy(0, Math.max(620, Math.round((el.clientHeight || window.innerHeight) * 0.85)));
                  return true;
                }
                """,
            )
            if scrolled:
                return
        except Exception:
            pass
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

        actions = [
            lambda: self.page.keyboard.press("ArrowDown"),
            lambda: self.page.keyboard.press("PageDown"),
            lambda: self.page.mouse.wheel(0, 900),
            lambda: self.page.evaluate(
                "() => { window.scrollBy(0, Math.max(700, Math.round(window.innerHeight * 0.8))); }"
            ),
        ]
        for action in actions:
            try:
                action()
                self.page.wait_for_timeout(1800)
                if self._wait_for_video_change(before_key):
                    return True
            except Exception:
                continue
        return False

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

