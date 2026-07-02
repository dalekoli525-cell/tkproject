# TK AI CRM 部署入口

本目录只保留部署清单和快速入口。完整部署步骤统一查看：

```text
DOCS/DEPLOYMENT.md
```

## 当前部署结构

- API：`DEPLOY/K3S/api-deployment.yaml`
- Worker：`DEPLOY/K3S/worker-deployment.yaml`
- Redis Cluster：`DEPLOY/K3S/redis-cluster.yaml`
- Runtime PVC：`DEPLOY/K3S/runtime-pvc.yaml`
- ConfigMap：`DEPLOY/K3S/configmap.yaml`
- Secret 示例：`DEPLOY/K3S/secret.example.yaml`
- Ingress：`DEPLOY/K3S/ingress.yaml`
- 数据库初始化 Job 示例：`DEPLOY/K3S/db-init-job.example.yaml`

## 快速部署顺序

1. 准备外部 MySQL 5.0。
2. 构建并推送 API / Worker 镜像。
3. 修改 `DEPLOY/K3S/configmap.yaml` 和 `DEPLOY/K3S/ingress.yaml`。
4. 使用 `kubectl create secret generic` 创建真实 Secret。
5. 执行：

```bash
kubectl apply -k DEPLOY/K3S
```

6. 第一次部署时执行数据库初始化 Job：

```bash
kubectl apply -f DEPLOY/K3S/db-init-job.example.yaml
kubectl -n tk-ai-crm logs job/tk-ai-crm-init-db
kubectl -n tk-ai-crm delete job tk-ai-crm-init-db
```

## 注意

- 不要把真实密码写入 `secret.example.yaml` 后提交。
- MySQL 不部署到 K3s，必须作为外部数据库服务。
- Redis Cluster 部署在 K3s 内部，不对公网开放。
- 生产部署必须启用 `TK_AI_CRM_VIDEO_COORDINATOR=redis`。
