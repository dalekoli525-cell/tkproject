# Refactor Checklist

## Phase 1 - Clean Baseline

- [x] Move legacy ADS/CRM code out of the new runtime path.
- [x] Create `APP/SHARED`, `APP/SERVER`, `APP/WORKER`, and `APP/CLIENT`.
- [x] Add Clash multi-port config generator.
- [x] Add Playwright persistent environment manager.
- [x] Add Dockerfiles and k3s baseline manifests.
- [x] Add database models for proxy environments and tasks.
- [x] Add invite-code registration and bearer-session auth baseline.
- [x] Protect admin/client/environment/task/collection API routes.
- [x] Add local worker observer with graceful shutdown.
- [x] Use atomic JSON writes for local server/client state files.
- [ ] Add API persistence layer.
- [ ] Add desktop client screens.

## Phase 2 - Browser Environment

- [ ] Create proxy browser environment.
- [ ] Bind environment to Clash proxy node and local port.
- [ ] Store TikTok username/password.
- [ ] Open browser and preserve login state.
- [ ] Detect TikTok login status.

## Phase 3 - Collection

- [ ] Recommendation-feed collector.
- [ ] Hashtag-search collector.
- [ ] Comment panel extraction.
- [ ] Zero-comment video skip.
- [ ] Tag whitelist/blacklist.
- [ ] AI video filter.
- [ ] AI user filter.

## Phase 4 - Server Integration

- [ ] Persist environments.
- [ ] Persist TikTok accounts.
- [ ] Persist tasks.
- [ ] Persist collected users.
- [ ] Redis task queue.
- [x] Worker boot/shutdown and local task snapshot logs.
- [ ] Distributed worker heartbeat in Redis/database.
