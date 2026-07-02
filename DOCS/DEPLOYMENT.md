# TK AI CRM 全新部署文档

本文档是当前项目唯一完整部署手册。旧版 `API_CONFIGURATION.md`、`PRODUCTION_K3S_DEPLOYMENT.md`、`SERVER_REQUIREMENTS.md` 已清理，后续部署以本文档为准。

## 1. 当前部署目标

系统最终由三部分组成：

- **Windows 客户端**：打包成 EXE 给用户安装。客户端负责登录系统、管理自己的浏览器环境、启动 TikTok 采集任务、查看自己的候选用户和达标用户。
- **Linux 服务端**：部署 API、开发者管理后台、Worker、Redis Cluster。用户客户端通过网络访问 API。
- **外部 MySQL 5.0 数据库**：单独部署在数据库服务器，不放入 K3s 容器。后续正式生产数据应逐步落到 MySQL Repository。

当前实现状态：

- 客户端浏览器环境仍在用户本机运行。
- 服务端已提供登录、注册、邀请码、用户、环境、标签、采集数据查询等 API。
- Redis Cluster 用于多用户视频采集协调，避免多个用户重复采集同一个 TikTok 视频。
- AI 判断当前为预留接口，真实大模型配置后再启用。
- 项目仍保留部分 `runtime` JSON/JSONL 过渡状态，正式生产需要继续迁移到 MySQL。

## 2. 推荐服务器配置

### 测试环境

适合 API 联调、少量客户端测试：

- K3s 节点：1 台
- CPU：2 核
- 内存：4GB
- 磁盘：80GB SSD
- 系统：Ubuntu 22.04 / 24.04 LTS
- MySQL 5.0：可单独一台小型 VM，也可以临时同内网服务器部署，但不放入 K3s

### 第一版生产环境

适合 10-30 个内部用户，浏览器主要在用户电脑本地运行：

- K3s 控制节点：1 台，4 核 CPU，8GB 内存，100GB SSD
- K3s Worker 节点：1 台，8 核 CPU，16GB 内存，200GB SSD
- MySQL 5.0 独立数据库服务器：4 核 CPU，8-16GB 内存，100GB+ SSD
- Redis Cluster：K3s 内 6 个 Pod，每个 Pod 5GB PVC
- AI 服务：单独服务器，后期按模型选择 CPU 或 GPU

### 扩展生产环境

适合 50-200 个用户：

- K3s 控制节点：3 台，4 核 CPU，8GB 内存
- K3s Worker 节点：2-3 台，每台 8-16 核 CPU，32GB 内存，300GB+ SSD
- MySQL：主从或专用数据库 VM，至少 4-8 核 CPU，16-32GB 内存，开启备份
- Redis Cluster：6 Pod 起步，根据任务协调压力增加资源
- AI：独立推理服务，不和 API 共用机器

## 3. 网络与端口要求

| 组件 | 方向 | 端口 | 说明 |
| --- | --- | --- | --- |
| 客户端 -> API | 入站到 K3s Ingress | 80/443 | 推荐生产使用 HTTPS。 |
| API/Worker -> MySQL | 出站到数据库服务器 | 3306 | MySQL 只允许内网访问。 |
| API/Worker -> Redis | K3s 内部 | 6379/16379 | Redis 不暴露公网。 |
| API/Worker -> AI 服务 | 内网 | 按 AI 服务配置 | 后续启用 AI 时使用。 |
| 客户端浏览器 -> TikTok | 用户本机出站 | 443 | 通过用户配置的代理服务器直连。 |

安全要求：

- MySQL、Redis 不要暴露公网。
- API 对外建议只开放 HTTPS。
- 真实 Secret 不要提交到 GitHub。
- 客户端不内置数据库密码、Redis 密码、AI Key。

## 4. 项目部署文件说明

主要文件：

```text
Dockerfile.api
Dockerfile.worker
DEPLOY/K3S/namespace.yaml
DEPLOY/K3S/runtime-pvc.yaml
DEPLOY/K3S/configmap.yaml
DEPLOY/K3S/secret.example.yaml
DEPLOY/K3S/redis-cluster.yaml
DEPLOY/K3S/api-deployment.yaml
DEPLOY/K3S/api-service.yaml
DEPLOY/K3S/worker-deployment.yaml
DEPLOY/K3S/ingress.yaml
DEPLOY/K3S/db-init-job.example.yaml
DEPLOY/K3S/kustomization.yaml
```

