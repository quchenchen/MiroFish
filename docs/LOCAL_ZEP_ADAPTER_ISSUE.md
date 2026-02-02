# Issue: 本地 ZEP 适配器实现

## 标题
**feat(zep): add local adapter using Neo4j + Qdrant**

## 概述

已实现使用本地部署的 **Neo4j**（图数据库）+ **Qdrant**（向量数据库）替代 Zep Cloud 服务，实现完全本地化的知识图谱存储和语义搜索功能。

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     ZepClient (本地适配器)                     │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐   │
│  │ GraphService  │  │ VectorService │  │  MemoryMgr    │   │
│  │   (Neo4j)     │  │   (Qdrant)    │  │               │   │
│  └───────────────┘  └───────────────┘  └───────────────┘   │
└─────────────────────────────────────────────────────────────┘
           │                     │
           ▼                     ▼
    ┌─────────────┐       ┌──────────────┐
    │   Neo4j     │       │   Qdrant     │
    │ 图数据库     │       │  向量数据库   │
    │ bolt://7687 │       │  http://6333 │
    └─────────────┘       └──────────────┘
```

---

## 新增文件

| 文件 | 行数 | 描述 |
|------|------|------|
| `backend/app/services/zep_adapter/__init__.py` | ~44 | 适配器入口，导出兼容接口 |
| `backend/app/services/zep_adapter/client.py` | ~920 | ZepClient 本地实现，包含工具服务和实体读取器 |
| `backend/app/services/zep_adapter/graph.py` | ~870 | Neo4j 图服务，节点/边的 CRUD 操作 |
| `backend/app/services/zep_adapter/vector.py` | ~740 | Qdrant 向量服务，语义搜索 |
| `backend/app/services/zep_adapter/types.py` | ~450 | 数据类型定义（SearchResult, NodeInfo, EdgeInfo 等） |
| `backend/app/services/zep_adapter/memory.py` | ~440 | 记忆更新服务，Agent 活动队列管理 |

**总计**: 约 3,464 行代码

---

## 功能对比

| 功能 | Zep Cloud | 本地适配器 |
|------|-----------|-----------|
| 图存储 | ✅ | ✅ Neo4j |
| 向量搜索 | ✅ | ✅ Qdrant + Embedding |
| 节点/边管理 | ✅ | ✅ |
| 语义搜索 | ✅ | ✅ 支持本地/云端 embedding |
| 实体提取 | ✅ | ✅ (兼容接口) |
| 记忆更新 | ✅ | ✅ LocalMemoryUpdater |
| InsightForge 深度检索 | ✅ | ✅ |
| PanoramaSearch 广度检索 | ✅ | ✅ |
| Agent 采访功能 | ✅ | ✅ |

---

## 关键特性

### 1. 灵活的 Embedding 配置
```bash
# 云端模式（默认，使用阿里云）
EMBEDDING_USE_LOCAL=false

# 本地模式（推荐，速度更快且无需 API 费用）
EMBEDDING_USE_LOCAL=true
EMBEDDING_LOCAL_MODEL=paraphrase-multilingual-MiniLM-L12-v2
```

### 2. 完全兼容的接口
```python
# 原有 Zep Cloud 代码无需修改
from zep_cloud import Zep  # 原版

from app.services.zep_adapter import Zep  # 本地版
# 接口完全一致！
```

### 3. Docker 一键部署
```yaml
services:
  neo4j:   # 图数据库 (端口 7474/7687)
  qdrant:  # 向量数据库 (端口 6333/6334)
  mirofish: # 主应用
```

---

## 环境变量配置

```bash
# 启用本地模式
ZEP_USE_LOCAL=true

# Neo4j 配置
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=mirofish123

# Qdrant 配置
QDRANT_URL=http://qdrant:6333

# Embedding 配置
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_USE_LOCAL=false  # 或 true 使用本地模型
EMBEDDING_LOCAL_MODEL=paraphrase-multilingual-MiniLM-L12-v2
```

---

## 依赖更新

```
+ neo4j>=5.0.0          # Neo4j 驱动
+ qdrant-client>=1.12.0 # Qdrant 客户端
+ sentence-transformers # 本地 embedding（可选）
```

---

## 相关 Commit

- `f959e75` - feat(zep): add local adapter using Neo4j + Qdrant
- `7704ba0` - feat: add local ZEP adapter with Neo4j+Qdrant and entity extraction
- `da8f674` - docs: add deployment documentation
- `7e3ea20` - feat(zep): add local adapter using Neo4j + Qdrant
- `6330ffe` - docs: update README with local ZEP adapter information

---

## 测试方法

```bash
# 启动服务
docker-compose up -d

# 验证 Neo4j
curl http://localhost:7474

# 验证 Qdrant
curl http://localhost:6333/collections

# 运行应用
python -m backend.app
```

---

## Co-authored-by

Claude Opus 4.5 <noreply@anthropic.com>
