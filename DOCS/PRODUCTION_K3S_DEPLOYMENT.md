# TK AI CRM 生产部署文档

本文档使用 UTF-8 编码，中文可直接写入源码、配置和文档。PowerShell 终端偶尔显示乱码不代表文件编码错误，验证以 Python 编译、接口测试和实际文件 UTF-8 内容为准。

## 1. 最终交付形态

系统分成两部分：

- 用户客户端：Windows exe 安装包，只包含登录、环境管理、代理浏览器启动、任务配置、结果查询。
- 服务端：API、开发者管理后台、Worker 和 Redis Cluster 部署在 Linux/K3s 集群；MySQL 5.0 单独部署在数据库服务器，不使用容器。

客户端不直接暴露数据库地址，不展示数据库原始数据。客户端只通过 API 获取当前登录用户允许看到的数据。

## 2. 推荐服务器配置

小规模内测，10-30 个用户：

- K3s 控制节点：4 核 CPU，8GB 内存，100GB SSD
- Worker 节点：8 核 CPU，16GB 内存，200GB SSD
- MySQL 5.0 独立数据库服务器：2 核 CPU，4GB 内存，100GB SSD
- Redis Cluster：K3s 内 6 个 Pod，每个 Pod 建议 100m-500m CPU，128-512MB 内存，5GB PVC

生产规模，50-200 个用户：

- K3s 控制节点：3 台，4 核 CPU，8GB 内存
- Worker 节点：2-5 台，每台 8-16 核 CPU，32GB 内存
- MySQL 5.0 独立数据库服务器：主从或专用 VM，至少 4 核 CPU，16GB 内存
- Redis Cluster：K3s 内 6 个 Pod 起步，按任务队列压力扩容资源
- 对象存储或共享存储：保存导出文件、日志归档、备份文件

注意：如果 TikTok 浏览器实际运行在用户本机，K3s worker 不需要承担大量浏览器资源。如果后续改成服务器端统一跑浏览器，worker 节点资源要按浏览器并发数扩容。

## 3. 服务端组件

K3s 中建议部署：

- `tk-ai-crm-api`：FastAPI 服务，提供登录、环境、任务、采集数据、管理后台 API。
- `tk-ai-crm-worker`：后台任务 worker，后续用于服务器端任务调度、AI 筛选、数据同步。
- MySQL 5.0：独立部署在非容器数据库服务器，存储用户、邀请码、TikTok 账号池、任务、采集结果。
- Redis Cluster：部署在 K3s 容器中，用于任务队列、分布式锁、任务状态缓存。
- AI 服务：Ollama、Minimax 或其他模型服务，API 通过配置接入。

当前仓库已有：

- `Dockerfile.api`
- `Dockerfile.worker`
- `DEPLOY/K3S`

## 4. 构建镜像

在项目根目录执行：

```powershell
docker build -f Dockerfile.api -t registry.example.local/tk-ai-crm-api:latest .
docker build -f Dockerfile.worker -t registry.example.local/tk-ai-crm-worker:latest .
docker push registry.example.local/tk-ai-crm-api:latest
docker push registry.example.local/tk-ai-crm-worker:latest
```

将 `registry.example.local` 替换为你的私有镜像仓库地址。

## 5. 创建 K3s Secret

生产环境不要直接使用 `secret.example.yaml`。先创建命名空间：

```powershell
kubectl apply -f DEPLOY/K3S/namespace.yaml
```

先在外部 MySQL 5.0 数据库服务器上创建数据库和账号，MySQL 不部署到 K3s：

```sql
CREATE DATABASE tk_ai_crm DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci;
GRANT ALL PRIVILEGES ON tk_ai_crm.* TO 'tk_user'@'%' IDENTIFIED BY '真实密码';
FLUSH PRIVILEGES;
```

再创建真实密钥：

```powershell
kubectl -n tk-ai-crm create secret generic tk-ai-crm-secrets `
  --from-literal=DATABASE_URL="mysql+pymysql://tk_user:真实密码@mysql5.example.local:3306/tk_ai_crm?charset=utf8" `
  --from-literal=REDIS_PASSWORD="Redis真实密码" `
  --from-literal=REDIS_URL="redis://:Redis真实密码@tk-ai-crm-redis-0.tk-ai-crm-redis-headless.tk-ai-crm.svc.cluster.local:6379/0" `
  --from-literal=AI_BASE_URL="http://ollama.example.local:11434" `
  --from-literal=AI_MODEL="minimax-m3:cloud"