说明：

- `secret.example.yaml` 是示例，不参与默认 `kustomization.yaml`，生产不要直接提交真实密码文件。
- `redis-cluster.yaml` 会创建 6 Pod Redis 5.0.14 Cluster，并自动执行初始化 Job。
- `runtime-pvc.yaml` 给 API/Worker 提供共享过渡运行目录。
- `db-init-job.example.yaml` 用于第一次初始化 MySQL 表结构。

## 5. 服务端环境变量

生产环境通过 K3s ConfigMap 和 Secret 注入。

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `production` | 运行环境。 |
| `APP_NAME` | `TK AI CRM` | API 服务名称。 |
| `SERVER_HOST` | `0.0.0.0` | API 容器监听地址。 |
| `SERVER_PORT` | `8000` | API 容器监听端口。 |
| `CLIENT_API_BASE_URL` | `https://api.example.com` | 客户端默认连接的 API 地址。 |
| `DATABASE_URL` | `mysql+pymysql://tk_user:密码@mysql-host:3306/tk_ai_crm?charset=utf8` | 外部 MySQL 5.0 连接串。 |
| `REDIS_PASSWORD` | `Redis真实密码` | Redis Cluster 密码。 |
| `REDIS_URL` | `redis://:密码@tk-ai-crm-redis-0...:6379/0` | Redis 单入口兼容配置。 |
| `REDIS_CLUSTER_NODES` | `redis-0:6379,redis-1:6379,...` | Redis Cluster 节点列表。 |
| `TK_AI_CRM_VIDEO_COORDINATOR` | `redis` | 生产必须为 `redis`。 |
| `TK_AI_CRM_VIDEO_LOCK_TTL_SECONDS` | `14400` | 视频采集锁过期时间。 |
| `TK_AI_CRM_VIDEO_DONE_TTL_SECONDS` | `2592000` | 已完成视频去重保留时间。 |
| `AI_BASE_URL` | `http://ai-server:11434` | 后续 AI 服务地址。 |
| `AI_MODEL` | `minimax-m3:cloud` | 后续 AI 模型名。 |

## 6. 部署前准备

### 6.1 安装 K3s

在 Linux 节点安装 K3s。单节点测试示例：

```bash
curl -sfL https://get.k3s.io | sh -
sudo kubectl get nodes
```

确认本机可以执行：

```bash
kubectl get nodes
kubectl get storageclass
```

如默认没有可用 StorageClass，需要先配置本地存储或云盘存储，否则 Redis PVC 和 runtime PVC 无法创建。

### 6.2 准备镜像仓库

把下面示例中的 `registry.example.local` 替换成你的真实镜像仓库。

```bash
docker build -f Dockerfile.api -t registry.example.local/tk-ai-crm-api:latest .
docker build -f Dockerfile.worker -t registry.example.local/tk-ai-crm-worker:latest .
docker push registry.example.local/tk-ai-crm-api:latest
docker push registry.example.local/tk-ai-crm-worker:latest
```

然后修改：

```text
DEPLOY/K3S/api-deployment.yaml
DEPLOY/K3S/worker-deployment.yaml
DEPLOY/K3S/db-init-job.example.yaml
```

把 `registry.example.local/...` 替换为真实镜像地址。

### 6.3 准备外部 MySQL 5.0

MySQL 不放入 K3s。先在数据库服务器上执行：

```sql
CREATE DATABASE tk_ai_crm DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci;
GRANT ALL PRIVILEGES ON tk_ai_crm.* TO 'tk_user'@'%' IDENTIFIED BY '你的强密码';
FLUSH PRIVILEGES;
```

注意：

- MySQL 5.0 使用 `utf8`，不要写 `utf8mb4`。
- 数据库服务器防火墙只允许 K3s 节点内网 IP 访问 3306。
- 生产环境需要定时备份。

## 7. 修改 K3s 配置

### 7.1 修改 ConfigMap

编辑：

```text
DEPLOY/K3S/configmap.yaml
```

至少修改：

```yaml
CLIENT_API_BASE_URL: "https://你的API域名"
```

如暂时没有域名，可以先用内网地址：

```yaml
CLIENT_API_BASE_URL: "http://192.168.x.x:8000"
```

### 7.2 创建 Secret

不要把真实 Secret 写进 Git。推荐直接用命令创建：

