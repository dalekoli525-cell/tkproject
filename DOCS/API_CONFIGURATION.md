# TK AI CRM API 配置与部署说明

本文档用于后续把 API、Redis、Worker 部署到服务器，并让 Windows 客户端通过网络访问服务。所有配置文件和命令都按 UTF-8 中文保存。

## 1. 服务组成

- **客户端**：Windows EXE，用户本地运行。负责创建浏览器环境、登录 TikTok、发起采集任务、查看自己的数据。
- **API 服务**：FastAPI，提供登录、注册、环境、标签、采集数据、管理后台接口。
- **Worker 服务**：后续服务器侧后台任务入口。当前 TikTok 浏览器采集仍主要在客户端本地 Playwright 环境运行。
- **MySQL 5.0**：单独部署在数据库服务器，不放入容器。
- **Redis Cluster 5.0.14**：在 K3s 内部署 6 节点集群，用于多用户视频去重和任务协调。
- **AI 服务**：后续接入大模型时通过 `AI_BASE_URL` 和 `AI_MODEL` 配置。

## 2. API 环境变量

API 和 Worker 共用 `APP/SHARED/settings.py` 读取配置，生产环境通过 K3s Secret / ConfigMap 注入。

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `production` | 运行环境标记。 |
| `APP_NAME` | `TK AI CRM` | FastAPI 标题。 |
| `DATABASE_URL` | `mysql+pymysql://tk_user:密码@mysql-host:3306/tk_ai_crm?charset=utf8` | MySQL 5.0 连接串。 |
| `REDIS_URL` | `redis://:密码@tk-ai-crm-redis-0...:6379/0` | Redis 单入口兼容配置。 |
| `REDIS_CLUSTER_NODES` | `redis-0:6379,redis-1:6379,...` | Redis Cluster 节点列表。 |
| `REDIS_PASSWORD` | `真实Redis密码` | Redis 集群密码。 |
| `TK_AI_CRM_VIDEO_COORDINATOR` | `redis` | 生产环境必须设为 `redis`，避免多用户重复采集同一视频。 |
| `CLIENT_API_BASE_URL` | `https://api.example.com` | 客户端默认访问的 API 地址。 |
| `SERVER_HOST` | `0.0.0.0` | API 监听地址。 |
| `SERVER_PORT` | `8000` | API 监听端口。 |
| `AI_BASE_URL` | `http://ollama.local:11434` | 后续 AI 服务地址。 |
| `AI_MODEL` | `minimax-m3:cloud` | 后续 AI 模型名。 |

## 3. 本地开发启动

```powershell
cd C:\TK_AI_CRM_V2
.\.venv\Scripts\python.exe SCRIPTS\Run_Api_Server.py
```

默认地址：

- API：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## 4. 默认测试账号

当前开发版本首次启动会自动创建两个本地测试账号：

| 账号 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `admin` | 管理员 |
| `client` | `client` | 普通客户端用户 |

生产部署时必须替换为数据库迁移或管理员初始化流程，并修改默认密码策略。

## 5. 登录与令牌

登录接口：

```http
POST /auth/login
Content-Type: application/json

{
  "username": "client",
  "password": "client"
}
```

返回：

```json
{
  "token": "Bearer令牌",
  "user": {
    "username": "client",
    "role": "operator",
    "is_active": true
  }
}
```

后续请求在 Header 中携带：

```http
Authorization: Bearer <token>
```

PowerShell 测试：

```powershell
$login = Invoke-RestMethod -Method POST `
  -Uri http://127.0.0.1:8000/auth/login `
  -ContentType application/json `
  -Body '{"username":"client","password":"client"}'

$headers = @{ Authorization = "Bearer $($login.token)" }
Invoke-RestMethod -Uri http://127.0.0.1:8000/client/bootstrap -Headers $headers
```

## 6. 用户注册与邀请码

客户端开放注册时必须提交 6 位邀请码：

```http
POST /auth/register
```

```json
{
  "username": "new_user",
  "password": "123456",
  "invite_code": "123456"
}
```

管理员创建邀请码：

```powershell
.\.venv\Scripts\python.exe SCRIPTS\Create_Invite_Code.py 123456 operator 10
```

管理员也可以直接通过 API 创建用户：

```http
POST /admin/users
Authorization: Bearer <admin-token>
```

```json
{
  "username": "client002",
  "password": "client002",
  "role": "operator",
  "is_active": true
}
```