```

如使用 GitOps，不要提交真实 secret；应使用 SealedSecret、External Secrets 或集群内密钥管理。

## 6. K3s 服务配置说明

当前 `DEPLOY/K3S` 包含：

- `namespace.yaml`：创建 `tk-ai-crm` 命名空间。
- `configmap.yaml`：非敏感运行配置。
- `redis-cluster.yaml`：K3s 内 Redis 5.0.14 六节点集群，3 主 3 从。
- `runtime-pvc.yaml`：过渡期运行状态持久化卷，挂载到 `/app/runtime`。
- `api-deployment.yaml`：API 服务部署，默认 2 副本。
- `api-service.yaml`：API ClusterIP Service。
- `worker-deployment.yaml`：后台 worker 部署。
- `ingress.yaml`：API 入口域名示例。
- `secret.example.yaml`：Secret 示例，不参与默认 kustomize。
- `db-init-job.example.yaml`：数据库初始化 Job 示例，手动运行。

`configmap.yaml` 中需要按实际环境调整：

```yaml
CLIENT_API_BASE_URL: "https://你的API域名"
WORKER_CONCURRENCY: "2"
TIKTOK_RENDER_WAIT_SECONDS: "30"
PROXY_PORT_START: "7901"
BROWSER_PROFILE_ROOT: "/app/runtime/profiles"
REDIS_CLUSTER_NODES: "tk-ai-crm-redis-0...:6379,tk-ai-crm-redis-1...:6379,..."
TK_AI_CRM_VIDEO_COORDINATOR: "redis"
TK_AI_CRM_VIDEO_LOCK_TTL_SECONDS: "14400"
TK_AI_CRM_VIDEO_DONE_TTL_SECONDS: "2592000"
```

代理服务器由客户端或管理后台保存为 Playwright 可直接使用的节点，例如
`45.123.102.122:44001:用户名:密码`、`http://用户名:密码@host:port` 或
`socks5://host:port:用户名:密码`。新版本由 Playwright 在启动浏览器时直接
连接代理服务器。

如果 API 只提供给内网客户端，Ingress 可以绑定内网域名或只开放内网负载均衡。

## 7. 部署 K3s

确认 secret 已创建后执行：

```powershell
kubectl apply -k DEPLOY/K3S
```

Redis Cluster 初始化由 `tk-ai-crm-redis-cluster-init` Job 自动执行。检查 Redis：

```powershell
kubectl -n tk-ai-crm get pods -l app=tk-ai-crm-redis
kubectl -n tk-ai-crm logs job/tk-ai-crm-redis-cluster-init
kubectl -n tk-ai-crm exec -it tk-ai-crm-redis-0 -- sh -lc 'redis-cli -a "$REDIS_PASSWORD" cluster info'
```

检查状态：

```powershell
kubectl -n tk-ai-crm get pods
kubectl -n tk-ai-crm get svc
kubectl -n tk-ai-crm logs deploy/tk-ai-crm-api
```

健康检查：

```powershell
curl http://你的域名或IP/health
curl http://你的域名或IP/ready
```

如果是第一次部署 MySQL 5.0 表结构，先确认外部 MySQL 已创建数据库和用户，然后手动运行初始化 Job：

```powershell
kubectl apply -f DEPLOY/K3S/db-init-job.example.yaml
kubectl -n tk-ai-crm logs job/tk-ai-crm-init-db
kubectl -n tk-ai-crm delete job tk-ai-crm-init-db
```

当前 `Init_Database.py` 使用 SQLAlchemy `create_all`，适合早期部署。正式生产建议改成 Alembic migration。

MySQL 5.0 注意事项：

- 不在 K3s 内部署 MySQL 容器，K3s 只通过 `DATABASE_URL` 访问外部数据库。
- MySQL 5.0 不支持 `utf8mb4`，连接串使用 `?charset=utf8`，中文可正常存储，但四字节 Emoji 可能无法写入。
- 数据库建议使用 InnoDB，并设置每日备份。
- 数据库和 K3s 节点必须在同一内网或专线网络内，不要把 MySQL 端口直接暴露到公网。

## 8. 数据库设计要求

生产数据库必须保证以下唯一性：

- `app_users.username` 唯一。
- `tiktok_accounts.username` 全局唯一。
- `browser_environments.owner_username + browser_environments.code` 联合唯一。
- 每个 TikTok 账号只能分配给一个用户或一个环境。
- 管理员后台可以看到所有用户和所有账号分配，普通用户只能看到自己的环境和查询结果。

