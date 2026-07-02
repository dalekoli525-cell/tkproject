# Server Requirements

## Minimum Test Cluster

Use this only for API development and one low-volume worker:

- 1 k3s server node
- 2 vCPU
- 4 GB RAM
- 80 GB SSD
- Ubuntu 22.04/24.04 LTS
- Docker/containerd through k3s

## Recommended First Production Cluster

For 3-5 concurrent Playwright environments:

- 1 k3s server/control-plane node
  - 4 vCPU
  - 8 GB RAM
  - 100 GB SSD
- 1 worker node
  - 8 vCPU
  - 16 GB RAM
  - 200 GB SSD
- MySQL 5.0 on the same LAN or a dedicated database VM, not in containers
- Redis Cluster inside k3s, six pods with persistent volumes
- AI service on a GPU machine or a separate CPU inference VM

## Production Scale Target

For 10-20 concurrent browser environments:

- 1 control-plane node
  - 4 vCPU
  - 8 GB RAM
  - 100 GB SSD
- 2-3 worker nodes
  - each 8-16 vCPU
  - each 32 GB RAM
  - each 300+ GB SSD
- dedicated database server
  - 4-8 vCPU
  - 16-32 GB RAM
  - SSD with daily backups
- Redis Cluster inside k3s
  - 6 pods minimum
  - 100m-500m CPU per pod for early production
  - 128-512 MB RAM per pod for early production
  - persistent volume per pod
- dedicated AI server
  - CPU mode: 8+ vCPU, 32 GB RAM
  - GPU mode: NVIDIA GPU with 12 GB+ VRAM

## Network Requirements

- Workers need outbound access to TikTok through the configured direct proxy
  servers or through the host network when `DIRECT` is selected.
- API needs LAN access to database, Redis, and AI service.
- MySQL 5.0 must run outside k3s on a database VM or physical server.
- Redis is exposed only inside the k3s namespace through the Redis Cluster services.
- Client needs access to API ingress.
- Keep database and Redis private; do not expose them directly to the internet.

## Browser Worker Notes

Playwright workers are memory-heavy. Plan roughly:

- 1 browser environment: 700 MB - 1.5 GB RAM
- 5 browser environments: 6 GB - 10 GB RAM
- 10 browser environments: 14 GB - 24 GB RAM

Start with low concurrency, measure memory, then raise `WORKER_CONCURRENCY`.
