# TK AI CRM Rewritten Architecture

## Scope

The rewritten project keeps only the TikTok collection product:

- proxy browser environments
- TikTok account login state
- recommendation-feed collection
- hashtag video collection
- comment-user collection
- AI video/user filtering
- tag performance statistics

The old ADS, DM outreach, CRM dashboard, campaign, and message automation code
has been moved to `legacy/` and is not part of the new baseline.

## Runtime Components

```text
Desktop Client
  -> API Server
      -> Database
      -> Redis queue
      -> AI service
  -> Worker status/logs through API

Worker
  -> Playwright persistent browser profile
  -> Clash Verge / mihomo per-environment local port
  -> TikTok web
```

## Proxy Model

Each browser environment gets its own local Clash listener port:

```text
env 001 -> 127.0.0.1:7901 -> ENV_001_PROXY -> Residential-1
env 002 -> 127.0.0.1:7902 -> ENV_002_PROXY -> Residential-2
```

Playwright uses the local port:

```python
proxy={"server": "http://127.0.0.1:7901"}
```

Clash uses `IN-PORT` routing to choose the correct proxy group.

## Collection State Machine

```text
START_BROWSER
OPEN_TIKTOK
WAIT_RENDER
CHECK_LOGIN
OPEN_RECOMMEND_OR_TAG
READ_VIDEO_META
CHECK_TAG_RULES
CHECK_COMMENT_COUNT
AI_VIDEO_FILTER
OPEN_COMMENTS
COLLECT_COMMENT_USERS
SAVE_RESULTS
NEXT_VIDEO
FINISHED
```

Videos with zero comments are skipped. Like-user list collection is not part of
the reliable baseline because TikTok does not expose a stable public list of
users who liked a video.