## 7. 客户端可用接口

普通用户接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/auth/login` | 登录。 |
| `POST` | `/auth/register` | 邀请码注册。 |
| `GET` | `/client/bootstrap` | 获取用户可见配置：代理节点、标签分类、任务模板。 |
| `GET` | `/environments` | 查询当前用户环境。 |
| `POST` | `/environments` | 创建当前用户环境。 |
| `DELETE` | `/environments/{code}` | 删除当前用户环境。 |
| `GET` | `/collection/users` | 查询达标用户，可按 TikTokID 模糊搜索。 |
| `GET` | `/collection/comment-candidates` | 查询候选用户，可按 TikTokID 模糊搜索。 |
| `GET` | `/collection/logs` | 查询任务日志。 |

管理员接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/admin/users` | 查看用户。 |
| `POST` | `/admin/users` | 创建用户。 |
| `PATCH` | `/admin/users/{username}` | 更新用户状态、角色、密码。 |
| `GET` | `/admin/invite-codes` | 查看邀请码。 |
| `POST` | `/admin/invite-codes` | 创建或更新邀请码。 |
| `GET` | `/admin/config/proxy-nodes` | 查看服务端代理节点。 |
| `POST` | `/admin/config/proxy-nodes` | 添加服务端代理节点。 |
| `GET` | `/admin/config/tag-classes` | 查看标签分类。 |
| `POST` | `/admin/config/tag-classes` | 新增或修改标签分类。 |
| `DELETE` | `/admin/config/tag-classes/{name}` | 删除标签分类。 |

## 8. 客户端指向服务器 API

开发阶段客户端读取 `CLIENT_API_BASE_URL`，默认是 `http://127.0.0.1:8000`。

打包 EXE 前建议在 `.env` 或安装包配置中写入：

```env
CLIENT_API_BASE_URL=https://api.example.com
```

客户端登录成功后会把会话保存到：

```text
runtime/client_state/client_session.json
```

普通用户的数据目录按用户名隔离：

```text
runtime/client_state/<username>/
```

## 9. K3s 部署顺序

1. 准备外部 MySQL 5.0，创建数据库和账号。
2. 构建并推送镜像。
3. 创建 K3s namespace。
4. 创建 Secret，写入 MySQL、Redis、AI 配置。
5. 部署 Redis Cluster。
6. 部署 API、Worker、Service、Ingress。
7. 运行数据库初始化 Job。
8. 用 Swagger 或 PowerShell 登录测试。

示例：

```powershell
kubectl apply -f DEPLOY/K3S/namespace.yaml

kubectl -n tk-ai-crm create secret generic tk-ai-crm-secrets `
  --from-literal=DATABASE_URL="mysql+pymysql://tk_user:真实密码@mysql-host:3306/tk_ai_crm?charset=utf8" `
  --from-literal=REDIS_PASSWORD="Redis真实密码" `
  --from-literal=REDIS_URL="redis://:Redis真实密码@tk-ai-crm-redis-0.tk-ai-crm-redis-headless.tk-ai-crm.svc.cluster.local:6379/0" `
  --from-literal=AI_BASE_URL="http://ollama.example.local:11434" `
  --from-literal=AI_MODEL="minimax-m3:cloud"

kubectl apply -k DEPLOY/K3S
```

## 10. 部署后验证

```powershell
kubectl -n tk-ai-crm get pods
kubectl -n tk-ai-crm logs deploy/tk-ai-crm-api
kubectl -n tk-ai-crm get svc
```

Redis Cluster：

```powershell
kubectl -n tk-ai-crm exec -it tk-ai-crm-redis-0 -- sh -lc 'redis-cli -a "$REDIS_PASSWORD" cluster info'
```

API：

```powershell
Invoke-RestMethod https://api.example.com/health
```

## 11. 当前实现边界

- 采集浏览器目前由客户端本地 Playwright/独立 Chrome 环境启动，服务器主要负责账号、配置、数据和协调。
- 当前开发版本部分接口仍使用 `runtime` 下 JSON/JSONL 作为过渡存储；正式生产需要逐步切换到 MySQL Repository。
- 多用户避免重复视频采集已经预留 Redis 协调器，生产环境必须启用 `TK_AI_CRM_VIDEO_COORDINATOR=redis`。
- AI 判断当前为模拟通过，后续选定大模型后再接入真实判断。

