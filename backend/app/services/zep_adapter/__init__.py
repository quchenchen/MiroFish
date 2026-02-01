"""
Zep 本地适配器

使用 Neo4j + Qdrant 替代 Zep Cloud，提供相同的接口。

架构:
    - Neo4j: 图数据库，存储节点和边
    - Qdrant: 向量数据库，提供语义搜索
    - 适配器层: 保持与 zep-cloud SDK 相同的接口
"""

from .client import ZepClient, ZepEntityReaderLocal, ZepToolsServiceLocal, Zep  # Zep 作为别名保持兼容性
from .types import (
    SearchResult,
    NodeInfo,
    EdgeInfo,
    InsightForgeResult,
    PanoramaResult,
    AgentInterview,
    InterviewResult,
    FilteredEntities,
    Node as EntityNode,  # Node 别名为 EntityNode 保持兼容
)
from .graph import GraphService
from .vector import VectorService

__all__ = [
    "ZepClient",
    "ZepEntityReaderLocal",
    "ZepToolsServiceLocal",
    "Zep",  # 别名，用于替换 zep_cloud.client.Zep
    "GraphService",
    "VectorService",
    "SearchResult",
    "NodeInfo",
    "EdgeInfo",
    "InsightForgeResult",
    "PanoramaResult",
    "AgentInterview",
    "InterviewResult",
    "FilteredEntities",
    "EntityNode",  # Node 的别名
]
