"""
图谱相关API路由
采用项目上下文机制，服务端持久化状态
"""

import os
import traceback
import threading
from flask import request, jsonify

from . import graph_bp
from ..config import Config
from ..services.ontology_generator import OntologyGenerator
from ..services.graph_builder import GraphBuilderService
from ..services.text_processor import TextProcessor
from ..services.entity_extractor import (
    infer_relation_from_fact,
    infer_relation_dynamic,
    discover_relation_types_from_documents,
    get_project_relation_types,
    save_project_relation_types
)
from ..services.zep_adapter.graph import GraphService, Neo4jRepository
from ..utils.file_parser import FileParser
from ..utils.logger import get_logger
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus

# 获取日志器
logger = get_logger('mirofish.api')


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


# ============== 项目管理接口 ==============

@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """
    获取项目详情
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": f"项目不存在: {project_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "data": project.to_dict()
    })


@graph_bp.route('/project/list', methods=['GET'])
def list_projects():
    """
    列出所有项目
    """
    limit = request.args.get('limit', 50, type=int)
    projects = ProjectManager.list_projects(limit=limit)
    
    return jsonify({
        "success": True,
        "data": [p.to_dict() for p in projects],
        "count": len(projects)
    })


@graph_bp.route('/project/<project_id>', methods=['DELETE'])
def delete_project(project_id: str):
    """
    删除项目
    """
    success = ProjectManager.delete_project(project_id)
    
    if not success:
        return jsonify({
            "success": False,
            "error": f"项目不存在或删除失败: {project_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "message": f"项目已删除: {project_id}"
    })


@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    """
    重置项目状态（用于重新构建图谱）
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": f"项目不存在: {project_id}"
        }), 404
    
    # 重置到本体已生成状态
    if project.ontology:
        project.status = ProjectStatus.ONTOLOGY_GENERATED
    else:
        project.status = ProjectStatus.CREATED
    
    project.graph_id = None
    project.graph_build_task_id = None
    project.error = None
    ProjectManager.save_project(project)
    
    return jsonify({
        "success": True,
        "message": f"项目已重置: {project_id}",
        "data": project.to_dict()
    })


