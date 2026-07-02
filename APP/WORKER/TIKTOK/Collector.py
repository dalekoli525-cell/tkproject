# -*- coding: utf-8 -*-

"""TikTok page automation for recommendation and hashtag collection."""

from __future__ import annotations

import json
import re
import random
import time
from collections import Counter
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

    PLAYBACK_ERROR_MARKERS = (
        "Kami menghadapi masalah untuk memainkan video ini",
        "Sila segar semula dan cuba lagi",
        "We're having trouble playing this video",
        "Something went wrong",
        "无法播放此视频",
        "无法播放这个视频",
        "请刷新重试",
    )
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
        "input[data-e2e*='search' i]",
        "div[role='search'] input",
        "form input[type='search']",
        "form input[type='text']",
        "input[placeholder*='Search' i]",
        "input[placeholder*='Cari' i]",
        "input[aria-label*='Search' i]",
        "input[aria-label*='Cari' i]",
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
        self.region_filter_warned = False

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

        mode_label = "标签视频" if mode == TASK_MODE_HASHTAG else "推荐视频"
        self.log(f"任务开始：模式={mode_label}，视频数量={max_videos_label}")
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

            if self._video_has_playback_error(video):
                if self._comment_entry_likely_available(video):
                    if not self._claim_video_or_skip(video, result):
                        if not self._next_video(video_key):
                            stagnant_rounds += 1
                        continue
                    self.log("视频播放失败，但评论区可用，先采集评论区用户")
                    self.store.save_video(video)
                    if self._collect_and_save_video_users(
                        video,
                        result,
                        local_index + 1,
                        max_videos_label,
                    ):
                        local_index += 1
                        if max_videos > 0 and local_index >= max_videos:
                            return
                        if not self._next_video(video_key):
                            stagnant_rounds += 1
                        continue

                self.log("检测到当前视频播放失败，先尝试恢复播放或切换到下一个视频")
                if self._recover_from_playback_error(video_key, mode):
                    stagnant_rounds = 0
                    continue
                result.skipped_videos += 1
                local_index += 1
                processed_keys.add(video_key)
                if max_videos > 0 and local_index >= max_videos:
                    return
                if not self._next_video(video_key) and stop_at_end:
                    stagnant_rounds += 1
                continue

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

            if not self._claim_video_or_skip(video, result):
                if not self._next_video(video_key):
                    stagnant_rounds += 1
                    if stagnant_rounds >= stagnant_limit:
                        if stop_at_end:
                            self.log("当前标签已到可见视频底部")
                        else:
                            self.log("推荐流连续多次未切换到新视频，结束当前任务以避免卡死")
                        return
                continue

            self.store.save_video(video)
            self._watch_current_video_before_comments(result)
            if self._mark_stopped_if_requested(result):
                self.store.release_video(video, self.task_code, self.environment_code, "task_stopped")
                return
            refreshed_video = self._read_video_meta(mode)
            refreshed_video["coordination_video_key"] = video.get("coordination_video_key", "")
            video = refreshed_video
            if self._video_has_playback_error(video) or not self._ensure_current_video_playing():
                if self._comment_entry_likely_available(video):
                    self.log("视频未能确认播放，但评论区可用，继续采集评论区用户")
                else:
                    self.log("观看过程中视频未能正常播放，跳过当前视频")
                    self.store.release_video(video, self.task_code, self.environment_code, "playback_failed")
                    result.skipped_videos += 1
                    local_index += 1
                    if max_videos > 0 and local_index >= max_videos:
                        return
                    if not self._next_video(video_key):
                        stagnant_rounds += 1
                    continue

            collected = self._collect_and_save_video_users(
                video,
                result,
                local_index + 1,
                max_videos_label,
            )
            if not collected:
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

            local_index += 1

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

    def _claim_video_or_skip(self, video: dict, result: CollectResult) -> bool:
        claim = self.store.claim_video(video, self.task_code, self.environment_code)
        if claim.acquired:
            video["coordination_video_key"] = claim.video_key
            self.log(f"视频已抢占，开始采集：{claim.video_key[:12]}")
            return True

        result.skipped_videos += 1
        if claim.reason == "DONE":
            self.log(f"视频已被其他任务采集完成，跳过：{claim.video_key[:12]}")
        elif claim.reason == "LOCKED":
            owner = claim.owner or "其他任务"
            self.log(f"视频正在被其他任务采集，跳过：{claim.video_key[:12]} / {owner}")
        else:
            self.log(f"视频协调器暂不可用，跳过当前视频：{claim.reason or 'UNKNOWN'}")
        return False

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
            self._prepare_current_video_for_collection(TASK_MODE_RECOMMEND, "推荐流入口")

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
        self._prepare_current_video_for_collection(TASK_MODE_HASHTAG, f"标签 #{keyword}")

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
                search_input.wait_for(state="visible", timeout=1800)
                search_input.click(timeout=1800)
                search_input.fill(keyword, timeout=2500)
                self.page.keyboard.press("Enter")
                self.page.wait_for_timeout(3500)
                self.log(f"已通过搜索框搜索标签：#{keyword}")
                return True
            except Exception:
                continue
        if self._search_keyword_by_clicking_shell(keyword):
            return True
        return False

    def _search_keyword_by_clicking_shell(self, keyword: str) -> bool:
        click_selectors = [
            "[data-e2e*='search' i]",
            "a[href*='/search']",
            "button[aria-label*='Search' i]",
            "button[aria-label*='Cari' i]",
            "text=Search",
            "text=Carian",
            "text=Cari",
            "text=搜索",
        ]
        for selector in click_selectors:
            try:
                target = self.page.locator(selector).first
                target.wait_for(state="visible", timeout=1200)
                target.click(timeout=1600)
                self.page.wait_for_timeout(500)
                self.page.keyboard.press("Control+A")
                self.page.keyboard.type(keyword, delay=random.randint(25, 55))
                self.page.keyboard.press("Enter")
                self.page.wait_for_timeout(3500)
                self.log(f"已通过搜索入口输入标签：#{keyword}")
                return True
            except Exception:
                continue

        try:
            focused = self.page.evaluate(
                """
                () => {
                  const candidates = Array.from(document.querySelectorAll("input, textarea, [contenteditable='true']"));
                  const visible = candidates.find((el) => {
                    const rect = el.getBoundingClientRect();
                    const text = `${el.placeholder || ""} ${el.ariaLabel || ""}`;
                    return rect.width > 80 && rect.height > 20 &&
                      rect.bottom > 0 && rect.top < window.innerHeight &&
                      /search|cari|carian|搜索/i.test(text);
                  });
                  if (!visible) return false;
                  visible.focus();
                  visible.click();
                  return true;
                }
                """,
            )
            if focused:
                self.page.keyboard.press("Control+A")
                self.page.keyboard.type(keyword, delay=random.randint(25, 55))
                self.page.keyboard.press("Enter")
                self.page.wait_for_timeout(3500)
                self.log(f"已通过搜索输入区域输入标签：#{keyword}")
                return True
        except Exception:
            pass
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

    def _prepare_current_video_for_collection(self, mode: str, label: str) -> None:
        self._focus_video_surface()
        self._mute_visible_videos()
        video = self._read_video_meta(mode)
        video_key = self._video_key(video)
        if self._video_has_playback_error(video):
            if self._video_ui_ready_for_collection(video):
                self.log(f"{label} 播放状态异常，但评论入口已渲染，继续采集当前内容")
                return
            self.log(f"{label} 当前视频播放失败且无评论入口，准备切换到下一个视频")
            self._recover_from_playback_error(video_key, mode)
            return
        if self._ensure_current_video_playing():
            self.log(f"{label} 视频已静音播放")
            return
        if self._video_ui_ready_for_collection(video):
            self.log(f"{label} 未能确认播放进度，但页面与评论入口已渲染，继续采集")
            return
        self.log(f"{label} 视频未能确认播放且评论入口不可用，准备切换到下一个视频")
        self._next_video(video_key)

    def _read_video_meta(self, mode: str) -> dict:
        url = self.page.url
        video_id = self._video_id_from_url(url)
        video_signature = self._current_video_signature()
        text = self._safe_page_text()
        tags = sorted(set(re.findall(r"#[\w\u4e00-\u9fff]+", text)))
        comment_count = self._extract_near_button_count(self.COMMENT_BUTTON_SELECTORS)

        return {
            "task_code": self.task_code,
            "environment_code": self.environment_code,
            "video_id": video_id or video_signature or url,
            "video_signature": video_signature,
            "url": url,
            "description": text[:1200],
            "tags": tags,
            "comment_count": comment_count,
            "source_mode": mode,
            "source_tag": self.active_tag or ",".join(self.task.get("hashtags") or []),
        }

    @staticmethod
    def _video_key(video: dict) -> str:
        for key in ("video_signature", "video_id"):
            value = str(video.get(key, "")).strip()
            if value:
                return value
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

    def _current_video_signature(self) -> str:
        try:
            payload = self.page.evaluate(
                """
                () => {
                  const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);
                  const visibleRect = (el) => {
                    const rect = el.getBoundingClientRect();
                    const width = Math.max(0, Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0));
                    const height = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
                    return { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(width), height: Math.round(height), area: width * height };
                  };
                  const videos = Array.from(document.querySelectorAll("video"))
                    .map((video) => {
                      const rect = visibleRect(video);
                      return {
                        src: video.currentSrc || video.src || "",
                        poster: video.poster || "",
                        paused: Boolean(video.paused),
                        duration: Number.isFinite(video.duration) ? Math.round(video.duration) : 0,
                        currentTime: Number.isFinite(video.currentTime) ? Math.round(video.currentTime) : 0,
                        rect,
                      };
                    })
                    .filter((item) => item.rect.area > viewportArea * 0.03)
                    .sort((a, b) => b.rect.area - a.rect.area);
                  const video = videos[0] || null;
                  const links = Array.from(document.querySelectorAll("a[href*='/@']"))
                    .map((anchor) => {
                      const rect = visibleRect(anchor);
                      return {
                        href: anchor.href || anchor.getAttribute("href") || "",
                        text: (anchor.innerText || "").trim(),
                        rect,
                      };
                    })
                    .filter((item) => item.rect.area > 0)
                    .sort((a, b) => Math.abs(a.rect.y - (video ? video.rect.y : 0)) - Math.abs(b.rect.y - (video ? video.rect.y : 0)))
                    .slice(0, 3);
                  const canonical = document.querySelector("link[rel='canonical']")?.href || "";
                  const ogUrl = document.querySelector("meta[property='og:url']")?.content || "";
                  const visibleText = (document.body?.innerText || "").slice(0, 1400);
                  return { canonical, ogUrl, location: location.href, video, links, visibleText };
                }
                """,
            )
        except Exception:
            return ""

        if not isinstance(payload, dict):
            return ""

        parts: list[str] = []
        for key in ("canonical", "ogUrl"):
            value = str(payload.get(key, "")).strip()
            video_id = self._video_id_from_url(value)
            if video_id:
                parts.append(f"id:{video_id}")
            elif value and "/video/" in value:
                parts.append(value)

        video = payload.get("video")
        if isinstance(video, dict):
            for key in ("src", "poster"):
                value = str(video.get(key, "")).strip()
                if value:
                    parts.append(f"{key}:{value[:220]}")
            rect = video.get("rect")
            if isinstance(rect, dict):
                parts.append(
                    "rect:"
                    f"{rect.get('x', '')},{rect.get('y', '')},"
                    f"{rect.get('width', '')},{rect.get('height', '')}"
                )
            duration = str(video.get("duration", "")).strip()
            if duration:
                parts.append(f"duration:{duration}")

        links = payload.get("links")
        if isinstance(links, list):
            for row in links[:2]:
                if not isinstance(row, dict):
                    continue
                href = str(row.get("href", "")).strip()
                text = str(row.get("text", "")).strip()
                if href:
                    parts.append(f"href:{href[:180]}")
                if text:
                    parts.append(f"text:{text[:80]}")

        if not parts:
            visible_text = str(payload.get("visibleText", "")).strip()
            if visible_text:
                parts.append(f"text:{visible_text[:240]}")

        return "|".join(parts)[:900]

    def _extract_near_button_count(self, selectors: list[str]) -> int:
        for selector in selectors:
            try:
                target = self.page.locator(selector).first
                candidate_texts = []
                for expression in ("self", "xpath=..", "xpath=../.."):
                    try:
                        node = target if expression == "self" else target.locator(expression)
                        candidate_texts.append(node.inner_text(timeout=900))
                    except Exception:
                        continue
                for text in candidate_texts:
                    number_count = len(re.findall(r"\d+(?:\.\d+)?[KkMm万]?", text.replace(",", "")))
                    value = self._parse_count(text)
                    if value >= 0 and number_count <= 2 and len(text.strip()) <= 140:
                        return value
            except Exception:
                continue
        try:
            value = self.page.evaluate(
                """
                () => {
                  const parseCount = (text) => {
                    const match = String(text || "").replace(/,/g, "").match(/(\\d+(?:\\.\\d+)?)([KkMm万]?)/g);
                    if (!match || !match.length) return -1;
                    const raw = match[match.length - 1];
                    const parts = raw.match(/(\\d+(?:\\.\\d+)?)([KkMm万]?)/);
                    if (!parts) return -1;
                    let value = Number(parts[1]);
                      const suffix = parts[2] || "";
                      if (suffix.toLowerCase() === "k") value *= 1000;
                      if (suffix.toLowerCase() === "m") value *= 1000000;
                      if (suffix === "万") value *= 10000;
                      return Math.round(value);
                  };
                  const numberTokenCount = (text) => {
                    const match = String(text || "").replace(/,/g, "").match(/(\\d+(?:\\.\\d+)?)([KkMm万]?)/g);
                    return match ? match.length : 0;
                  };
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 8 &&
                      rect.height > 8 &&
                      rect.bottom > 80 &&
                      rect.top < window.innerHeight - 20;
                  };
                  const textNear = (el) => {
                    const parts = [];
                    let node = el;
                    for (let depth = 0; node && depth < 4; depth += 1, node = node.parentElement) {
                      const text = node.innerText || node.getAttribute?.("aria-label") || "";
                      if (text) {
                        parts.push(text);
                        if (parseCount(text) >= 0 && numberTokenCount(text) <= 2 && text.length <= 180) {
                          return text;
                        }
                      }
                    }
                    return parts.join("\\n");
                  };
                  const headerMatches = Array.from(document.querySelectorAll("h1, h2, h3, div, span"))
                    .map((el) => ({ el, text: el.innerText || "" }))
                    .filter((item) => visible(item.el) && /\\b(Komen|Comments|评论)\\b/i.test(item.text));
                  for (const item of headerMatches) {
                    const value = parseCount(item.text);
                    if (value >= 0) return value;
                  }

                  const hintedNodes = Array.from(document.querySelectorAll(
                    "[data-e2e*='comment' i], button[aria-label*='comment' i], button[aria-label*='komen' i], [role='button'][aria-label*='comment' i], [role='button'][aria-label*='komen' i]"
                  ));
                  for (const node of hintedNodes) {
                    const target = node.closest("button, [role='button']") || node;
                    if (!visible(target)) continue;
                    const value = parseCount(textNear(target));
                    if (value >= 0) return value;
                  }

                  const buttons = Array.from(document.querySelectorAll("button, [role='button']"));
                  const rightRailNumbers = buttons.map((button) => {
                    const rect = button.getBoundingClientRect();
                    const text = textNear(button);
                    const value = parseCount(text);
                    return { value, x: rect.x, y: rect.y, width: rect.width, height: rect.height };
                  }).filter((item) =>
                    item.value >= 0 &&
                    item.width >= 24 &&
                    item.height >= 24 &&
                    item.x > window.innerWidth * 0.55 &&
                    item.y > 120 &&
                    item.y < window.innerHeight - 20
                  ).sort((a, b) => a.y - b.y);

                  // TikTok's right action rail usually orders numbers as like, comment, bookmark, share.
                  // Only use this fallback when there are enough numeric rail actions to avoid reading the like count.
                  return rightRailNumbers.length >= 2 ? rightRailNumbers[1].value : -1;
                }
                """,
            )
            return int(value)
        except Exception:
            pass
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

    def _video_has_playback_error(self, video: dict) -> bool:
        description = str(video.get("description", ""))
        return any(marker in description for marker in self.PLAYBACK_ERROR_MARKERS)

    def _video_matches_rules(self, video: dict, mode: str) -> bool:
        if self._video_has_playback_error(video):
            if self._video_ui_ready_for_collection(video):
                self.log("视频播放状态异常，但评论入口可用，继续采集")
            else:
                self.log("跳过播放异常且无评论入口的视频")
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
        if allow_tags:
            normalized_allow = {
                str(tag).strip().lstrip("#").lower()
                for tag in allow_tags
                if str(tag).strip()
            }
            normalized_tags = {
                str(tag).strip().lstrip("#").lower()
                for tag in tags
                if str(tag).strip()
            }
            if normalized_tags and not normalized_tags.intersection(normalized_allow):
                self.log("跳过未命中指定标签的视频")
                return False
            if not normalized_tags:
                self.log("当前视频未解析到页面标签，按标签入口来源继续采集")

        video["ai_decision"] = "MOCK_PASS"
        video["ai_score"] = 100
        video["ai_reason"] = "AI_DISABLED_TEMPORARILY"

        return True

    def _watch_current_video_before_comments(self, result: CollectResult) -> None:
        min_seconds = self._safe_filter_int(self.task.get("watch_seconds_min", 4))
        max_seconds = self._safe_filter_int(self.task.get("watch_seconds_max", 10))
        min_seconds = max(2, min_seconds)
        max_seconds = max(min_seconds, max_seconds)
        wait_ms = random.randint(min_seconds * 1000, max_seconds * 1000)
        try:
            viewport = self.page.viewport_size or {}
            width = int(viewport.get("width") or 1280)
            height = int(viewport.get("height") or 800)
            self.page.mouse.move(
                random.randint(max(20, width // 4), max(30, width // 2)),
                random.randint(max(20, height // 3), max(30, height * 2 // 3)),
                steps=random.randint(8, 16),
            )
        except Exception:
            pass

        elapsed = 0
        self._ensure_current_video_playing()
        while elapsed < wait_ms:
            if self._mark_stopped_if_requested(result):
                return
            step = min(900, wait_ms - elapsed)
            self.page.wait_for_timeout(step)
            elapsed += step

    def _recover_from_playback_error(self, before_key: str, mode: str) -> bool:
        if self._click_playback_retry():
            self.page.wait_for_timeout(random.randint(2200, 3600))
            if (
                not self._video_has_playback_error(self._read_video_meta(mode))
                and self._ensure_current_video_playing()
            ):
                self.log("播放失败已通过页面重试恢复")
                return True

        if self._next_video(before_key):
            self.log("播放失败视频已切换到下一个视频")
            return True

        try:
            self.page.reload(wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(random.randint(3200, 5200))
            if not self._video_has_playback_error(self._read_video_meta(mode)):
                self.log("播放失败已通过刷新页面恢复")
                return True
        except Exception as exc:
            self.log(f"刷新恢复播放失败：{str(exc).splitlines()[0][:120]}")

        self.log("播放失败视频未能恢复，也未能确认切换到新视频")
        return False

    def _ensure_current_video_playing(self) -> bool:
        for attempt in range(4):
            self._mute_visible_videos()
            try:
                state = self.page.evaluate(
                    """
                    () => {
                      const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);
                      const visibleRect = (el) => {
                        const rect = el.getBoundingClientRect();
                        const width = Math.max(0, Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0));
                        const height = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
                        return { area: width * height, x: rect.x, y: rect.y, width, height };
                      };
                      const videos = Array.from(document.querySelectorAll("video"))
                        .map((video) => ({ video, rect: visibleRect(video) }))
                        .filter((item) => item.rect.area > viewportArea * 0.03)
                        .sort((a, b) => b.rect.area - a.rect.area);
                      const target = videos[0]?.video || null;
                      if (!target) return { found: false };
                      const before = Number.isFinite(target.currentTime) ? target.currentTime : 0;
                      target.muted = true;
                      target.volume = 0;
                      target.play().catch(() => {});
                      return {
                        found: true,
                        paused: Boolean(target.paused),
                        readyState: target.readyState,
                        currentTime: before,
                        src: target.currentSrc || target.src || "",
                      };
                    }
                    """,
                )
            except Exception:
                state = {}

            self.page.wait_for_timeout(900)
            if self._video_has_playback_error(self._read_video_meta(str(self.task.get("mode", TASK_MODE_RECOMMEND)))):
                return False

            try:
                progressed = self.page.evaluate(
                    """
                    () => {
                      const videos = Array.from(document.querySelectorAll("video"))
                        .filter((video) => {
                          const rect = video.getBoundingClientRect();
                          return rect.width > 120 && rect.height > 120;
                        })
                        .sort((a, b) => {
                          const ar = a.getBoundingClientRect();
                          const br = b.getBoundingClientRect();
                          return (br.width * br.height) - (ar.width * ar.height);
                        });
                      const video = videos[0];
                      if (!video) return false;
                      return !video.paused && video.readyState >= 2 && video.currentTime > 0;
                    }
                    """,
                )
                if progressed:
                    return True
            except Exception:
                pass

            if attempt == 1:
                self._focus_video_surface()
        return False

    def _mute_visible_videos(self) -> None:
        try:
            self.page.evaluate(
                """
                () => {
                  for (const video of document.querySelectorAll("video")) {
                    video.muted = true;
                    video.volume = 0;
                    video.setAttribute("muted", "");
                    video.setAttribute("playsinline", "");
                  }
                }
                """,
            )
        except Exception:
            pass

    def _click_playback_retry(self) -> bool:
        retry_selectors = [
            "button:has-text('刷新')",
            "button:has-text('重试')",
            "button:has-text('Refresh')",
            "button:has-text('Retry')",
            "button:has-text('Segar semula')",
            "button:has-text('Cuba lagi')",
            "text=刷新",
            "text=重试",
            "text=Refresh",
            "text=Retry",
            "text=Segar semula",
            "text=Cuba lagi",
        ]
        for selector in retry_selectors:
            try:
                target = self.page.locator(selector).first
                target.wait_for(state="visible", timeout=900)
                target.click(timeout=1200)
                return True
            except Exception:
                continue
        return False

    def _collect_and_save_video_users(
        self,
        video: dict,
        result: CollectResult,
        display_index: int,
        max_videos_label: str,
    ) -> bool:
        comment_count = video.get("comment_count", -1)
        if isinstance(comment_count, int) and comment_count >= 0:
            self.log(f"视频 {display_index}/{max_videos_label} 评论数：{comment_count}")

        try:
            users = self._collect_comment_users(video, result)
        except Exception:
            self.store.release_video(video, self.task_code, self.environment_code, "collect_exception")
            raise

        if video.get("comment_collect_status") == "NO_COMMENT_BUTTON":
            self.store.release_video(video, self.task_code, self.environment_code, "no_comment_button")
            return False

        saved = self.store.save_users(users)
        if result.stopped:
            self.store.release_video(video, self.task_code, self.environment_code, "task_stopped")
        else:
            self.store.complete_video(
                video,
                self.task_code,
                self.environment_code,
                users_count=len(users),
                saved_count=saved,
            )
        result.videos_seen += 1
        result.users_saved += saved
        self.log(
            f"视频 {display_index}/{max_videos_label} 完成：采集用户 {len(users)}，新增 {saved}"
        )
        return True

    def _comment_entry_likely_available(self, video: dict) -> bool:
        if self.task.get("skip_zero_comment_video", True) and video.get("comment_count") == 0:
            return False

        if self._comments_panel_visible():
            return True

        for selector in self.COMMENT_BUTTON_SELECTORS:
            try:
                if self.page.locator(selector).first.is_visible(timeout=700):
                    return True
            except Exception:
                continue
        return False

    def _video_ui_ready_for_collection(self, video: dict) -> bool:
        """Treat a rendered TikTok action rail/comment panel as collectable even if playback probing fails."""

        if self._comments_panel_visible():
            return True

        comment_count = video.get("comment_count", -1)
        if isinstance(comment_count, int) and comment_count > 0:
            return True

        url = str(video.get("url", "") or self.page.url)
        if "/video/" in url or "/photo/" in url:
            if self._comment_entry_likely_available(video):
                return True

        try:
            return bool(
                self.page.evaluate(
                    """
                    () => {
                      const visible = (el) => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width >= 24 &&
                          rect.height >= 24 &&
                          rect.right > window.innerWidth * 0.48 &&
                          rect.bottom > 80 &&
                          rect.top < window.innerHeight - 20;
                      };
                      const commentNodes = Array.from(document.querySelectorAll(
                        "[data-e2e*='comment' i], button[aria-label*='comment' i], button[aria-label*='komen' i], [role='button'][aria-label*='comment' i], [role='button'][aria-label*='komen' i]"
                      ));
                      if (commentNodes.some(visible)) return true;
                      const actionButtons = Array.from(document.querySelectorAll("button, [role='button']"))
                        .filter((button) => {
                          const rect = button.getBoundingClientRect();
                          return rect.width >= 28 &&
                            rect.height >= 28 &&
                            rect.x > window.innerWidth * 0.55 &&
                            rect.y > 120 &&
                            rect.y < window.innerHeight - 20;
                        });
                      return actionButtons.length >= 3;
                    }
                    """,
                )
            )
        except Exception:
            return False

    def _collect_comment_users(self, video: dict, result: CollectResult) -> list[dict]:
        max_comments = int(self.task.get("max_comments_per_video") or 0)
        batch_size = max(1, int(self.task.get("comment_batch_size") or 20))
        if not self._open_comments():
            video["comment_collect_status"] = "NO_COMMENT_BUTTON"
            return []

        comment_count = video.get("comment_count", -1)
        comment_count = comment_count if isinstance(comment_count, int) else -1
        expected_batches = 0
        if max_comments > 0:
            expected_batches = max(1, (max_comments + batch_size - 1) // batch_size)
        elif comment_count > 0:
            expected_batches = max(1, (comment_count + batch_size - 1) // batch_size)

        configured_max_rounds = int(self.task.get("max_comment_scroll_rounds") or 0)
        if configured_max_rounds > 0:
            max_scroll_rounds = configured_max_rounds
        elif expected_batches > 0:
            max_scroll_rounds = min(max(expected_batches + 40, 60), 1000)
        else:
            max_scroll_rounds = 180

        min_scroll_rounds_before_stable_stop = 0
        if max_comments <= 0 and comment_count > batch_size:
            min_scroll_rounds_before_stable_stop = max(12, min(expected_batches - 2, 240))
        if comment_count > batch_size:
            self.log(
                f"评论区全量采集准备：页面评论数 {comment_count}，批次大小 {batch_size}，"
                f"预计批次 {expected_batches}，最大滚动 {max_scroll_rounds} 次"
            )

        raw_candidates: dict[str, dict] = {}
        stable_rounds = 0
        max_stable_rounds = 8 if max_comments > 0 else 18
        previous_scroll_state = self._comment_scroll_state()
        next_batch_log_at = batch_size
        scroll_round = 0

        while (max_comments <= 0 or len(raw_candidates) < max_comments) and scroll_round < max_scroll_rounds:
            if self._mark_stopped_if_requested(result):
                self.log("已收到暂停请求：停止加载新评论，开始筛选已采集候选")
                break

            before_count = len(raw_candidates)
            raw_users = self._visible_comment_users(video, apply_filters=False)
            if raw_users:
                new_raw_users = [
                    user
                    for user in raw_users
                    if user.get("tiktok_id") and user["tiktok_id"] not in raw_candidates
                ]
                for user in new_raw_users:
                    raw_candidates[user["tiktok_id"]] = user
                if new_raw_users:
                    self.store.save_comment_candidates(new_raw_users)
                    self.log(
                        f"评论区滚动采集中：本轮解析 {len(raw_users)}，新增候选 {len(new_raw_users)}，累计候选 {len(raw_candidates)}"
                    )
                    while len(raw_candidates) >= next_batch_log_at:
                        batch_number = next_batch_log_at // batch_size
                        self.log(
                            f"评论区批次加载完成：第 {batch_number} 批，目标 {batch_size}，累计候选 {len(raw_candidates)}"
                        )
                        next_batch_log_at += batch_size

            before_scroll_state = self._comment_scroll_state()
            scrolled = self._scroll_comments()
            self.page.wait_for_timeout(800)
            after_scroll_state = self._comment_scroll_state()
            scroll_unchanged = (
                after_scroll_state == before_scroll_state
                or after_scroll_state == previous_scroll_state
            )
            at_bottom = self._comment_scroll_at_bottom(after_scroll_state)
            if len(raw_candidates) == before_count and (scroll_unchanged or not scrolled):
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_scroll_state = after_scroll_state
            scroll_round += 1

            if max_comments <= 0 and comment_count > 0 and len(raw_candidates) >= comment_count:
                self.log(f"评论区候选已达到页面评论数：{len(raw_candidates)}/{comment_count}")
                break

            can_stop_by_stable = (
                stable_rounds >= max_stable_rounds
                and (at_bottom or scroll_round >= min_scroll_rounds_before_stable_stop)
            )
            if can_stop_by_stable:
                self.log(
                    f"评论区滚动结束：已滚动 {scroll_round} 次，连续无新增 {stable_rounds} 次，"
                    f"到底={self._yes_no(at_bottom)}，候选 {len(raw_candidates)}"
                )
                break

            if scroll_round % 5 == 0 and len(raw_candidates) < next_batch_log_at:
                progress_hint = ""
                if comment_count > 0:
                    progress_hint = f"，页面评论数 {comment_count}，预计批次 {expected_batches}"
                self.log(
                    f"评论区继续滚动加载：已滚动 {scroll_round} 次，累计候选 {len(raw_candidates)}，"
                    f"当前批目标 {next_batch_log_at}{progress_hint}"
                )

            time.sleep(0.2)

        if scroll_round >= max_scroll_rounds:
            self.log(f"评论区达到最大滚动轮次 {max_scroll_rounds}，停止当前视频评论采集")

        self._close_comments_if_needed()
        if not raw_candidates:
            self.log("评论区未采集到候选用户")
            return []

        users: dict[str, dict] = {}
        reject_reason_counts: Counter[str] = Counter()
        total_candidates = len(raw_candidates)
        self.log(f"评论区候选采集完成：候选 {total_candidates}，开始后台静默筛选")
        if result.stopped:
            self.log("暂停处理中：继续完成当前候选区静默筛选，筛选完成后关闭环境")
        for index, raw_user in enumerate(raw_candidates.values(), start=1):
            user, reject_reasons = self._qualify_comment_user(raw_user)
            if user:
                users.setdefault(user["tiktok_id"], user)
            else:
                for reason in reject_reasons or ["未知原因"]:
                    reject_reason_counts[reason] += 1
            if index == 1 or index % 5 == 0 or index == total_candidates:
                rejected = sum(reject_reason_counts.values())
                reason_text = self._format_reject_reason_counts(reject_reason_counts)
                self.log(
                    f"静默筛选进度：{index}/{total_candidates}，达标 {len(users)}，"
                    f"不达标 {rejected}{reason_text}"
                )
            if max_comments > 0 and len(users) >= max_comments:
                break

        if reject_reason_counts:
            self.log(
                f"静默筛选完成：候选 {total_candidates}，达标 {len(users)}，"
                f"不达标 {sum(reject_reason_counts.values())}"
                f"{self._format_reject_reason_counts(reject_reason_counts, limit=6)}"
            )

        if max_comments > 0:
            return list(users.values())[:max_comments]
        return list(users.values())

    @staticmethod
    def _comment_scroll_at_bottom(state) -> bool:
        if not isinstance(state, list) or len(state) < 3:
            return False
        try:
            top = int(state[0])
            scroll_height = int(state[1])
            client_height = int(state[2])
            if len(state) >= 7:
                return bool(state[6])
            return scroll_height > 0 and top + client_height >= scroll_height - 24
        except Exception:
            return False

    @staticmethod
    def _yes_no(value: bool) -> str:
        return "是" if value else "否"

    @staticmethod
    def _format_reject_reason_counts(reason_counts, limit: int = 4) -> str:
        if not reason_counts:
            return ""

        top_reasons = reason_counts.most_common(limit)
        parts = [
            f"{reason} {count}"
            for reason, count in top_reasons
        ]
        remaining = sum(reason_counts.values()) - sum(count for _, count in top_reasons)
        if remaining > 0:
            parts.append(f"其他原因 {remaining}")
        return "，原因：" + "；".join(parts)

    def _comments_panel_visible(self) -> bool:
        panel_selectors = [
            *self.COMMENT_CONTAINER_SELECTORS,
            "text=/^(Komen|Comments|评论)\\b/i",
        ]
        for selector in panel_selectors:
            try:
                if self.page.locator(selector).first.is_visible(timeout=700):
                    return True
            except Exception:
                continue
        return False

    def _open_comments(self) -> bool:
        if self._comments_panel_visible():
            return True

        for selector in self.COMMENT_BUTTON_SELECTORS:
            try:
                button = self.page.locator(selector).first
                button.wait_for(state="visible", timeout=2200)
                button.click(timeout=3000)
                self.page.wait_for_timeout(1800)
                return True
            except Exception:
                continue
        if self._click_comment_button_by_dom():
            self.page.wait_for_timeout(1800)
            return True
        self.log("未找到评论按钮")
        return False

    def _click_comment_button_by_dom(self) -> bool:
        try:
            return bool(
                self.page.evaluate(
                    """
                    () => {
                      const parseCount = (text) => {
                        const match = String(text || "").replace(/,/g, "").match(/(\\d+(?:\\.\\d+)?)([KkMm万]?)/g);
                        return Boolean(match && match.length);
                      };
                      const visibleButton = (button) => {
                        const rect = button.getBoundingClientRect();
                        return rect.width >= 28 &&
                          rect.height >= 28 &&
                          rect.y > 120 &&
                          rect.y < window.innerHeight - 20;
                      };
                      const buttons = Array.from(document.querySelectorAll("button, [role='button']"));
                      const hinted = buttons.map((button) => {
                        const rect = button.getBoundingClientRect();
                        const text = button.innerText || button.getAttribute("aria-label") || "";
                        const hasCommentHint =
                          /comment|komen|评论/i.test(text) ||
                          Boolean(button.querySelector("[data-e2e*='comment' i], svg[data-e2e*='comment' i]"));
                        return { button, text, hasCount: parseCount(text), hasCommentHint, rect };
                      }).filter((item) =>
                        item.hasCommentHint &&
                        visibleButton(item.button)
                      ).sort((a, b) => {
                        return Math.abs(a.rect.y - window.innerHeight * 0.65) - Math.abs(b.rect.y - window.innerHeight * 0.65);
                      });

                      const rightRailNumbers = buttons.map((button) => {
                        const rect = button.getBoundingClientRect();
                        let text = button.innerText || button.getAttribute("aria-label") || "";
                        let parent = button.parentElement;
                        for (let depth = 0; parent && depth < 3; depth += 1, parent = parent.parentElement) {
                          text += "\\n" + (parent.innerText || "");
                        }
                        return { button, text, hasCount: parseCount(text), rect };
                      }).filter((item) =>
                        item.hasCount &&
                        visibleButton(item.button) &&
                        item.rect.x > window.innerWidth * 0.55
                      ).sort((a, b) => a.rect.y - b.rect.y);

                      const target = hinted[0]?.button || rightRailNumbers[1]?.button;
                      if (!target) return false;
                      target.scrollIntoView({ block: "center", inline: "center" });
                      target.click();
                      return true;
                    }
                    """,
                )
            )
        except Exception:
            return False

    def _visible_comment_users(self, video: dict, apply_filters: bool = True) -> list[dict]:
        users: dict[str, dict] = {}
        for user in self._visible_comment_users_from_dom(video, apply_filters=apply_filters):
            users.setdefault(user["tiktok_id"], user)
        if users:
            return list(users.values())

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
                    if apply_filters and not self._comment_matches_time_window(comment_text):
                        continue
                    nickname = self._comment_nickname(
                        link_text=link.inner_text(timeout=1000).strip(),
                        comment_text=comment_text,
                        tiktok_id=tiktok_id,
                    )
                    profile_metrics = {}
                    ai_decision = "PENDING"
                    ai_score = 0
                    ai_reason = "raw_comment_candidate"
                    if apply_filters:
                        profile_matches, profile_metrics = self._profile_matches_target_filters(tiktok_id)
                        if not profile_matches:
                            continue
                        ai_decision = "MOCK_PASS"
                        ai_score = 100
                        ai_reason = "AI_DISABLED_TEMPORARILY"
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
                            "ai_decision": ai_decision,
                            "ai_score": ai_score,
                            "ai_reason": ai_reason,
                            "qualified": bool(apply_filters),
                            "profile_metrics": profile_metrics,
                        }
                    )
                except Exception:
                    continue

        return list(users.values())

    def _qualify_comment_user(self, raw_user: dict) -> tuple[dict | None, list[str]]:
        """Apply local target filters to one already-extracted comment user."""

        tiktok_id = str(raw_user.get("tiktok_id", "")).strip()
        if not tiktok_id:
            return None, ["TikTok ID 为空"]

        comment_reason = self._comment_time_reject_reason(
            str(raw_user.get("comment_text", ""))
        )
        if comment_reason:
            return None, [comment_reason]

        profile_matches, profile_metrics = self._profile_matches_target_filters(tiktok_id)
        if not profile_matches:
            reasons = profile_metrics.get("filter_reasons")
            if not isinstance(reasons, list) or not reasons:
                reasons = ["主页数据不达标"]
            return None, [str(reason) for reason in reasons if str(reason).strip()]

        user = dict(raw_user)
        user["ai_decision"] = "MOCK_PASS"
        user["ai_score"] = 100
        user["ai_reason"] = "AI_DISABLED_TEMPORARILY"
        user["qualified"] = True
        user["profile_metrics"] = profile_metrics
        return user, []

    def _visible_comment_users_from_dom(self, video: dict, apply_filters: bool = True) -> list[dict]:
        try:
            rows = self.page.evaluate(
                """
                () => {
                  const anchors = Array.from(document.querySelectorAll("a[href*='/@']"));
                  const looksLikeCommentText = (text) => {
                    text = String(text || "");
                    return (
                      text.includes("Balas") || text.includes("Reply") ||
                      text.includes("Lihat") || text.includes("View") ||
                      text.includes("yang lalu") || text.includes("ago") ||
                      text.includes("小时前") || text.includes("分钟前") ||
                      /\\b\\d+\\s*(s|m|h|j|d|w)\\b/i.test(text) ||
                      /\\b\\d{1,2}-\\d{1,2}\\b/.test(text)
                    );
                  };
                  const shellText = (text) => {
                    text = String(text || "");
                    return (
                      text.includes("Tajuk i18n TikTok") ||
                      text.includes("Untuk Anda") ||
                      text.includes("Kami menghadapi masalah untuk memainkan video ini") ||
                      text.includes("Mengikuti akaun") ||
                      text.includes("Muat naik") ||
                      text.includes("Komen\\n")
                    );
                  };
                  const commentRootFor = (anchor) => {
                    let el = anchor;
                    for (let depth = 0; el && depth < 8; depth += 1, el = el.parentElement) {
                      const text = el.innerText || "";
                      if (text.length > 12 && text.length < 2200 && looksLikeCommentText(text) && !shellText(text)) {
                        return el;
                      }
                    }
                    return anchor.closest("[data-e2e='comment-level-1'], [class*='CommentItem'], div") || anchor;
                  };
                  return anchors.map((anchor) => {
                    const root = commentRootFor(anchor);
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
                    return item.href &&
                      looksLikeCommentText(text) &&
                      !shellText(text) &&
                      text.length < 2200;
                  }).slice(0, 1200);
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
            if apply_filters and not self._comment_matches_time_window(comment_text):
                continue
            nickname = self._comment_nickname(
                link_text=str(row.get("anchorText", "")).strip(),
                comment_text=comment_text,
                tiktok_id=tiktok_id,
            )
            profile_metrics = {}
            ai_decision = "PENDING"
            ai_score = 0
            ai_reason = "raw_comment_candidate"
            if apply_filters:
                profile_matches, profile_metrics = self._profile_matches_target_filters(tiktok_id)
                if not profile_matches:
                    continue
                ai_decision = "MOCK_PASS"
                ai_score = 100
                ai_reason = "AI_DISABLED_TEMPORARILY"
            users.append(
                {
                    "task_code": self.task_code,
                    "environment_code": self.environment_code,
                    "tiktok_id": tiktok_id,
                    "nickname": nickname,
                    "comment_text": comment_text,
                    "source_video_id": video.get("video_id", ""),
                    "source_tag": video.get("source_tag", ""),
                    "ai_decision": ai_decision,
                    "ai_score": ai_score,
                    "ai_reason": ai_reason,
                    "qualified": bool(apply_filters),
                    "profile_metrics": profile_metrics,
                }
            )
        unique_users: dict[str, dict] = {}
        for user in users:
            unique_users.setdefault(user["tiktok_id"], user)
        return list(unique_users.values())

    def _target_filters(self) -> dict:
        filters = self.task.get("target_filters") or {}
        if not isinstance(filters, dict):
            return {}

        normalized = dict(filters)

        # Product meaning: 粉丝量/关注量 are upper limits. Older task files used
        # followers_min/following_min, so migrate those values at runtime too.
        followers_max = self._safe_filter_int(normalized.get("followers_max", 0))
        legacy_followers_limit = self._safe_filter_int(normalized.get("followers_min", 0))
        if followers_max <= 0 and legacy_followers_limit > 0:
            normalized["followers_max"] = legacy_followers_limit
        normalized["followers_min"] = 0

        following_max = self._safe_filter_int(normalized.get("following_max", 0))
        legacy_following_limit = self._safe_filter_int(normalized.get("following_min", 0))
        if following_max <= 0 and legacy_following_limit > 0:
            normalized["following_max"] = legacy_following_limit
        normalized["following_min"] = 0

        return normalized

    def _comment_matches_time_window(self, comment_text: str) -> bool:
        return self._comment_time_reject_reason(comment_text) is None

    def _comment_time_reject_reason(self, comment_text: str) -> str | None:
        filters = self._target_filters()
        min_days = self._safe_filter_int(filters.get("comment_min_days_ago", 0))
        max_days = self._safe_filter_int(filters.get("comment_max_days_ago", 0))
        if min_days <= 0 and max_days <= 0:
            return None

        age_days = self._comment_age_days(comment_text)
        if age_days is None:
            return None
        if min_days > 0 and age_days < min_days:
            return f"评论时间过近(<{min_days}天)"
        if max_days > 0 and age_days > max_days:
            return f"评论时间超出(>{max_days}天)"
        return None

    def _profile_matches_target_filters(self, tiktok_id: str) -> tuple[bool, dict]:
        filters = self._target_filters()
        followers_min = self._safe_filter_int(filters.get("followers_min", 0))
        followers_max = self._safe_filter_int(filters.get("followers_max", 0))
        following_min = self._safe_filter_int(filters.get("following_min", 0))
        following_max = self._safe_filter_int(filters.get("following_max", 0))
        registered_years = self._safe_filter_int(filters.get("registered_within_years", 0))
        registration_year_min = self._safe_filter_int(filters.get("registration_year_min", 0))
        min_posts = self._safe_filter_int(filters.get("min_posts", 0))
        registration_regions = filters.get("registration_regions") or []

        needs_profile = any(
            value > 0
            for value in (followers_min, followers_max, following_min, following_max, min_posts)
        )
        if not needs_profile:
            if (registered_years > 0 or registration_year_min > 0) and not self.registration_filter_warned:
                self.registration_filter_warned = True
                self.log("TikTok 主页通常不公开注册日期，注册日期条件已记录但暂不作为硬过滤。")
            if registration_regions and not self.region_filter_warned:
                self.region_filter_warned = True
                self.log("TikTok 主页通常不公开注册地区，注册地区条件已记录但暂不作为硬过滤。")
            return True, {}

        if tiktok_id in self.profile_metric_cache:
            return self.profile_metric_cache[tiktok_id]

        metrics = self._read_public_profile_metrics(tiktok_id)
        followers = metrics.get("followers")
        following = metrics.get("following")
        posts = metrics.get("posts")

        def reject(*reasons: str) -> tuple[bool, dict]:
            clean_reasons = [
                str(reason).strip()
                for reason in reasons
                if str(reason).strip()
            ]
            if not clean_reasons:
                clean_reasons = ["主页数据不达标"]
            metrics["filter_reasons"] = clean_reasons
            result = (False, metrics)
            self.profile_metric_cache[tiktok_id] = result
            return result

        if not metrics.get("profile_checked"):
            status = metrics.get("http_status")
            if status == 404:
                return reject("主页不存在或不可访问")
            if status:
                return reject(f"主页读取失败(HTTP {status})")
            return reject("主页读取失败")

        if followers_min > 0 and followers is None:
            return reject("粉丝数未公开/未解析")
        if followers_max > 0 and followers is None:
            return reject("粉丝数未公开/未解析")
        if followers is not None:
            if followers_min > 0 and followers < followers_min:
                return reject(f"粉丝数不足(<{followers_min})")
            if followers_max > 0 and followers > followers_max:
                return reject(f"粉丝数超出(>{followers_max})")

        if following_min > 0 and following is None:
            return reject("关注数未公开/未解析")
        if following_max > 0 and following is None:
            return reject("关注数未公开/未解析")
        if following is not None:
            if following_min > 0 and following < following_min:
                return reject(f"关注数不足(<{following_min})")
            if following_max > 0 and following > following_max:
                return reject(f"关注数超出(>{following_max})")

        if min_posts > 0 and posts is None:
            return reject("作品数未公开/未解析")
        if posts is not None and min_posts > 0 and posts < min_posts:
            return reject(f"作品数不足(<{min_posts})")

        if (registered_years > 0 or registration_year_min > 0) and not self.registration_filter_warned:
            self.registration_filter_warned = True
            self.log("TikTok 主页通常不公开注册日期，注册日期条件已记录但暂不作为硬过滤。")
        if registration_regions and not self.region_filter_warned:
            self.region_filter_warned = True
            self.log("TikTok 主页通常不公开注册地区，注册地区条件已记录但暂不作为硬过滤。")

        metrics["filter_reasons"] = []
        result = (True, metrics)
        self.profile_metric_cache[tiktok_id] = result
        return result

    def _read_public_profile_metrics(self, tiktok_id: str) -> dict:
        metrics = {
            "followers": None,
            "following": None,
            "posts": None,
            "profile_checked": False,
            "profile_method": "background_request",
        }
        try:
            request_context = getattr(self.page.context, "request", None)
            if request_context is None:
                metrics["profile_error"] = "browser context request API unavailable"
                return metrics

            response = request_context.get(
                f"https://www.tiktok.com/@{tiktok_id}",
                timeout=18000,
                headers={
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "accept-language": "ms-MY,ms;q=0.9,en;q=0.8,zh-CN;q=0.7",
                    "user-agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/149.0.0.0 Safari/537.36"
                    ),
                },
            )
            metrics["http_status"] = response.status
            if response.status >= 400:
                metrics["profile_error"] = f"http_status_{response.status}"
                return metrics

            payload = response.text()
            parsed = self._parse_profile_metrics_from_payload(payload)
            metrics.update(parsed)
            metrics["profile_checked"] = True
        except Exception as exc:
            metrics["profile_error"] = str(exc).splitlines()[0][:160]
        return metrics

    def _parse_profile_metrics_from_payload(self, payload: str) -> dict:
        metrics = {
            "followers": None,
            "following": None,
            "posts": None,
        }
        text = str(payload or "")
        if not text:
            return metrics

        key_map = {
            "followers": ("followerCount", "followers", "fans", "fansCount"),
            "following": ("followingCount", "following"),
            "posts": ("videoCount", "awemeCount", "posts"),
        }
        for metric_name, keys in key_map.items():
            for key in keys:
                value = self._parse_json_number_field(text, key)
                if value is not None:
                    metrics[metric_name] = value
                    break

        if metrics["followers"] is None:
            metrics["followers"] = self._parse_profile_metric(
                text,
                ("followers", "pengikut", "粉丝", "粉絲"),
            )
        if metrics["following"] is None:
            metrics["following"] = self._parse_profile_metric(
                text,
                ("following", "mengikuti", "关注", "正在关注"),
            )

        return metrics

    @staticmethod
    def _parse_json_number_field(payload: str, key: str) -> int | None:
        patterns = [
            rf'"{re.escape(key)}"\s*:\s*(\d+)',
            rf'\\"{re.escape(key)}\\"\s*:\s*(\d+)',
            rf'"{re.escape(key)}"\s*:\s*"(\d+)"',
            rf'\\"{re.escape(key)}\\"\s*:\s*\\"(\d+)\\"',
        ]
        for pattern in patterns:
            match = re.search(pattern, payload)
            if not match:
                continue
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None
        return None

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
                    """
                    (el) => {
                      const findScroller = (start) => {
                        let node = start;
                        for (let depth = 0; node && depth < 7; depth += 1, node = node.parentElement) {
                          if (node.scrollHeight > node.clientHeight + 35) return node;
                        }
                        return start;
                      };
                      const target = findScroller(el);
                      const anchors = Array.from(target.querySelectorAll("a[href*='/@']")).map((a) => a.href || a.getAttribute("href") || "");
                      return [
                        Math.round(target.scrollTop),
                        Math.round(target.scrollHeight),
                        Math.round(target.clientHeight),
                        anchors.length,
                        anchors[0] || "",
                        anchors[anchors.length - 1] || "",
                        target.scrollHeight > 0 && target.scrollTop + target.clientHeight >= target.scrollHeight - 24
                      ];
                    }
                    """,
                    timeout=1500,
                )
            except Exception:
                continue
        try:
            return self.page.evaluate(
                """
                () => {
                  const commentText = /(Komen|Comments|评论|Balas|Reply|Lihat|View|yang lalu|ago)/i;
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 240 &&
                      rect.height > 180 &&
                      rect.right > window.innerWidth * 0.52 &&
                      rect.bottom > 120 &&
                      rect.top < window.innerHeight - 20;
                  };
                  const candidates = Array.from(document.querySelectorAll("aside, div, section, main"))
                    .map((el) => {
                      const style = window.getComputedStyle(el);
                      const overflow = `${style.overflowY} ${style.overflow}`;
                      const text = el.innerText || "";
                      const rect = el.getBoundingClientRect();
                      const anchors = Array.from(el.querySelectorAll("a[href*='/@']")).map((a) => a.href || a.getAttribute("href") || "");
                      return { el, overflow, text, rect, anchors };
                    })
                    .filter((item) =>
                      visible(item.el) &&
                      item.el.scrollHeight > item.el.clientHeight + 35 &&
                      /(auto|scroll|overlay)/.test(item.overflow) &&
                      item.anchors.length > 0 &&
                      commentText.test(item.text)
                    )
                    .sort((a, b) => {
                      const ar = a.rect;
                      const br = b.rect;
                      const aRight = ar.left > window.innerWidth * 0.55 ? 1 : 0;
                      const bRight = br.left > window.innerWidth * 0.55 ? 1 : 0;
                      if (aRight !== bRight) return bRight - aRight;
                      return (b.el.scrollHeight - b.el.clientHeight) - (a.el.scrollHeight - a.el.clientHeight);
                    })
                    .map((item) => item.el);
                  const el = candidates[0] || document.scrollingElement || document.documentElement;
                  const anchors = Array.from(el.querySelectorAll("a[href*='/@']")).map((a) => a.href || a.getAttribute("href") || "");
                  return [
                    Math.round(el.scrollTop),
                    Math.round(el.scrollHeight),
                    Math.round(el.clientHeight),
                    anchors.length,
                    anchors[0] || "",
                    anchors[anchors.length - 1] || "",
                    el.scrollHeight > 0 && el.scrollTop + el.clientHeight >= el.scrollHeight - 24
                  ];
                }
                """,
            )
        except Exception:
            return None

    def _scroll_comments(self) -> bool:
        for selector in self.COMMENT_CONTAINER_SELECTORS:
            try:
                container = self.page.locator(selector).first
                changed = container.evaluate(
                    """
                    (el) => {
                      const findScroller = (start) => {
                        let node = start;
                        for (let depth = 0; node && depth < 7; depth += 1, node = node.parentElement) {
                          if (node.scrollHeight > node.clientHeight + 35) return node;
                        }
                        return null;
                      };
                      const target = findScroller(el);
                      if (!target) return false;
                      const before = target.scrollTop;
                      const delta = Math.max(620, Math.round(target.clientHeight * 0.86));
                      target.scrollBy(0, delta);
                      target.dispatchEvent(new WheelEvent("wheel", { deltaY: delta, bubbles: true, cancelable: true }));
                      return Math.abs(target.scrollTop - before) > 2 || before < target.scrollHeight - target.clientHeight - 4;
                    }
                    """,
                    timeout=1500,
                )
                if changed:
                    return True
            except Exception:
                continue
        try:
            scroll_result = self.page.evaluate(
                """
                () => {
                  const commentText = /(Komen|Comments|评论|Balas|Reply|Lihat|View|yang lalu|ago)/i;
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 240 &&
                      rect.height > 180 &&
                      rect.right > window.innerWidth * 0.52 &&
                      rect.bottom > 120 &&
                      rect.top < window.innerHeight - 20;
                  };
                  const candidates = Array.from(document.querySelectorAll("aside, div, section, main"))
                    .map((el) => {
                      const style = window.getComputedStyle(el);
                      const overflow = `${style.overflowY} ${style.overflow}`;
                      const text = el.innerText || "";
                      const rect = el.getBoundingClientRect();
                      const anchors = el.querySelectorAll("a[href*='/@']").length;
                      return { el, overflow, text, rect, anchors };
                    })
                    .filter((item) =>
                      visible(item.el) &&
                      item.el.scrollHeight > item.el.clientHeight + 35 &&
                      /(auto|scroll|overlay)/.test(item.overflow) &&
                      item.anchors > 0 &&
                      commentText.test(item.text)
                    )
                    .sort((a, b) => {
                      const ar = a.rect;
                      const br = b.rect;
                      const aRight = ar.left > window.innerWidth * 0.55 ? 1 : 0;
                      const bRight = br.left > window.innerWidth * 0.55 ? 1 : 0;
                      if (aRight !== bRight) return bRight - aRight;
                      return (b.el.scrollHeight - b.el.clientHeight) - (a.el.scrollHeight - a.el.clientHeight);
                    });
                  const item = candidates[0];
                  if (!item) {
                    const point = { x: Math.round(window.innerWidth * 0.78), y: Math.round(window.innerHeight * 0.58) };
                    return { scrolled: false, fallbackPoint: point };
                  }
                  const el = item.el;
                  const before = el.scrollTop;
                  const delta = Math.max(620, Math.round((el.clientHeight || window.innerHeight) * 0.82));
                  el.scrollBy(0, delta);
                  el.dispatchEvent(new WheelEvent("wheel", { deltaY: delta, bubbles: true, cancelable: true }));
                  const rect = item.rect;
                  return {
                    scrolled: Math.abs(el.scrollTop - before) > 2 || before < el.scrollHeight - el.clientHeight - 4,
                    fallbackPoint: {
                      x: Math.round(Math.max(20, Math.min(window.innerWidth - 20, rect.left + rect.width / 2))),
                      y: Math.round(Math.max(80, Math.min(window.innerHeight - 20, rect.top + rect.height / 2)))
                    }
                  };
                }
                """,
            )
            if isinstance(scroll_result, dict):
                if scroll_result.get("scrolled"):
                    return True
                point = scroll_result.get("fallbackPoint") or {}
                x = int(point.get("x") or 0)
                y = int(point.get("y") or 0)
                if x > 0 and y > 0:
                    self.page.mouse.move(x, y, steps=random.randint(4, 8))
                    self.page.mouse.wheel(0, random.randint(720, 980))
                    return True
        except Exception:
            pass
        self.page.mouse.wheel(0, 900)
        return True

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
        self._close_comments_if_needed()
        self._focus_video_surface()

        for selector in self.NEXT_VIDEO_SELECTORS:
            try:
                button = self.page.locator(selector).first
                button.click(timeout=1800)
                self.page.wait_for_timeout(random.randint(1600, 2600))
                return self._wait_for_video_change(before_key)
            except Exception:
                continue

        actions = [
            lambda: self.page.keyboard.press("ArrowDown"),
            lambda: self.page.keyboard.press("PageDown"),
            lambda: self.page.mouse.wheel(0, random.randint(680, 980)),
            self._swipe_video_feed,
            lambda: self.page.evaluate(
                "() => { window.scrollBy(0, Math.max(700, Math.round(window.innerHeight * 0.82))); }"
            ),
        ]
        for action in actions:
            try:
                action()
                self.page.wait_for_timeout(random.randint(1700, 2800))
                if self._wait_for_video_change(before_key):
                    return True
            except Exception:
                continue
        return False

    def _focus_video_surface(self) -> None:
        try:
            viewport = self.page.viewport_size or {}
            width = int(viewport.get("width") or 1280)
            height = int(viewport.get("height") or 800)
            self.page.mouse.click(
                random.randint(max(40, width // 3), max(60, width * 2 // 3)),
                random.randint(max(40, height // 3), max(60, height * 2 // 3)),
                delay=random.randint(40, 120),
            )
            self.page.wait_for_timeout(random.randint(250, 550))
        except Exception:
            pass

    def _swipe_video_feed(self) -> None:
        viewport = self.page.viewport_size or {}
        width = int(viewport.get("width") or 1280)
        height = int(viewport.get("height") or 800)
        x = random.randint(max(40, width // 3), max(60, width * 2 // 3))
        start_y = random.randint(max(80, height * 2 // 3), max(100, height - 80))
        end_y = random.randint(max(40, height // 4), max(60, height // 2))
        self.page.mouse.move(x, start_y, steps=random.randint(5, 10))
        self.page.mouse.down()
        self.page.mouse.move(x + random.randint(-20, 20), end_y, steps=random.randint(12, 24))
        self.page.mouse.up()

    def _wait_for_video_change(self, before_key: str) -> bool:
        if not before_key:
            return True
        for _ in range(7):
            try:
                current = self._read_video_meta(str(self.task.get("mode", TASK_MODE_RECOMMEND)))
                if self._video_key(current) != before_key:
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(600)
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