当前代码已经加入基础约束：

- SQLAlchemy 模型中 `TikTokAccount.username` 是唯一字段。
- SQLAlchemy 模型中 `BrowserEnvironment.owner_username + code` 是联合唯一。
- 当前 JSON 过渡版环境 API 已增加 TikTok 账号重复绑定校验，重复绑定返回 HTTP `409`。

后续切换到正式 MySQL Repository 时，要把唯一分配放在数据库事务里完成，推荐流程：

1. 用户请求创建环境或绑定 TikTok 账号。
2. API 开启数据库事务。
3. 查询 `tiktok_accounts.username` 是否已存在且已分配。
4. 如果已分配给其他用户，直接返回 `409`。
5. 如果未分配，写入 `assigned_owner_username`、`environment_code`、`assigned_at`。
6. 提交事务。

Redis 可以辅助做短锁，但最终唯一性必须由 MySQL 唯一索引保证。

## 9. 任务分配规则

任务环节必须满足：

- 一个用户只能领取自己名下的环境任务。
- 一个 TikTok 账号不能同时被两个用户使用。
- 同一个 TikTok 视频在打开评论区前必须先通过 Redis 抢占，抢占失败的环境直接切换下一个视频。
- 视频评论区全量采集完成后写入 `video_done`，后续其他用户刷到同一视频直接跳过。
- 一个环境启动后使用独立 Playwright profile，cookie 保存在该环境 profile 中。
- 用户重复打开同一环境时复用原 profile，不需要重复登录。
- 如果环境绑定的 TikTok 账号变更，旧 profile 必须备份或重建，防止账号串号。
- 管理员后台可以暂停、关闭、回收异常任务。

当前客户端已拆出 `Profile_State_Service.py`，用于维护 profile 标记、保留 cookie、换账号时备份旧 profile。

## 10. 开发者管理后台

开发者后台需要具备：

- 用户管理：创建、禁用、查看用户。
- 邀请码管理：创建 6 位邀请码、设置角色、设置可用次数。
- TikTok 账号池：添加账号、查看分配状态、回收账号。
- 代理节点管理：添加、禁用、分组代理节点。
- 标签分类管理：增删改查标签类，每类多个标签。
- 任务管理：查看任务状态、暂停任务、重试任务。
- 数据查询：按用户、TikTok ID、任务、时间范围查询采集结果。

普通客户端用户不直接访问数据库，也不看到其他用户的数据。

## 11. Windows 客户端 exe 打包

客户端入口：

```powershell
.\.venv\Scripts\python.exe SCRIPTS\Run_Client.py
```

建议使用 PyInstaller 打包：

```powershell
.\.venv\Scripts\pip.exe install pyinstaller
.\.venv\Scripts\pyinstaller.exe `
  --noconfirm `
  --clean `
  --name TK_AI_CRM_Client `
  --windowed `
  --add-data "APP;APP" `
  --add-data "SCRIPTS;SCRIPTS" `
  SCRIPTS\Run_Client.py
```

输出目录：

```text
dist\TK_AI_CRM_Client
```

后续可再用 Inno Setup 或 NSIS 制作安装包。

客户端安装包需要提供：

- API 地址配置。
- 本地 Playwright/Chromium 运行环境。
- 本地 profile 存储目录。
- 用户登录入口。

客户端不应内置数据库密码、Redis 密码、AI 密钥。

## 12. 发布前验证

每次发布前执行：

```powershell
.\.venv\Scripts\python.exe SCRIPTS\Validate_Production.py
```

必须看到：

```text
offline validation passed
production validation passed
```

验证内容包括：

- Python 模块编译。
- API 健康检查。
- 注册/登录。
- 环境创建。
- 环境列表不泄露 TikTok 密码。
- TikTok 账号重复绑定返回 `409`。
- 标签解析支持中文。
- profile 换账号会触发备份。
- 任务命令可以写入和暂停。

## 13. 下一步生产化工作

还需要继续完成：

- 把当前 JSON 过渡状态迁移到 MySQL Repository。
- 增加 Alembic 数据库迁移。
- 增加管理后台页面。
- 增加服务端任务队列。
- 增加用户端 API 地址配置界面。
- 增加 exe 自动更新或版本检查。
- 增加 K3s 持久化存储、备份和日志采集。
