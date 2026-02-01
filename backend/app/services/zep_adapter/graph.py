"""
Neo4j 图数据库服务

提供图操作的底层实现，兼容 Zep Cloud 的图接口
"""

import time
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from neo4j import GraphDatabase, RoutingControl
from openai import OpenAI

from ...config import Config
from ...utils.logger import get_logger
from .types import Node, Edge, EdgeInfo, NodeInfo

logger = get_logger('mirofish.zep_adapter.graph')


def _sanitize_attributes(attributes: Dict[str, Any]) -> Dict[str, Any]:
    """
    清洗属性值，确保所有值都是 Neo4j 支持的原始类型或数组

    Neo4j 不支持嵌套的 dict/map，需要转换为 JSON 字符串
    """
    sanitized = {}
    for key, value in attributes.items():
        if value is None:
            sanitized[key] = None
        elif isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, list):
            # 递归清洗列表中的每个元素
            sanitized[key] = [_sanitize_item(item) for item in value]
        elif isinstance(value, dict) or hasattr(value, 'items'):
            # 处理 Python dict 和 Neo4j Map 对象
            # 先转换为纯 Python dict，再序列化为 JSON
            try:
                if hasattr(value, 'items'):
                    # Neo4j Map 对象，转换为 dict
                    value_dict = {k: _sanitize_item(v) for k, v in value.items()}
                else:
                    value_dict = {k: _sanitize_item(v) for k, v in value.items()}
                sanitized[key] = json.dumps(value_dict, ensure_ascii=False)
            except Exception:
                # 如果转换失败，转换为字符串
                sanitized[key] = str(value)
        else:
            # 其他类型转换为字符串
            sanitized[key] = str(value)
    return sanitized


def _sanitize_item(item: Any) -> Any:
    """递归清洗单个值"""
    if item is None:
        return None
    elif isinstance(item, (str, int, float, bool)):
        return item
    elif isinstance(item, list):
        return [_sanitize_item(i) for i in item]
    elif isinstance(item, dict) or hasattr(item, 'items'):
        # 处理 Python dict 和 Neo4j Map 对象
        try:
            if hasattr(item, 'items'):
                # Neo4j Map 对象
                return json.dumps({k: _sanitize_item(v) for k, v in item.items()}, ensure_ascii=False)
            else:
                return json.dumps({k: _sanitize_item(v) for k, v in item.items()}, ensure_ascii=False)
        except Exception:
            return str(item)
    else:
        return str(item)


