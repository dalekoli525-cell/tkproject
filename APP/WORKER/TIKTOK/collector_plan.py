"""TikTok collection state-machine definitions.

The concrete Playwright implementation will be built on this stable workflow.
Keeping the state names explicit makes worker logs and UI progress predictable.
"""

from enum import StrEnum


class CollectState(StrEnum):
    START_BROWSER = "START_BROWSER"
    OPEN_TIKTOK = "OPEN_TIKTOK"
    WAIT_RENDER = "WAIT_RENDER"
    CHECK_LOGIN = "CHECK_LOGIN"
    OPEN_RECOMMEND_OR_TAG = "OPEN_RECOMMEND_OR_TAG"
    READ_VIDEO_META = "READ_VIDEO_META"
    CHECK_TAG_RULES = "CHECK_TAG_RULES"
    CHECK_COMMENT_COUNT = "CHECK_COMMENT_COUNT"
    AI_VIDEO_FILTER = "AI_VIDEO_FILTER"
    OPEN_COMMENTS = "OPEN_COMMENTS"
    COLLECT_COMMENT_USERS = "COLLECT_COMMENT_USERS"
    SAVE_RESULTS = "SAVE_RESULTS"
    NEXT_VIDEO = "NEXT_VIDEO"
    FINISHED = "FINISHED"


COLLECT_WORKFLOW = [
    CollectState.START_BROWSER,
    CollectState.OPEN_TIKTOK,
    CollectState.WAIT_RENDER,
    CollectState.CHECK_LOGIN,
    CollectState.OPEN_RECOMMEND_OR_TAG,
    CollectState.READ_VIDEO_META,
    CollectState.CHECK_TAG_RULES,
    CollectState.CHECK_COMMENT_COUNT,
    CollectState.AI_VIDEO_FILTER,
    CollectState.OPEN_COMMENTS,
    CollectState.COLLECT_COMMENT_USERS,
    CollectState.SAVE_RESULTS,
    CollectState.NEXT_VIDEO,
    CollectState.FINISHED,
]