# ============== 接口1：上传文件并生成本体 ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    接口1：上传文件，分析生成本体定义
    
    请求方式：multipart/form-data
    
    参数：
        files: 上传的文件（PDF/MD/TXT），可多个
        simulation_requirement: 模拟需求描述（必填）
        project_name: 项目名称（可选）
        additional_context: 额外说明（可选）
        
    返回：
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "ontology": {
                    "entity_types": [...],
                    "edge_types": [...],
                    "analysis_summary": "..."
                },
                "files": [...],
                "total_text_length": 12345
            }
        }
    """
    try:
        logger.info("=== 开始生成本体定义 ===")
        
        # 获取参数
        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')
        
        logger.debug(f"项目名称: {project_name}")
        logger.debug(f"模拟需求: {simulation_requirement[:100]}...")
        
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "请提供模拟需求描述 (simulation_requirement)"
            }), 400
        
        # 获取上传的文件
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": "请至少上传一个文档文件"
            }), 400
        
        # 创建项目
        project = ProjectManager.create_project(name=project_name)
        project.simulation_requirement = simulation_requirement
        logger.info(f"创建项目: {project.project_id}")
        
        # 保存文件并提取文本
        document_texts = []
        all_text = ""
        
        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                # 保存文件到项目目录
                file_info = ProjectManager.save_file_to_project(
                    project.project_id, 
                    file, 
                    file.filename
                )
                project.files.append({
                    "filename": file_info["original_filename"],
                    "size": file_info["size"]
                })
                
                # 提取文本
                text = FileParser.extract_text(file_info["path"])
                text = TextProcessor.preprocess_text(text)
                document_texts.append(text)
                all_text += f"\n\n=== {file_info['original_filename']} ===\n{text}"
        
        if not document_texts:
            ProjectManager.delete_project(project.project_id)
            return jsonify({
                "success": False,
                "error": "没有成功处理任何文档，请检查文件格式"
            }), 400
        
        # 保存提取的文本
        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        logger.info(f"文本提取完成，共 {len(all_text)} 字符")
        
        # 生成本体
        logger.info("调用 LLM 生成本体定义...")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )
        
        # 保存本体到项目
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"本体生成完成: {entity_count} 个实体类型, {edge_count} 个关系类型")
        
        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", [])
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(f"=== 本体生成完成 === 项目ID: {project.project_id}")
        
        return jsonify({
            "success": True,
            "data": {
                "project_id": project.project_id,
                "project_name": project.name,
                "ontology": project.ontology,
                "analysis_summary": project.analysis_summary,
                "files": project.files,
                "total_text_length": project.total_text_length
            }
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 接口2：构建图谱 ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """
    接口2：根据project_id构建图谱
    
    请求（JSON）：
        {
            "project_id": "proj_xxxx",  // 必填，来自接口1
            "graph_name": "图谱名称",    // 可选
            "chunk_size": 500,          // 可选，默认500
            "chunk_overlap": 50         // 可选，默认50
        }
        
    返回：
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "task_id": "task_xxxx",
                "message": "图谱构建任务已启动"
            }
        }
    """
    try:
        logger.info("=== 开始构建图谱 ===")
        
        # 检查配置（根据模式）
        errors = []
        if Config.ZEP_USE_LOCAL:
            if not Config.NEO4J_PASSWORD:
                errors.append("NEO4J_PASSWORD未配置 (本地模式需要)")
            if not Config.LLM_API_KEY:
                errors.append("LLM_API_KEY未配置")
        else:
            if not Config.ZEP_API_KEY:
                errors.append("ZEP_API_KEY未配置")
        if errors:
            logger.error(f"配置错误: {errors}")
            return jsonify({
                "success": False,
                "error": "配置错误: " + "; ".join(errors)
            }), 500
        
        # 解析请求
        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"请求参数: project_id={project_id}")
        
        if not project_id:
            return jsonify({
                "success": False,
                "error": "请提供 project_id"
            }), 400
        
        # 获取项目
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"项目不存在: {project_id}"
            }), 404
        
        # 检查项目状态
        force = data.get('force', False)  # 强制重新构建
        
        if project.status == ProjectStatus.CREATED:
            return jsonify({
                "success": False,
                "error": "项目尚未生成本体，请先调用 /ontology/generate"
            }), 400
        
        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": "图谱正在构建中，请勿重复提交。如需强制重建，请添加 force: true",
                "task_id": project.graph_build_task_id
            }), 400
        
        # 如果强制重建，重置状态
        if force and project.status in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.graph_id = None
            project.graph_build_task_id = None
            project.error = None
        
        # 获取配置
        graph_name = data.get('graph_name', project.name or 'MiroFish Graph')
        chunk_size = data.get('chunk_size', project.chunk_size or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.chunk_overlap or Config.DEFAULT_CHUNK_OVERLAP)
        
        # 更新项目配置
        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        
        # 获取提取的文本
        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return jsonify({
                "success": False,
                "error": "未找到提取的文本内容"
            }), 400
        
        # 获取本体
        ontology = project.ontology
        if not ontology:
            return jsonify({
                "success": False,
                "error": "未找到本体定义"
            }), 400
        
        # 创建异步任务
        task_manager = TaskManager()
        task_id = task_manager.create_task(f"构建图谱: {graph_name}")
        logger.info(f"创建图谱构建任务: task_id={task_id}, project_id={project_id}")
        
        # 更新项目状态
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)
        
        # 启动后台任务
        def build_task():
            build_logger = get_logger('mirofish.build')
            try:
                build_logger.info(f"[{task_id}] 开始构建图谱...")
                task_manager.update_task(
                    task_id, 
                    status=TaskStatus.PROCESSING,
                    message="初始化图谱构建服务..."
                )
                
                # 创建图谱构建服务
                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
                
                # 分块
                task_manager.update_task(
                    task_id,
                    message="文本分块中...",
                    progress=5
                )
                chunks = TextProcessor.split_text(
                    text, 
                    chunk_size=chunk_size, 
                    overlap=chunk_overlap
                )
                total_chunks = len(chunks)
                
                # 创建图谱
                task_manager.update_task(
                    task_id,
                    message="创建Zep图谱...",
                    progress=10
                )
                graph_id = builder.create_graph(name=graph_name)
                
                # 更新项目的graph_id
                project.graph_id = graph_id
                ProjectManager.save_project(project)
                
                # 设置本体
                task_manager.update_task(
                    task_id,
                    message="设置本体定义...",
                    progress=15
                )
                builder.set_ontology(graph_id, ontology)
                
                # 添加文本（progress_callback 签名是 (msg, progress_ratio)）
                def add_progress_callback(msg, progress_ratio):
                    progress = 15 + int(progress_ratio * 40)  # 15% - 55%
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )
                
                task_manager.update_task(
                    task_id,
                    message=f"开始添加 {total_chunks} 个文本块...",
                    progress=15
                )
                
                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=3,
                    progress_callback=add_progress_callback
                )

                # 本地模式：使用 LLM 抽取实体和关系
                if builder._use_local:
                    build_logger.info(f"[{task_id}] 本地模式: 开始 LLM 实体抽取...")
                    task_manager.update_task(
                        task_id,
                        message="开始 LLM 实体抽取...",
                        progress=60
                    )

                    try:
                        import sys
                        import os
                        # 添加 backend 目录到 sys.path
                        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
                        if backend_dir not in sys.path:
                            sys.path.insert(0, backend_dir)
                        from app.services.entity_extractor import GraphEntityExtractor
                        extractor = GraphEntityExtractor()

                        # 合并所有文本块进行实体抽取
                        full_text = "\n\n".join(chunks)
                        build_logger.info(f"[{task_id}] 开始抽取实体，文本长度: {len(full_text)}")

                        # 执行抽取并存储
                        extraction_result = extractor.extract_and_store(
                            graph_id=graph_id,
                            text=full_text,
                            ontology=ontology
                        )

                        build_logger.info(f"[{task_id}] 实体抽取完成: {len(extraction_result.entities)} 个实体, {len(extraction_result.relations)} 个关系")

                        task_manager.update_task(
                            task_id,
                            progress=85,
                            message=f"实体抽取完成: {len(extraction_result.entities)} 个实体, {len(extraction_result.relations)} 个关系"
                        )
                    except Exception as e:
                        build_logger.error(f"[{task_id}] 实体抽取失败: {e}")
                        import traceback
                        build_logger.error(traceback.format_exc())
                        # 继续执行，不让抽取失败阻止整个流程
                else:
                    # 云端模式：等待Zep处理完成
                    task_manager.update_task(
                        task_id,
                        message="等待Zep处理数据...",
                        progress=60
                    )

                    def wait_progress_callback(msg, progress_ratio):
                        progress = 60 + int(progress_ratio * 25)  # 60% - 85%
                        task_manager.update_task(
                            task_id,
                            message=msg,
                            progress=progress
                        )

                    builder._wait_for_episodes(episode_uuids, wait_progress_callback)
                
                # 获取图谱数据
                task_manager.update_task(
                    task_id,
                    message="获取图谱数据...",
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)
                
                # 更新项目状态
                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)
                
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] 图谱构建完成: graph_id={graph_id}, 节点={node_count}, 边={edge_count}")
                
                # 完成
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="图谱构建完成",
                    progress=100,
                    result={
                        "project_id": project_id,
                        "graph_id": graph_id,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks
                    }
                )
                
            except Exception as e:
                # 更新项目状态为失败
                build_logger.error(f"[{task_id}] 图谱构建失败: {str(e)}")
                build_logger.debug(traceback.format_exc())
                
                project.status = ProjectStatus.FAILED
                project.error = str(e)
                ProjectManager.save_project(project)
                
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"构建失败: {str(e)}",
                    error=traceback.format_exc()
                )
        
        # 启动后台线程
        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "message": "图谱构建任务已启动，请通过 /task/{task_id} 查询进度"
            }
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 任务查询接口 ==============

@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    """
    查询任务状态
    """
    task = TaskManager().get_task(task_id)
    
    if not task:
        return jsonify({
            "success": False,
            "error": f"任务不存在: {task_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "data": task.to_dict()
    })


@graph_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """
    列出所有任务
    """
    tasks = TaskManager().list_tasks()
    
    return jsonify({
        "success": True,
        "data": [t.to_dict() for t in tasks],
        "count": len(tasks)
    })


# ============== 图谱数据接口 ==============

@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """
    获取图谱数据（节点和边）
    """
    try:
        # GraphBuilderService 会根据 ZEP_USE_LOCAL 自动选择模式
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        graph_data = builder.get_graph_data(graph_id)

        return jsonify({
            "success": True,
            "data": graph_data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/delete/<graph_id>', methods=['DELETE'])
def delete_graph(graph_id: str):
    """
    删除Zep图谱
    """
    try:
        # GraphBuilderService 会根据 ZEP_USE_LOCAL 自动选择模式
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        builder.delete_graph(graph_id)

        return jsonify({
            "success": True,
            "message": f"图谱已删除: {graph_id}"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/update-relations/<graph_id>', methods=['POST'])
def update_relation_types(graph_id: str):
    """
    批量更新图谱中的关系类型（支持项目上下文）

    根据关系的 fact 描述，智能推断并更新更精确的关系类型
    支持项目特定的关系类型推断

    Request body:
        project_id: (可选) 项目ID，用于项目感知的关系推断
    """
    try:
        data = request.get_json() or {}
        project_id = data.get('project_id')

        # 获取图谱中所有关系
        neo4j_repo = Neo4jRepository(
            uri=Config.NEO4J_URI,
            username=Config.NEO4J_USERNAME,
            password=Config.NEO4J_PASSWORD
        )
        graph_service = GraphService(neo4j_repo)

        # 查询所有需要更新的关系（name为"相关"或"RELATED_TO"）
        # 注意：关系存储为原生 Neo4j 关系，不是 Edge 节点
        query = """
        MATCH (s:Entity)-[r:RELATIONSHIP {name: '相关'}]->(t:Entity)
        RETURN r.fact as fact, s.name as source_name, t.name as target_name,
               elementId(r) as rel_id
        """
        results = neo4j_repo._execute_query(query, {})

        updated_count = 0
        skipped_count = 0
        relation_distribution = {}

        for result in results:
            fact = result.get("fact", "")
            source_name = result.get("source_name", "")
            target_name = result.get("target_name", "")
            rel_id = result.get("rel_id", "")

            if not fact:
                skipped_count += 1
                continue

            # 使用项目感知的关系推断（如果提供了 project_id）
            if project_id:
                new_relation_type = infer_relation_dynamic(
                    fact=fact,
                    source=source_name,
                    target=target_name,
                    project_id=project_id
                )
            else:
                new_relation_type = infer_relation_from_fact(
                    fact=fact,
                    source=source_name,
                    target=target_name
                )

            # 统计
            relation_distribution[new_relation_type] = relation_distribution.get(new_relation_type, 0) + 1

            # 更新关系 - 使用原生 Neo4j 关系更新
            update_query = """
            MATCH (s:Entity)-[r:RELATIONSHIP]->(t:Entity)
            WHERE elementId(r) = $rel_id
            SET r.name = $new_name
            SET r.relation_type = $new_type
            RETURN r
            """
            neo4j_repo._execute_write(update_query, {
                "rel_id": rel_id,
                "new_name": new_relation_type,
                "new_type": new_relation_type
            })
            updated_count += 1
            logger.info(f"更新关系: 相关 -> {new_relation_type} ({source_name} -> {target_name}, fact: {fact[:40]}...)")

        return jsonify({
            "success": True,
            "data": {
                "updated_count": updated_count,
                "skipped_count": skipped_count,
                "relation_distribution": relation_distribution,
                "project_id": project_id
            },
            "message": f"已更新 {updated_count} 条关系，跳过 {skipped_count} 条"
        })

    except Exception as e:
        logger.error(f"更新关系类型失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/discover-relations/<project_id>', methods=['POST'])
def discover_relation_types(project_id: str):
    """
    从项目文档中发现关系类型

    分析项目中的文档内容，自动发现并提取适合该领域的关系类型
    发现的结果会保存到项目配置中
    """
    try:
        data = request.get_json() or {}
        documents = data.get('documents', [])
        max_types = data.get('max_types', 30)
        save_to_project = data.get('save', True)

        if not documents:
            # 尝试从项目中获取文档
            project = ProjectManager.get_project(project_id)
            if not project:
                return jsonify({
                    "success": False,
                    "error": f"项目不存在: {project_id}"
                }), 404

            # 从项目的 sources 中提取文本
            documents = []
            if hasattr(project, 'sources') and project.sources:
                for source in project.sources:
                    if source.get('content'):
                        documents.append(source['content'])
                    elif source.get('path'):
                        try:
                            content = FileParser.parse_file(source['path'])
                            if content:
                                documents.append(content)
                        except Exception as e:
                            logger.warning(f"无法读取文件 {source.get('path')}: {e}")

        if not documents:
            return jsonify({
                "success": False,
                "error": "没有可分析的文档内容"
            }), 400

        # 执行关系类型发现
        logger.info(f"开始为项目 {project_id} 发现关系类型，文档数量: {len(documents)}")
        discovered_types = discover_relation_types_from_documents(
            documents=documents,
            max_types=max_types
        )

        # 保存到项目配置
        if save_to_project:
            save_project_relation_types(project_id, discovered_types)
            logger.info(f"已保存 {len(discovered_types)} 种关系类型到项目 {project_id}")

        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "relation_types": discovered_types,
                "count": len(discovered_types)
            },
            "message": f"发现 {len(discovered_types)} 种关系类型"
        })

    except Exception as e:
        logger.error(f"发现关系类型失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/project/<project_id>/relations', methods=['GET'])
def get_project_relations(project_id: str):
    """
    获取项目特定的关系类型列表

    返回该项目可用的所有关系类型，包括：
    - 从文档中发现的类型
    - 在本体中定义的类型
    - 默认的通用类型
    """
    try:
        relation_types = get_project_relation_types(project_id)

        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "relation_types": relation_types,
                "count": len(relation_types)
            }
        })

    except Exception as e:
        logger.error(f"获取项目关系类型失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