class Neo4jRepository:
    """
    Neo4j 图数据库仓库

    提供节点和边的 CRUD 操作，以及批量操作和 Cypher 查询
    """

    def __init__(
        self,
        uri: str = None,
        username: str = None,
        password: str = None
    ):
        """
        初始化 Neo4j 连接

        Args:
            uri: Neo4j Bolt URI (默认从配置读取)
            username: 用户名 (默认从配置读取)
            password: 密码 (默认从配置读取)
        """
        self.uri = uri or getattr(Config, 'NEO4J_URI', 'bolt://localhost:7687')
        self.username = username or getattr(Config, 'NEO4J_USERNAME', 'neo4j')
        self.password = password or getattr(Config, 'NEO4J_PASSWORD', 'mirofish123')

        self.driver = None
        self._connect()

        logger.info(f"Neo4jRepository 初始化完成: {self.uri}")

    def _connect(self):
        """建立数据库连接"""
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password)
            )
            # 验证连接
            self.driver.verify_connectivity()
            logger.info("Neo4j 连接成功")
        except Exception as e:
            logger.error(f"Neo4j 连接失败: {e}")
            raise

    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j 连接已关闭")

    def _execute_query(
        self,
        query: str,
        parameters: Dict[str, Any] = None,
        database: str = "neo4j"
    ) -> List[Dict[str, Any]]:
        """
        执行 Cypher 查询

        Args:
            query: Cypher 查询语句
            parameters: 查询参数
            database: 数据库名称

        Returns:
            查询结果列表
        """
        if not self.driver:
            self._connect()

        try:
            with self.driver.session(database=database) as session:
                result = session.run(query, parameters)
                return [record.data() for record in result]
        except Exception as e:
            logger.error(f"查询执行失败: {e}")
            logger.debug(f"查询: {query}")
            logger.debug(f"参数: {parameters}")
            raise

    def _execute_write(
        self,
        query: str,
        parameters: Dict[str, Any] = None,
        database: str = "neo4j"
    ) -> Any:
        """
        执行写入操作

        Args:
            query: Cypher 查询语句
            parameters: 查询参数
            database: 数据库名称

        Returns:
            写入结果
        """
        if not self.driver:
            self._connect()

        try:
            with self.driver.session(database=database) as session:
                result = session.run(query, parameters)
                return result.single()
        except Exception as e:
            logger.error(f"写入操作失败: {e}")
            logger.debug(f"查询: {query}")
            logger.debug(f"参数: {parameters}")
            raise

    # ========== 图谱操作 ==========

    def create_graph(self, graph_id: str) -> str:
        """
        创建图谱

        在 Neo4j 中，图谱通过节点的 graph_id 属性来区分

        Args:
            graph_id: 图谱ID

        Returns:
            创建的图谱ID
        """
        # Neo4j 不需要预先创建图谱，只需标记节点
        # 创建一个虚拟节点作为图谱标记
        query = """
        MERGE (g:Graph {id: $graph_id})
        ON CREATE SET g.created_at = datetime()
        RETURN g.id as id
        """
        result = self._execute_write(query, {"graph_id": graph_id})
        logger.info(f"图谱已创建/标记: {graph_id}")
        return result["id"]

    def delete_graph(self, graph_id: str) -> bool:
        """
        删除图谱及其所有节点和边

        Args:
            graph_id: 图谱ID

        Returns:
            是否成功
        """
        query = """
        MATCH (n {graph_id: $graph_id})
        DETACH DELETE n
        """
        self._execute_write(query, {"graph_id": graph_id})
        logger.info(f"图谱已删除: {graph_id}")
        return True

    # ========== 节点操作 ==========

    def create_node(
        self,
        graph_id: str,
        name: str,
        labels: List[str] = None,
        summary: str = "",
        attributes: Dict[str, Any] = None
    ) -> Node:
        """
        创建节点

        Args:
            graph_id: 图谱ID
            name: 节点名称
            labels: 标签列表
            summary: 节点摘要
            attributes: 额外属性

        Returns:
            创建的节点
        """
        labels = labels or []
        attributes = attributes or {}

        # 确保有 Entity 标签
        if "Entity" not in labels:
            labels = ["Entity"] + labels

        # 生成 UUID (简化版，实际应使用 uuid 模块)
        import uuid
        node_uuid = str(uuid.uuid4())

        # 构建 Cypher 标签字符串
        label_str = ":".join(labels)

        # 合并属性并清洗非原始类型
        all_attributes = {
            "graph_id": graph_id,
            "name": name,
            "summary": summary,
            **_sanitize_attributes(attributes)
        }

        # 构建动态 CREATE 查询
        attr_keys = list(all_attributes.keys())
        attr_values = list(all_attributes.values())
        attr_params = {f"prop_{i}": v for i, v in enumerate(attr_values)}
        set_clause = ", ".join([f"n.{k} = $prop_{i}" for i, k in enumerate(attr_keys)])

        query = f"""
        CREATE (n:{label_str})
        SET n.uuid = $uuid, {set_clause}
        RETURN n.uuid as uuid, n.name as name, n.summary as summary
        """

        params = {"uuid": node_uuid, **attr_params}
        result = self._execute_write(query, params)

        logger.debug(f"节点已创建: {name} ({node_uuid})")
        return Node(
            uuid_=node_uuid,
            name=name,
            labels=labels,
            summary=summary,
            attributes=all_attributes
        )

    def batch_create_nodes(
        self,
        graph_id: str,
        nodes: List[Dict[str, Any]]
    ) -> int:
        """
        批量创建节点

        Args:
            graph_id: 图谱ID
            nodes: 节点数据列表，每个节点包含 name, labels, summary, attributes

        Returns:
            创建的节点数量
        """
        import uuid

        if not nodes:
            return 0

        # 使用 UNWIND 批量创建
        query = """
        UNWIND $nodes as node_data
        MERGE (n:Entity {uuid: node_data.uuid})
        ON CREATE SET n += node_data.properties
        RETURN count(*) as count
        """

        # 准备节点数据
        prepared_nodes = []
        for node in nodes:
            node_uuid = node.get("uuid") or str(uuid.uuid4())
            labels = node.get("labels", ["Entity"])
            name = node.get("name", "")

            # 添加标签
            label_str = ":".join(labels)

            properties = {
                "uuid": node_uuid,
                "graph_id": graph_id,
                "name": name,
                "summary": node.get("summary", ""),
                **node.get("attributes", {})
            }

            prepared_nodes.append({
                "uuid": node_uuid,
                "labels": labels,
                "properties": properties
            })

        # 由于标签是动态的，需要分别处理
        count = 0
        for node_data in prepared_nodes:
            try:
                labels = node_data["labels"]
                if "Entity" not in labels:
                    labels = ["Entity"] + labels
                label_str = ":".join(labels)

                query = f"""
                MERGE (n:{label_str} {{uuid: $uuid}})
                ON CREATE SET n += $properties
                """

                self._execute_write(query, {
                    "uuid": node_data["uuid"],
                    "properties": node_data["properties"]
                })
                count += 1
            except Exception as e:
                logger.warning(f"创建节点失败: {e}")

        logger.info(f"批量创建节点完成: {count}/{len(nodes)}")
        return count

    def get_node(self, uuid: str) -> Optional[Node]:
        """
        获取节点详情

        Args:
            uuid: 节点UUID

        Returns:
            节点对象或 None
        """
        query = """
        MATCH (n {uuid: $uuid})
        RETURN n.uuid as uuid, n.name as name, n.summary as summary,
               labels(n) as labels, properties(n) as attributes
        """
        results = self._execute_query(query, {"uuid": uuid})

        if not results:
            return None

        data = results[0]
        return Node(
            uuid_=data.get("uuid", ""),
            name=data.get("name", ""),
            labels=data.get("labels", []),
            summary=data.get("summary", ""),
            attributes=data.get("attributes", {})
        )

    def get_nodes_by_graph(self, graph_id: str) -> List[Node]:
        """
        获取图谱的所有节点

        Args:
            graph_id: 图谱ID

        Returns:
            节点列表
        """
        query = """
        MATCH (n {graph_id: $graph_id})
        RETURN n.uuid as uuid, n.name as name, n.summary as summary,
               n.content as content, labels(n) as labels
        ORDER BY n.name
        """
        results = self._execute_query(query, {"graph_id": graph_id})

        nodes = []
        for data in results:
            # 将 content 放入 attributes 中
            attributes = {}
            content = data.get("content")
            if content:
                attributes["content"] = content

            nodes.append(Node(
                uuid_=data.get("uuid", ""),
                name=data.get("name", ""),
                labels=data.get("labels", []),
                summary=data.get("summary", ""),
                attributes=attributes
            ))

        logger.info(f"获取节点: {len(nodes)} 个")
        return nodes

    # ========== 边操作 ==========

    def create_edge(
        self,
        graph_id: str,
        source_uuid: str,
        target_uuid: str,
        name: str,
        fact: str = "",
        attributes: Dict[str, Any] = None,
        valid_at: str = None,
        invalid_at: str = None
    ) -> Edge:
        """
        创建边

        Args:
            graph_id: 图谱ID
            source_uuid: 源节点UUID
            target_uuid: 目标节点UUID
            name: 边名称/关系类型
            fact: 事实描述
            attributes: 额外属性
            valid_at: 生效时间
            invalid_at: 失效时间

        Returns:
            创建的边
        """
        import uuid
        edge_uuid = str(uuid.uuid4())
        attributes = attributes or {}
        timestamp = datetime.now().isoformat()

        query = """
        MATCH (s {uuid: $source_uuid})
        MATCH (t {uuid: $target_uuid})
        CREATE (s)-[r:RELATIONSHIP]->(t)
        SET r.uuid = $uuid,
            r.graph_id = $graph_id,
            r.name = $name,
            r.fact = $fact,
            r.created_at = $created_at,
            r.valid_at = $valid_at,
            r.invalid_at = $invalid_at
        RETURN r.uuid as uuid
        """

        self._execute_write(query, {
            "source_uuid": source_uuid,
            "target_uuid": target_uuid,
            "uuid": edge_uuid,
            "graph_id": graph_id,
            "name": name,
            "fact": fact,
            "created_at": timestamp,
            "valid_at": valid_at,
            "invalid_at": invalid_at
        })

        logger.debug(f"边已创建: {source_uuid} -> {target_uuid} ({edge_uuid})")
        return Edge(
            uuid_=edge_uuid,
            name=name,
            fact=fact,
            source_node_uuid=source_uuid,
            target_node_uuid=target_uuid,
            created_at=timestamp,
            valid_at=valid_at,
            invalid_at=invalid_at
        )

    def batch_create_edges(
        self,
        graph_id: str,
        edges: List[Dict[str, Any]]
    ) -> int:
        """
        批量创建边

        Args:
            graph_id: 图谱ID
            edges: 边数据列表

        Returns:
            创建的边数量
        """
        import uuid

        if not edges:
            return 0

        count = 0
        for edge_data in edges:
            try:
                edge_uuid = edge_data.get("uuid") or str(uuid.uuid4())
                timestamp = datetime.now().isoformat()

                query = """
                MATCH (s {uuid: $source_uuid})
                MATCH (t {uuid: $target_uuid})
                CREATE (s)-[r:RELATIONSHIP]->(t)
                SET r.uuid = $uuid,
                    r.graph_id = $graph_id,
                    r.name = $name,
                    r.fact = $fact,
                    r.created_at = $created_at,
                    r.valid_at = $valid_at,
                    r.invalid_at = $invalid_at,
                    r.expired_at = $expired_at
                """

                self._execute_write(query, {
                    "source_uuid": edge_data.get("source_node_uuid"),
                    "target_uuid": edge_data.get("target_node_uuid"),
                    "uuid": edge_uuid,
                    "graph_id": graph_id,
                    "name": edge_data.get("name", "RELATED_TO"),
                    "fact": edge_data.get("fact", ""),
                    "created_at": edge_data.get("created_at", timestamp),
                    "valid_at": edge_data.get("valid_at"),
                    "invalid_at": edge_data.get("invalid_at"),
                    "expired_at": edge_data.get("expired_at")
                })
                count += 1
            except Exception as e:
                logger.warning(f"创建边失败: {e}")

        logger.info(f"批量创建边完成: {count}/{len(edges)}")
        return count

    def get_edges_by_graph(self, graph_id: str) -> List[Edge]:
        """
        获取图谱的所有边

        Args:
            graph_id: 图谱ID

        Returns:
            边列表
        """
        query = """
        MATCH (s {graph_id: $graph_id})-[r]->(t {graph_id: $graph_id})
        RETURN r.uuid as uuid, r.name as name, r.fact as fact,
               s.uuid as source_uuid, t.uuid as target_uuid,
               s.name as source_name, t.name as target_name,
               r.created_at as created_at, r.valid_at as valid_at,
               r.invalid_at as invalid_at, r.expired_at as expired_at
        """
        results = self._execute_query(query, {"graph_id": graph_id})

        edges = []
        for data in results:
            edges.append(Edge(
                uuid_=data.get("uuid", ""),
                name=data.get("name", ""),
                fact=data.get("fact", ""),
                source_node_uuid=data.get("source_uuid", ""),
                target_node_uuid=data.get("target_uuid", ""),
                created_at=data.get("created_at"),
                valid_at=data.get("valid_at"),
                invalid_at=data.get("invalid_at"),
                expired_at=data.get("expired_at")
            ))

        logger.info(f"获取边: {len(edges)} 条")
        return edges

    def get_entity_edges(self, node_uuid: str) -> List[Edge]:
        """
        获取节点的所有相关边

        Args:
            node_uuid: 节点UUID

        Returns:
            边列表
        """
        query = """
        MATCH (n {uuid: $uuid})-[r]-(m)
        RETURN r.uuid as uuid, r.name as name, r.fact as fact,
               n.uuid as source_uuid, m.uuid as target_uuid,
               r.created_at as created_at, r.valid_at as valid_at,
               r.invalid_at as invalid_at, r.expired_at as expired_at
        """
        results = self._execute_query(query, {"uuid": node_uuid})

        edges = []
        for data in results:
            edges.append(Edge(
                uuid_=data.get("uuid", ""),
                name=data.get("name", ""),
                fact=data.get("fact", ""),
                source_node_uuid=data.get("source_uuid", ""),
                target_node_uuid=data.get("target_uuid", ""),
                created_at=data.get("created_at"),
                valid_at=data.get("valid_at"),
                invalid_at=data.get("invalid_at"),
                expired_at=data.get("expired_at")
            ))

        return edges

    # ========== 文本添加操作 (模拟 Zep 的 graph.add) ==========

    def add_text_to_graph(
        self,
        graph_id: str,
        text: str
    ) -> bool:
        """
        将文本添加到图谱

        这是 Zep 的主要接口，用于从文本中提取实体和关系。
        本地实现中，我们将文本存储为一个特殊节点，后续可以处理。

        Args:
            graph_id: 图谱ID
            text: 文本内容

        Returns:
            是否成功
        """
        import uuid

        # 创建一个文本条目节点
        text_uuid = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()

        query = """
        MERGE (g:Graph {id: $graph_id})
        CREATE (t:TextEntry {uuid: $uuid, graph_id: $graph_id, content: $text, created_at: $timestamp})
        RETURN t.uuid as uuid
        """

        self._execute_write(query, {
            "graph_id": graph_id,
            "uuid": text_uuid,
            "text": text,
            "timestamp": timestamp
        })

        logger.debug(f"文本已添加到图谱: {len(text)} 字符")
        return True

    # ========== 图谱统计 ==========

    def get_graph_stats(self, graph_id: str) -> Dict[str, Any]:
        """
        获取图谱统计信息

        Args:
            graph_id: 图谱ID

        Returns:
            统计信息
        """
        query = """
        MATCH (n {graph_id: $graph_id})
        OPTIONAL MATCH (n)-[r]-(m {graph_id: $graph_id})
        RETURN count(DISTINCT n) as node_count, count(DISTINCT r) as edge_count
        """
        result = self._execute_query(query, {"graph_id": graph_id})

        if result:
            return {
                "node_count": result[0].get("node_count", 0),
                "edge_count": result[0].get("edge_count", 0)
            }

        return {"node_count": 0, "edge_count": 0}


