#!/usr/bin/env python3
"""
Zep Cloud 到本地 Neo4j + Qdrant 数据迁移脚本

用法:
    python scripts/migrate_from_zep.py --graph-id <graph_id> [--output-dir ./migrated_data]

功能:
    1. 从 Zep Cloud 导出图谱数据（节点、边）
    2. 导入到本地 Neo4j + Qdrant
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, List

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from backend.app.config import Config
from backend.app.utils.logger import get_logger

logger = get_logger('migrate_from_zep')


class ZepDataExporter:
    """从 Zep Cloud 导出数据"""

    def __init__(self, api_key: str):
        from zep_cloud.client import Zep
        self.client = Zep(api_key=api_key)

    def export_graph(self, graph_id: str) -> Dict[str, Any]:
        """
        导出图谱的所有数据

        Args:
            graph_id: 图谱ID

        Returns:
            包含 nodes 和 edges 的字典
        """
        logger.info(f"开始导出图谱: {graph_id}")

        # 导出节点
        logger.info("导出节点...")
        nodes = self.client.graph.node.get_by_graph_id(graph_id=graph_id)
        nodes_data = []
        for node in nodes:
            nodes_data.append({
                "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                "name": node.name or "",
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
            })
        logger.info(f"导出 {len(nodes_data)} 个节点")

        # 导出边
        logger.info("导出边...")
        edges = self.client.graph.edge.get_by_graph_id(graph_id=graph_id)
        edges_data = []
        for edge in edges:
            edge_data = {
                "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                "name": edge.name or "",
                "fact": edge.fact or "",
                "source_node_uuid": edge.source_node_uuid or "",
                "target_node_uuid": edge.target_node_uuid or "",
                "attributes": edge.attributes or {},
            }
            # 添加时间信息
            edge_data["created_at"] = getattr(edge, 'created_at', None)
            edge_data["valid_at"] = getattr(edge, 'valid_at', None)
            edge_data["invalid_at"] = getattr(edge, 'invalid_at', None)
            edge_data["expired_at"] = getattr(edge, 'expired_at', None)
            edges_data.append(edge_data)
        logger.info(f"导出 {len(edges_data)} 条边")

        return {
            "graph_id": graph_id,
            "exported_at": datetime.now().isoformat(),
            "nodes": nodes_data,
            "edges": edges_data,
        }

    def save_to_file(self, data: Dict[str, Any], filepath: str):
        """保存数据到 JSON 文件"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"数据已保存到: {filepath}")


class LocalDataImporter:
    """导入数据到本地 Neo4j + Qdrant"""

    def __init__(self):
        from backend.app.services.zep_adapter import ZepClient
        self.client = ZepClient()

    def import_graph(self, data: Dict[str, Any]) -> Dict[str, int]:
        """
        导入图谱数据到本地

        Args:
            data: 导出的图谱数据

        Returns:
            导入统计信息
        """
        graph_id = data["graph_id"]
        logger.info(f"开始导入图谱: {graph_id}")

        # 创建图谱
        self.client.neo4j.create_graph(graph_id)

        # 导入节点
        logger.info("导入节点...")
        nodes_imported = self.client.neo4j.batch_create_nodes(
            graph_id=graph_id,
            nodes=data["nodes"]
        )
        logger.info(f"导入 {nodes_imported} 个节点")

        # 导入边
        logger.info("导入边...")
        edges_imported = self.client.neo4j.batch_create_edges(
            graph_id=graph_id,
            edges=data["edges"]
        )
        logger.info(f"导入 {edges_imported} 条边")

        # 索引到向量数据库
        logger.info("索引到向量数据库...")
        self._index_to_vector(graph_id, data)

        return {
            "nodes": nodes_imported,
            "edges": edges_imported,
        }

    def _index_to_vector(self, graph_id: str, data: Dict[str, Any]):
        """索引数据到向量数据库"""
        # 索引节点
        for node in data["nodes"]:
            try:
                self.client.vector.index_node(
                    graph_id=graph_id,
                    node_uuid=node["uuid"],
                    node_data=node
                )
            except Exception as e:
                logger.warning(f"索引节点失败 {node.get('name', '')}: {e}")

        # 索引边
        for edge in data["edges"]:
            try:
                self.client.vector.index_edge(
                    graph_id=graph_id,
                    edge_uuid=edge["uuid"],
                    edge_data=edge
                )
            except Exception as e:
                logger.warning(f"索引边失败 {edge.get('name', '')}: {e}")

        logger.info("向量索引完成")


def main():
    parser = argparse.ArgumentParser(description="Zep Cloud 到本地数据迁移")
    parser.add_argument("--graph-id", required=True, help="要迁移的图谱ID")
    parser.add_argument("--output-dir", default="./migrated_data", help="导出数据目录")
    parser.add_argument("--import", dest="do_import", action="store_true",
                       help="执行导入到本地数据库")
    parser.add_argument("--export-only", action="store_true",
                       help="仅导出，不导入")
    parser.add_argument("--input-file", help="从文件导入（用于跳过导出步骤）")

    args = parser.parse_args()

    # 检查 API Key
    if not Config.ZEP_API_KEY:
        logger.error("ZEP_API_KEY 未配置，请设置环境变量")
        sys.exit(1)

    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)

    # 导出数据
    if not args.input_file:
        exporter = ZepDataExporter(api_key=Config.ZEP_API_KEY)
        data = exporter.export_graph(args.graph_id)

        # 保存到文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(args.output_dir, f"{args.graph_id}_{timestamp}.json")
        exporter.save_to_file(data, output_file)
    else:
        # 从文件读取
        with open(args.input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"从文件加载数据: {args.input_file}")

    # 导入数据
    if args.do_import:
        importer = LocalDataImporter()
        stats = importer.import_graph(data)
        logger.info(f"导入完成: {stats}")
    elif not args.export_only:
        logger.info("使用 --import 参数执行导入，或使用 --export-only 仅导出")

    logger.info("迁移脚本完成")


if __name__ == "__main__":
    main()