```bash
kubectl apply -f DEPLOY/K3S/namespace.yaml

kubectl -n tk-ai-crm create secret generic tk-ai-crm-secrets \
  --from-literal=DATABASE_URL="mysql+pymysql://tk_user:你的强密码@mysql-host:3306/tk_ai_crm?charset=utf8" \
  --from-literal=REDIS_PASSWORD="Redis强密码" \
  --from-literal=REDIS_URL="redis://:Redis强密码@tk-ai-crm-redis-0.tk-ai-crm-redis-headless.tk-ai-crm.svc.cluster.local:6379/0" \
  --from-literal=AI_BASE_URL="http://ai-server:11434" \
  --from-literal=AI_MODEL="minimax-m3:cloud"
```

如果使用 GitOps，改用 SealedSecret、External Secrets 或集群密钥管理，不要提交真实明文。

### 7.3 修改 Ingress

编辑：

```text
DEPLOY/K3S/ingress.yaml
```

把：

```yaml
host: tk-ai-crm.local
```

改成你的真实域名，例如：

```yaml
host: api.example.com
```

生产环境建议配置 TLS 证书。

## 8. 部署 K3s 服务

确认 Secret 已创建后执行：

```bash
kubectl apply -k DEPLOY/K3S
```

查看资源：

```bash
kubectl -n tk-ai-crm get pods
kubectl -n tk-ai-crm get svc
kubectl -n tk-ai-crm get ingress
kubectl -n tk-ai-crm get pvc
```

Redis Cluster 初始化检查：

```bash
kubectl -n tk-ai-crm get pods -l app=tk-ai-crm-redis
kubectl -n tk-ai-crm logs job/tk-ai-crm-redis-cluster-init
kubectl -n tk-ai-crm exec -it tk-ai-crm-redis-0 -- sh -lc 'redis-cli -a "$REDIS_PASSWORD" cluster info'
```

看到 `cluster_state:ok` 表示 Redis Cluster 初始化成功。

## 9. 初始化数据库

第一次部署时执行：

```bash
kubectl apply -f DEPLOY/K3S/db-init-job.example.yaml
kubectl -n tk-ai-crm logs job/tk-ai-crm-init-db
kubectl -n tk-ai-crm delete job tk-ai-crm-init-db
```

当前 `SCRIPTS/Init_Database.py` 使用 SQLAlchemy `create_all`，适合早期部署。正式生产建议后续改成 Alembic migration。

## 10. 验证 API

### 10.1 健康检查

```bash
kubectl -n tk-ai-crm logs deploy/tk-ai-crm-api
kubectl -n tk-ai-crm port-forward svc/tk-ai-crm-api 8000:8000
```

本机测试：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

如果使用 Ingress：

```bash
curl https://你的API域名/health
```

### 10.2 Swagger

浏览器打开：

```text
https://你的API域名/docs
```

登录接口：

```http
POST /auth/login
```

请求体：

```json
{
  "username": "admin",
  "password": "admin"
}
```

说明：当前开发版本会自动创建 `admin/admin` 和 `client/client` 测试账号。生产上线前必须改为正式管理员初始化流程，并禁用默认密码。

### 10.3 PowerShell 验证

```powershell
$base = "https://你的API域名"
$login = Invoke-RestMethod -Method POST `
  -Uri "$base/auth/login" `
  -ContentType "application/json; charset=utf-8" `
  -Body '{"username":"admin","password":"admin"}'