class GraphService:
    """
    图服务 - 提供 Zep 兼容的图操作接口

    封装 Neo4jRepository，提供与 Zep Cloud 图 API 相同的接口
    """

    class NodeOperations:
        """节点操作"""

        def __init__(self, parent: "GraphService"):
            self.parent = parent

        def get_by_graph_id(self, graph_id: str) -> List[Node]:
            """获取图谱的所有节点"""
            nodes = self.parent.neo4j.get_nodes_by_graph(graph_id)
            return nodes

        def get(self, uuid_: str = None, uuid: str = None) -> Node:
            """获取单个节点"""
            node_uuid = uuid_ or uuid
            node = self.parent.neo4j.get_node(node_uuid)
            if not node:
                raise ValueError(f"节点不存在: {node_uuid}")
            return node

        def create(
            self,
            graph_id: str,
            name: str,
            labels: List[str] = None,
            summary: str = "",
            **attributes
        ) -> Node:
            """创建节点"""
            return self.parent.neo4j.create_node(
                graph_id=graph_id,
                name=name,
                labels=labels,
                summary=summary,
                attributes=attributes
            )

        def get_entity_edges(self, node_uuid: str) -> List[Edge]:
            """获取节点的实体边"""
            return self.parent.neo4j.get_entity_edges(node_uuid)

    class EdgeOperations:
        """边操作"""

        def __init__(self, parent: "GraphService"):
            self.parent = parent

        def get_by_graph_id(self, graph_id: str) -> List[Edge]:
            """获取图谱的所有边"""
            edges = self.parent.neo4j.get_edges_by_graph(graph_id)
            return edges

    class SearchOperations:
        """搜索操作"""

        def __init__(self, parent: "GraphService"):
            self.parent = parent
            self.vector_service = None

        def set_vector_service(self, vector_service):
            """设置向量服务（用于语义搜索）"""
            self.vector_service = vector_service

        def __call__(
            self,
            graph_id: str,
            query: str,
            limit: int = 10,
            scope: str = "edges",
            reranker: str = None
        ) -> "GraphSearchResult":
            """
            图谱搜索

            如果有向量服务，使用语义搜索；否则使用关键词匹配

            Args:
                graph_id: 图谱ID
                query: 搜索查询
                limit: 返回数量限制
                scope: 搜索范围 (edges/nodes/both)
                reranker: 重排序器 (暂不支持)

            Returns:
                搜索结果
            """
            edges = []
            nodes = []

            if self.vector_service:
                # 使用向量搜索
                edges_data, nodes_data = self.vector_service.search_by_text(
                    graph_id=graph_id,
                    query=query,
                    limit=limit,
                    scope=scope
                )

                for e_data in edges_data:
                    edges.append(Edge(**e_data))

                for n_data in nodes_data:
                    nodes.append(Node(**n_data))

            else:
                # 降级为关键词匹配
                if scope in ["edges", "both"]:
                    all_edges = self.parent.neo4j.get_edges_by_graph(graph_id)
                    query_lower = query.lower()

                    for edge in all_edges:
                        if (query_lower in (edge.fact or "").lower() or
                            query_lower in (edge.name or "").lower()):
                            edges.append(edge)
                            if len(edges) >= limit:
                                break

                if scope in ["nodes", "both"]:
                    all_nodes = self.parent.neo4j.get_nodes_by_graph(graph_id)
                    query_lower = query.lower()

                    for node in all_nodes:
                        if (query_lower in (node.name or "").lower() or
                            query_lower in (node.summary or "").lower()):
                            nodes.append(node)
                            if len(nodes) >= limit:
                                break

            return GraphSearchResult(edges=edges, nodes=nodes)

    def __init__(self, neo4j_repo: Neo4jRepository):
        self.neo4j = neo4j_repo
        self.node = self.NodeOperations(self)
        self.edge = self.EdgeOperations(self)
        self.search = self.SearchOperations(self)

    def add(self, graph_id: str, type_: str, data: str, **kwargs) -> bool:
        """
        添加数据到图谱

        Args:
            graph_id: 图谱ID
            type_: 数据类型 (text/json)
            data: 数据内容
            **kwargs: 其他参数

        Returns:
            是否成功
        """
        if type_ == "text":
            return self.neo4j.add_text_to_graph(graph_id, data)
        else:
            logger.warning(f"不支持的添加类型: {type_}")
            return False
