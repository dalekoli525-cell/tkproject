# Deployment

This project is designed for k3s:

- API pods expose task/account/environment endpoints.
- Worker pods run Playwright collection jobs.
- MySQL 5.0 is deployed separately on a non-container database host and is
  configured by `DATABASE_URL`.
- Redis runs as a six-pod Redis Cluster inside k3s.
- AI services are configured by URL.
- Browser profiles should use persistent volumes when worker state must survive
  restarts.

First deployment command:

```powershell
kubectl apply -f DEPLOY/K3S/namespace.yaml
kubectl -n tk-ai-crm create secret generic tk-ai-crm-secrets `
  --from-literal=DATABASE_URL="mysql+pymysql://tk_user:change-me@mysql5.example.local:3306/tk_ai_crm?charset=utf8" `
  --from-literal=REDIS_PASSWORD="change-me" `
  --from-literal=REDIS_URL="redis://:change-me@tk-ai-crm-redis-0.tk-ai-crm-redis-headless.tk-ai-crm.svc.cluster.local:6379/0" `
  --from-literal=AI_BASE_URL="http://ollama.example.local:11434" `
  --from-literal=AI_MODEL="minimax-m3:cloud"
kubectl apply -k DEPLOY/K3S
```

`DEPLOY/K3S/secret.example.yaml` is only a template. It is intentionally not
included by `kustomization.yaml` for production safety.

Redis Cluster is initialized by `DEPLOY/K3S/redis-cluster.yaml`. If you change
`REDIS_PASSWORD` after the cluster has been created, recreate the Redis
StatefulSet PVCs and rerun `tk-ai-crm-redis-cluster-init`; do not rotate it on a
live cluster without a planned migration.

Full Chinese production notes:

```text
DOCS/PRODUCTION_K3S_DEPLOYMENT.md
DOCS/API_CONFIGURATION.md
```

Optional first database initialization:

```powershell
kubectl apply -f DEPLOY/K3S/db-init-job.example.yaml
kubectl -n tk-ai-crm logs job/tk-ai-crm-init-db
kubectl -n tk-ai-crm delete job tk-ai-crm-init-db
```
