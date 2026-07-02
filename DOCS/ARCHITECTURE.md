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
      -> external MySQL 5.0 database
      -> Redis Cluster in k3s
      -> AI service
  -> Worker status/logs through API

Worker
  -> Playwright persistent browser profile
  -> direct proxy server selected by environment
  -> TikTok web
```

## Proxy Model

Each browser environment stores an independent Playwright persistent profile
and selects one proxy server string. Proxy nodes can be reused by multiple
environments when the operator chooses to do so.

```text
env 001 -> http://45.123.102.122:44001 + username/password
env 002 -> socks5://proxy.example.com:1080 + username/password
env 003 -> DIRECT
```

Playwright receives the parsed proxy directly at browser launch:

```python
proxy={
    "server": "http://45.123.102.122:44001",
    "username": "proxy-user",
    "password": "proxy-password",
}
```

Supported input formats include `host:port:user:pass`,
`http://host:port:user:pass`, `http://user:pass@host:port`, and
`socks5://host:port:user:pass`.

## Collection State Machine

```text
START_BROWSER
OPEN_TIKTOK
WAIT_RENDER
CHECK_LOGIN
OPEN_RECOMMEND_OR_TAG
READ_VIDEO_META
CLAIM_VIDEO_BEFORE_COMMENTS
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

## Video Coordination

Before an environment opens the comment panel, it must claim the current video.
This prevents multiple users or environments from collecting the same video's
comment users at the same time.

```text
read video_id
  -> check video_done
  -> SET video_lock:{video_id} owner NX EX 14400
      success: collect the comments
      failed: skip to the next video
  -> after full comment collection, write video_done:{video_id}
  -> release video_lock:{video_id}
```

Local desktop testing uses `runtime/coordination/video_coordination.json` as a
project-wide fallback. Production sets `TK_AI_CRM_VIDEO_COORDINATOR=redis` so
all users, environments, and workers coordinate through Redis Cluster. MySQL
unique indexes remain the final protection for stored videos and users.
