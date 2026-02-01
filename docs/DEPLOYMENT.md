# MiroFish 部署文档

## 概述

MiroFish 是一个基于知识图谱的模拟环境构建系统，包含以下服务：

- **Backend**: Flask API 服务 (端口 5001)
- **Frontend**: Vue.js 前端应用 (端口 3000)
- **Neo4j**: 图数据库 (端口 7474, 7687)
- **Qdrant**: 向量数据库 (端口 6333, 6334)

## 系统要求

### 硬件要求

- CPU: 4核及以上
- 内存: 8GB 及以上
- 磁盘: 20GB 及以上可用空间

### 软件要求

- Docker: 20.10+
- Docker Compose: 2.0+
- Git: 2.0+

## 快速开始

### 1. 克隆代码

```bash
git clone https://github.com/quchenchen/MiroFish.git
cd MiroFish
```

### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```bash
# ===== 基础配置 =====
APP_PORT=5001
FRONTEND_PORT=3000

# ===== LLM 配置 =====
# 选择 LLM 提供商: aliyun, openai, ollama
LLM_PROVIDER=aliyun
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

# ===== Zep 配置 =====
# true = 使用本地 Neo4j+Qdrant, false = 使用 Zep Cloud
ZEP_USE_LOCAL=true

# Zep Cloud 配置 (当 ZEP_USE_LOCAL=false 时使用)
ZEP_API_KEY=your_zep_api_key
ZEP_URL=https://api.getzep.com

# 本地数据库配置 (当 ZEP_USE_LOCAL=true 时使用)
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password

QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=

# ===== 其他配置 =====
CHUNK_SIZE=500
CHUNK_OVERLAP=50
```

### 3. 启动服务

```bash
# 构建并启动所有服务
docker compose up -d

# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f mirofish
```

### 4. 访问应用

- 前端应用: http://localhost:3000
- 后端 API: http://localhost:5001
- Neo4j 浏览器: http://localhost:7474 (用户名: neo4j, 密码: 见 .env)
- Qdrant 控制台: http://localhost:6333/dashboard

## 服务部署模式

### 模式 1: 本地开发模式

使用本地 Neo4j + Qdrant，适合开发和小规模部署：

```bash
# .env 配置
ZEP_USE_LOCAL=true
NEO4J_PASSWORD=your_password
LLM_API_KEY=your_llm_key
```

### 模式 2: 云端 Zep 模式

使用 Zep Cloud 服务，无需维护数据库：

```bash
# .env 配置
ZEP_USE_LOCAL=false
ZEP_API_KEY=your_zep_key
LLM_API_KEY=your_llm_key
```

## 服务器部署

### 方案 1: Docker Compose 部署（推荐）

适用于单服务器部署。

1. **上传代码到服务器**

```bash
# 在服务器上
git clone https://github.com/quchenchen/MiroFish.git
cd MiroFish
```

2. **配置环境变量**

```bash
cp .env.example .env
nano .env  # 编辑配置
```

3. **启动服务**

```bash
docker compose up -d
```

4. **配置反向代理（可选）**

使用 Nginx 作为反向代理：

```nginx
# /etc/nginx/sites-available/mirofish
server {
    listen 80;
    server_name your-domain.com;

    # 前端
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://localhost:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

启用配置：

```bash
sudo ln -s /etc/nginx/sites-available/mirofish /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 方案 2: Kubernetes 部署

适用于大规模或生产环境部署。

1. **构建镜像**

```bash
docker build -t your-registry.com/mirofish:latest .
docker push your-registry.com/mirofish:latest
```

2. **部署 Kubernetes 资源**

```bash
kubectl apply -f k8s/
```

## 常见问题

### 1. Neo4j 无法连接

检查 Neo4j 服务状态：

```bash
docker compose logs neo4j
docker compose ps neo4j
```

确认密码配置正确（.env 中的 NEO4J_PASSWORD）

### 2. Qdrant 无法连接

检查 Qdrant 服务状态：

```bash
docker compose logs qdrant
docker compose ps qdrant
```

### 3. 前端无法连接后端

确认 API 地址配置正确，检查 `frontend/src/api/index.js` 中的 `baseURL`。

### 4. 构建失败

检查 Docker 日志：

```bash
docker compose logs mirofish
```

重新构建：

```bash
docker compose up -d --build mirofish
```

### 5. 任务轮询 404 错误

这是正常的恢复机制。当服务器重启后，内存中的任务会丢失，前端会自动检查项目状态并恢复。

## 数据备份

### Neo4j 备份

```bash
# 备份
docker exec neo4j neo4j-admin database dump neo4j --to-path=/backups

# 恢复
docker exec neo4j neo4j-admin database load neo4j --from-path=/backups --force
```

### Qdrant 备份

```bash
# 备份快照
curl -X POST http://localhost:6333/collections/mirofish/snapshots

# 下载快照
curl -O http://localhost:6333/collections/mirofish/snapshots/snapshot_name
```

## 监控

### 查看服务状态

```bash
docker compose ps
```

### 查看日志

```bash
# 所有服务
docker compose logs -f

# 特定服务
docker compose logs -f mirofish
docker compose logs -f neo4j
docker compose logs -f qdrant
```

### 健康检查

```bash
# 后端健康检查
curl http://localhost:5001/api/graph/project/list

# Neo4j 健康检查
curl http://localhost:7474

# Qdrant 健康检查
curl http://localhost:6333/health
```

## 更新部署

```bash
# 拉取最新代码
git pull origin main

# 重新构建并启动
docker compose up -d --build

# 清理旧镜像（可选）
docker image prune -f
```

## 卸载

```bash
# 停止并删除容器
docker compose down

# 删除数据卷（谨慎操作！）
docker compose down -v

# 删除镜像
docker rmi mirofish:latest
```

## 安全建议

1. **修改默认密码**: 生产环境务必修改 Neo4j 默认密码
2. **使用 HTTPS**: 生产环境配置 SSL 证书
3. **限制访问**: 使用防火墙限制端口访问
4. **定期备份**: 定期备份 Neo4j 和 Qdrant 数据
5. **更新依赖**: 定期更新 Docker 镜像和依赖包
