"""
Qdrant 向量数据库服务

提供语义搜索功能，替代 Zep Cloud 的向量搜索
"""

import os
import time
import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from openai import OpenAI

from ...config import Config
from ...utils.logger import get_logger

logger = get_logger('mirofish.zep_adapter.vector')


class EmbeddingService:
    """
    Embedding 服务

    支持：
    1. 云端 API (OpenAI/阿里云)
    2. 本地模型 (sentence-transformers)
    """

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = None,
        use_local: bool = None,
        local_model_path: str = None
    ):
        """
        初始化 Embedding 服务

        Args:
            api_key: OpenAI API Key (云端模式需要)
            base_url: API Base URL (云端模式需要)
            model: 模型名称 (云端模式)
            use_local: 是否使用本地模型
            local_model_path: 本地模型路径
        """
        # 判断是否使用本地模型
        self.use_local = use_local if use_local is not None else getattr(Config, 'EMBEDDING_USE_LOCAL', False)
        self.local_model_path = local_model_path or getattr(Config, 'EMBEDDING_LOCAL_MODEL', 'paraphrase-multilingual-MiniLM-L12-v2')

        if self.use_local:
            # 使用本地 sentence-transformers 模型
            self._init_local_model()
        else:
            # 使用云端 API
            self.api_key = api_key or Config.LLM_API_KEY
            self.base_url = base_url or Config.LLM_BASE_URL
            self.model = model or getattr(Config, 'EMBEDDING_MODEL', 'text-embedding-v3')

            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=60.0
            )
            logger.info(f"EmbeddingService 初始化完成 (云端): model={self.model}")

    def _init_local_model(self):
        """初始化本地 sentence-transformers 模型"""
        try:
            from sentence_transformers import SentenceTransformer

            # 设置离线模式，避免联网检查
            os.environ['TRANSFORMERS_OFFLINE'] = '1'
            os.environ['HF_HUB_OFFLINE'] = '1'
            os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '120'

            # 使用预装模型路径（避免 Git LFS 问题）
            # 容器内: /root/.cache/huggingface/hub/local_model
            # 宿主机: /mnt/sda/MiroFish/models/local_model
            local_model_dirs = [
                '/root/.cache/huggingface/hub/local_model',  # 容器内预装模型
                '/mnt/sda/MiroFish/models/local_model',  # 宿主机模型目录
                '/mnt/sda/MiroFish/backend/.venv/models/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/snapshots/e8f8c211226b894fcb81acc59f3b34ba3efd5f42',
            ]

            model_path_to_load = None
            for path in local_model_dirs:
                if os.path.exists(path):
                    model_path_to_load = path
                    logger.info(f"使用本地模型路径: {path}")
                    break

            if not model_path_to_load:
                # 最后尝试使用 HuggingFace 缓存
                cache_dir = getattr(Config, 'EMBEDDING_CACHE_DIR', None)
                if cache_dir and os.path.exists(cache_dir):
                    model_cache_base = os.path.join(cache_dir, f"models--sentence-transformers--{self.local_model_path}")
                    snapshots_dir = os.path.join(model_cache_base, "snapshots")
                    if os.path.exists(snapshots_dir):
                        snapshots = [d for d in os.listdir(snapshots_dir) if os.path.isdir(os.path.join(snapshots_dir, d))]
                        if snapshots:
                            model_path_to_load = os.path.join(snapshots_dir, snapshots[0])

            if not model_path_to_load:
                model_path_to_load = self.local_model_path
                logger.warning(f"未找到本地模型文件，尝试使用: {model_path_to_load}")

            logger.info(f"正在加载本地 embedding 模型: {self.local_model_path}")
            self.local_model = SentenceTransformer(model_path_to_load)
            self.vector_size = self.local_model.get_sentence_embedding_dimension()
            logger.info(f"本地 embedding 模型加载完成: vector_size={self.vector_size}")
        except ImportError:
            logger.error("sentence_transformers 未安装，请运行: pip install sentence-transformers")
            raise
        except Exception as e:
            logger.error(f"本地模型加载失败: {e}")
            raise

    def embed(self, text: str) -> List[float]:
        """
        生成文本嵌入

        Args:
            text: 输入文本

        Returns:
            嵌入向量
        """
        if self.use_local:
            return self._embed_local(text)
        else:
            return self._embed_remote(text)

    def _embed_local(self, text: str) -> List[float]:
        """使用本地模型生成嵌入"""
        try:
            embedding = self.local_model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"本地模型生成嵌入失败: {e}")
            # 返回零向量作为降级方案
            return [0.0] * self.vector_size

    def _embed_remote(self, text: str) -> List[float]:
        """使用云端 API 生成嵌入"""
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"云端 API 生成嵌入失败: {e}")
            # 返回零向量作为降级方案 (根据模型维度)
            dim = 1024 if "text-embedding-v3" in self.model or "embedding-v" in self.model else 1536
            return [0.0] * dim

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成嵌入

        Args:
            texts: 输入文本列表

        Returns:
            嵌入向量列表
        """
        if self.use_local:
            return self._embed_batch_local(texts)
        else:
            return self._embed_batch_remote(texts)

    def _embed_batch_local(self, texts: List[str]) -> List[List[float]]:
        """使用本地模型批量生成嵌入"""
        try:
            embeddings = self.local_model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"本地模型批量生成嵌入失败: {e}")
            return [[0.0] * self.vector_size for _ in texts]

    def _embed_batch_remote(self, texts: List[str]) -> List[List[float]]:
        """使用云端 API 批量生成嵌入"""
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=texts
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error(f"云端 API 批量生成嵌入失败: {e}")
            dim = 1024 if "text-embedding-v3" in self.model or "embedding-v" in self.model else 1536
            return [[0.0] * dim for _ in texts]

    def get_vector_size(self) -> int:
        """获取向量维度"""
        if self.use_local:
            return self.vector_size
        else:
            # 云端模型维度
            model = self.model
            if "text-embedding-v3" in model or "embedding-v" in model:
                return 1024
            elif "text-embedding-3-large" in model:
                return 3072
            elif "text-embedding-3-small" in model:
                return 1536
            else:
                return 1536


class QdrantVectorService:
    """
    Qdrant 向量数据库服务

    提供向量存储和语义搜索功能
    """

    # 向量维度 (根据 embedding 模型自动调整)
    # OpenAI text-embedding-3-small: 1536
    # 阿里云 text-embedding-v3: 1024
    VECTOR_SIZE = 1536  # 默认值，实际使用时会根据模型调整

    def __init__(
        self,
        url: str = None,
        api_key: str = None,
        embedding_service: EmbeddingService = None
    ):
        """
        初始化 Qdrant 服务

        Args:
            url: Qdrant 服务 URL
            api_key: Qdrant API Key (本地部署不需要)
            embedding_service: Embedding 服务实例
        """
        self.url = url or getattr(Config, 'QDRANT_URL', 'http://localhost:6333')
        self.api_key = api_key

        self.client = QdrantClient(
            url=self.url,
            api_key=self.api_key,
            timeout=30,
            check_compatibility=False  # 禁用版本兼容性检查
        )

        self.embedding = embedding_service or EmbeddingService()

        logger.info(f"QdrantVectorService 初始化完成: {self.url}")

    def _get_collection_name(self, graph_id: str) -> str:
        """
        获取图谱对应的集合名称

        Args:
            graph_id: 图谱ID

        Returns:
            集合名称 (安全的格式)
        """
        # 将 graph_id 转换为安全的集合名
        # 替换特殊字符为下划线
        safe_name = graph_id.replace("-", "_").replace("/", "_")
        return f"graph_{safe_name}"

    def ensure_collection(self, graph_id: str) -> str:
        """
        确保集合存在

        Args:
            graph_id: 图谱ID

        Returns:
            集合名称
        """
        collection_name = self._get_collection_name(graph_id)

        # 检查集合是否存在
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]

        if collection_name not in collection_names:
            # 动态获取向量维度
            vector_size = self._get_vector_size()
            # 创建新集合
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"创建 Qdrant 集合: {collection_name} (维度: {vector_size})")

        return collection_name

    def _get_vector_size(self) -> int:
        """获取当前 embedding 模型的向量维度"""
        return self.embedding.get_vector_size()

    def upsert_edge(
        self,
        graph_id: str,
        edge_uuid: str,
        text: str,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """
        添加/更新边的向量

        Args:
            graph_id: 图谱ID
            edge_uuid: 边UUID
            text: 边文本
            metadata: 元数据

        Returns:
            是否成功
        """
        collection_name = self.ensure_collection(graph_id)

        # 生成嵌入
        vector = self.embedding.embed(text)

        # 准备元数据
        payload = {
            "uuid": edge_uuid,
            "text": text,
            "type": "edge",
            "created_at": datetime.now().isoformat(),
            **(metadata or {})
        }

        # 上传到 Qdrant
        try:
            self.client.upsert(
                collection_name=collection_name,
                points=[
                    PointStruct(
                        id=edge_uuid,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
            return True
        except Exception as e:
            logger.error(f"上传向量失败: {e}")
            return False

    def upsert_node(
        self,
        graph_id: str,
        node_uuid: str,
        text: str,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """
        添加/更新节点的向量

        Args:
            graph_id: 图谱ID
            node_uuid: 节点UUID
            text: 节点文本
            metadata: 元数据

        Returns:
            是否成功
        """
        collection_name = self.ensure_collection(graph_id)

        # 生成嵌入
        vector = self.embedding.embed(text)

        # 准备元数据
        payload = {
            "uuid": node_uuid,
            "text": text,
            "type": "node",
            "created_at": datetime.now().isoformat(),
            **(metadata or {})
        }

        # 上传到 Qdrant
        try:
            self.client.upsert(
                collection_name=collection_name,
                points=[
                    PointStruct(
                        id=node_uuid,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
            return True
        except Exception as e:
            logger.error(f"上传向量失败: {e}")
            return False

    def upsert_text(
        self,
        graph_id: str,
        text_id: str,
        text: str,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """
        添加/更新文本条目的向量

        用于模拟 Zep 的 graph.add() 功能

        Args:
            graph_id: 图谱ID
            text_id: 文本ID
            text: 文本内容
            metadata: 元数据

        Returns:
            是否成功
        """
        collection_name = self.ensure_collection(graph_id)

        # 生成嵌入
        vector = self.embedding.embed(text)

        # 准备元数据
        payload = {
            "uuid": text_id,
            "text": text,
            "type": "text",
            "created_at": datetime.now().isoformat(),
            **(metadata or {})
        }

        # 上传到 Qdrant
        try:
            self.client.upsert(
                collection_name=collection_name,
                points=[
                    PointStruct(
                        id=text_id,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
            return True
        except Exception as e:
            logger.error(f"上传向量失败: {e}")
            return False

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        filters: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        语义搜索

        Args:
            graph_id: 图谱ID
            query: 查询文本
            limit: 返回数量
            filters: 过滤条件

        Returns:
            搜索结果列表，每项包含 uuid, text, score, payload
        """
        collection_name = self._get_collection_name(graph_id)

        # 检查集合是否存在
        collections = self.client.get_collections().collections
        if collection_name not in [c.name for c in collections]:
            logger.warning(f"集合不存在: {collection_name}")
            return []

        # 生成查询向量
        query_vector = self.embedding.embed(query)

        # 构建过滤条件
        query_filter = None
        if filters:
            conditions = []
            for key, value in filters.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
            if conditions:
                query_filter = Filter(must=conditions)

        # 执行搜索 (使用 query_points 推荐)
        try:
            results = self.client.query_points(
                collection_name=collection_name,
                query=query_vector,  # 参数名是 query 不是 query_vector
                limit=limit
            )

            # 格式化结果 (query_points 返回 QueryResponse，包含 points 列表)
            formatted_results = []
            for result in results.points:  # 访问 response.points
                formatted_results.append({
                    "uuid": result.id,
                    "text": result.payload.get("text", ""),
                    "score": result.score,
                    "type": result.payload.get("type", "unknown"),
                    "payload": result.payload
                })

            return formatted_results

        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []

    def search_by_text(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges"
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        按文本搜索，返回边和节点

        Args:
            graph_id: 图谱ID
            query: 查询文本
            limit: 返回数量
            scope: 搜索范围 (edges/nodes/both)

        Returns:
            (边列表, 节点列表)
        """
        results = self.search(
            graph_id=graph_id,
            query=query,
            limit=limit * 2  # 多取一些用于筛选
        )

        edges = []
        nodes = []

        for result in results:
            item_type = result.get("type", "text")

            if scope in ["edges", "both"] and item_type == "edge":
                edges.append({
                    "uuid": result["uuid"],
                    "fact": result["text"],
                    "name": result["payload"].get("name", "RELATED_TO"),
                    "source_node_uuid": result["payload"].get("source_node_uuid", ""),
                    "target_node_uuid": result["payload"].get("target_node_uuid", ""),
                })

            elif scope in ["nodes", "both"] and item_type == "node":
                nodes.append({
                    "uuid": result["uuid"],
                    "name": result["payload"].get("name", ""),
                    "summary": result["text"],
                    "labels": result["payload"].get("labels", ["Entity"]),
                })

        # 限制数量
        edges = edges[:limit]
        nodes = nodes[:limit]

        return edges, nodes

    def delete_collection(self, graph_id: str) -> bool:
        """
        删除图谱对应的集合

        Args:
            graph_id: 图谱ID

        Returns:
            是否成功
        """
        collection_name = self._get_collection_name(graph_id)

        try:
            self.client.delete_collection(collection_name=collection_name)
            logger.info(f"删除集合: {collection_name}")
            return True
        except Exception as e:
            logger.warning(f"删除集合失败: {e}")
            return False


class VectorService:
    """
    向量服务接口

    兼容 Zep 的向量搜索接口
    """

    def __init__(
        self,
        qdrant_service: QdrantVectorService,
        neo4j_repo  # Neo4jRepository
    ):
        self.qdrant = qdrant_service
        self.neo4j = neo4j_repo

    def index_edge(
        self,
        graph_id: str,
        edge_uuid: str,
        edge_data: Dict[str, Any]
    ):
        """
        索引边到向量数据库

        Args:
            graph_id: 图谱ID
            edge_uuid: 边UUID
            edge_data: 边数据
        """
        # 构建索引文本
        text = edge_data.get("fact", "")

        # 添加节点名称上下文
        source_name = edge_data.get("source_node_name", "")
        target_name = edge_data.get("target_node_name", "")
        if source_name and target_name:
            text = f"{source_name} {edge_data.get('name', '')} {target_name}: {text}"

        metadata = {
            "name": edge_data.get("name", ""),
            "source_node_uuid": edge_data.get("source_node_uuid", ""),
            "target_node_uuid": edge_data.get("target_node_uuid", ""),
            "source_node_name": source_name,
            "target_node_name": target_name,
        }

        self.qdrant.upsert_edge(
            graph_id=graph_id,
            edge_uuid=edge_uuid,
            text=text,
            metadata=metadata
        )

    def index_node(
        self,
        graph_id: str,
        node_uuid: str,
        node_data: Dict[str, Any]
    ):
        """
        索引节点到向量数据库

        Args:
            graph_id: 图谱ID
            node_uuid: 节点UUID
            node_data: 节点数据
        """
        # 构建索引文本
        name = node_data.get("name", "")
        summary = node_data.get("summary", "")
        text = f"{name}: {summary}" if name and summary else (name or summary)

        metadata = {
            "name": name,
            "labels": node_data.get("labels", []),
        }

        self.qdrant.upsert_node(
            graph_id=graph_id,
            node_uuid=node_uuid,
            text=text,
            metadata=metadata
        )

    def index_text(
        self,
        graph_id: str,
        text: str
    ) -> str:
        """
        索引文本到向量数据库

        用于模拟 Zep 的 graph.add() 功能

        Args:
            graph_id: 图谱ID
            text: 文本内容

        Returns:
            文本ID
        """
        text_id = str(uuid.uuid4())

        self.qdrant.upsert_text(
            graph_id=graph_id,
            text_id=text_id,
            text=text
        )

        return text_id

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges"
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        搜索向量数据库

        Args:
            graph_id: 图谱ID
            query: 查询文本
            limit: 返回数量
            scope: 搜索范围

        Returns:
            (边列表, 节点列表)
        """
        return self.qdrant.search_by_text(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope=scope
        )