$headers = @{ Authorization = "Bearer $($login.token)" }
Invoke-RestMethod -Uri "$base/client/bootstrap" -Headers $headers
Invoke-RestMethod -Uri "$base/collection/users?limit=5" -Headers $headers
Invoke-RestMethod -Uri "$base/collection/comment-candidates?limit=5" -Headers $headers
```

## 11. 客户端连接服务端

客户端只需要访问 API，不需要访问 MySQL、Redis、AI。

打包 EXE 前设置：

```env
CLIENT_API_BASE_URL=https://你的API域名
```

如果是内网测试：

```env
CLIENT_API_BASE_URL=http://192.168.x.x:8000
```

客户端登录后会按用户名隔离本地状态：

```text
runtime/client_state/<username>/
```

浏览器环境本地资料也按环境隔离。用户重新打开同一环境时，会保留该环境的 TikTok 登录 Cookie。

## 12. 管理员初始化

生产建议流程：

1. 第一次启动 API 后，用临时 `admin/admin` 登录。
2. 创建正式管理员账号。
3. 停用或删除默认 `admin` 和 `client` 测试账号。
4. 创建邀请码。
5. 客户端用户通过邀请码注册，或由管理员后台直接创建用户。

常用接口：

```text
POST /admin/users
PATCH /admin/users/{username}
POST /admin/invite-codes
GET /admin/users
```

## 13. 多用户去重策略

生产必须开启：

```env
TK_AI_CRM_VIDEO_COORDINATOR=redis
```

工作方式：

1. 客户端环境发现一个 TikTok 视频。
2. 采集评论前先向 Redis 抢占视频锁。
3. 抢占成功才进入评论区采集。
4. 抢占失败说明其他用户正在采集或已采集完成，当前环境直接切换下一个视频。
5. 采集完成后写入已完成标记，避免重复消耗时间。

Redis 只负责短期协调。最终生产数据唯一性仍应由 MySQL 唯一索引保证，例如：

- TikTok 账号唯一。
- 环境归属唯一。
- 采集用户按 TikTokID 去重。
- 已采集视频按视频 ID 去重。

## 14. 运维命令

查看 API：

```bash
kubectl -n tk-ai-crm get deploy tk-ai-crm-api
kubectl -n tk-ai-crm logs deploy/tk-ai-crm-api --tail=200
```

查看 Worker：

```bash
kubectl -n tk-ai-crm get deploy tk-ai-crm-worker
kubectl -n tk-ai-crm logs deploy/tk-ai-crm-worker --tail=200
```

查看 Redis：

```bash
kubectl -n tk-ai-crm get pods -l app=tk-ai-crm-redis
kubectl -n tk-ai-crm exec -it tk-ai-crm-redis-0 -- sh -lc 'redis-cli -a "$REDIS_PASSWORD" cluster nodes'
```

重启 API：

```bash
kubectl -n tk-ai-crm rollout restart deploy/tk-ai-crm-api
kubectl -n tk-ai-crm rollout status deploy/tk-ai-crm-api
```

扩容 Worker：

```bash
kubectl -n tk-ai-crm scale deploy/tk-ai-crm-worker --replicas=2
```

回滚 API：

```bash
kubectl -n tk-ai-crm rollout undo deploy/tk-ai-crm-api
```

## 15. 更新版本流程

1. 本地完成开发和测试。
2. 构建新镜像并推送。
3. 更新 `api-deployment.yaml` 和 `worker-deployment.yaml` 镜像 tag。
4. 执行：

```bash
kubectl apply -k DEPLOY/K3S
kubectl -n tk-ai-crm rollout status deploy/tk-ai-crm-api
kubectl -n tk-ai-crm rollout status deploy/tk-ai-crm-worker
```

5. 验证 `/health`、登录、数据查询、客户端连接。

## 16. 备份策略

必须备份：

- MySQL 数据库。
- Redis PVC，至少在重大版本升级前快照。
- `runtime` PVC，当前仍保存部分过渡状态和日志。

建议：

- MySQL 每天全量备份，每小时增量或 binlog。
- 重要升级前手动备份数据库。
- 不把用户浏览器 Profile 当作服务端核心数据，用户本地环境应由客户端自己维护。

## 17. 上线前检查清单

- [ ] `CLIENT_API_BASE_URL` 已改成真实 API 地址。
- [ ] Ingress 域名已改成真实域名。
- [ ] 已配置 HTTPS。
- [ ] Secret 使用真实密码，但没有提交到 Git。
- [ ] MySQL 只允许内网访问。
- [ ] Redis 不暴露公网。
- [ ] 默认测试账号已停用或替换。
- [ ] `TK_AI_CRM_VIDEO_COORDINATOR=redis`。
- [ ] Redis Cluster `cluster_state:ok`。
- [ ] API `/health` 和 `/ready` 正常。
- [ ] Swagger 可访问。
- [ ] 客户端可以登录。
- [ ] 客户端可以创建环境、添加代理、启动采集。
- [ ] 数据查询可以查看候选用户和达标用户。

## 18. 当前后续生产化任务

部署前可以先运行，但正式生产还需要继续完成：

- 把当前 JSON/JSONL 过渡存储迁移到 MySQL Repository。
- 增加管理员 Web 后台，而不是只依赖 Swagger。
- 完成客户端 EXE 打包和自动更新策略。
- 完成 AI 用户筛选模型配置和角色提示词管理。
- 完成日志集中采集和告警。
- 增加数据库迁移工具，例如 Alembic。

