# Deployment

This project is designed for k3s:

- API pods expose task/account/environment endpoints.
- Worker pods run Playwright collection jobs.
- MySQL/PostgreSQL, Redis, and AI services are configured by URL.
- Browser profiles should use persistent volumes when worker state must survive
  restarts.

First deployment command:

```powershell
kubectl apply -k DEPLOY/K3S
```

Before production, copy `DEPLOY/K3S/secret.example.yaml` to a private secret
manifest or create the secret with `kubectl create secret generic`.
