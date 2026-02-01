"""
Zep图谱记忆更新服务
将模拟中的Agent活动动态更新到Zep图谱中

支持两种模式:
1. ZEP_USE_LOCAL=false: 使用 Zep Cloud (zep_cloud.client.Zep)
2. ZEP_USE_LOCAL=true: 使用本地 Neo4j + Qdrant (zep_adapter)
"""

import os
import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.zep_graph_memory_updater')

# 根据配置选择使用 Zep Cloud 或本地适配器
if Config.ZEP_USE_LOCAL:
    from .zep_adapter import ZepClient
    logger.info("使用 Zep 本地适配器 (Neo4j + Qdrant) for memory updater")
else:
    from zep_cloud.client import Zep
    logger.info("使用 Zep Cloud for memory updater")


@dataclass
class AgentActivity:
    """Agent活动记录"""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str
    
    def to_episode_text(self) -> str:
        """
        将活动转换为可以发送给Zep的文本描述
        
        采用自然语言描述格式，让Zep能够从中提取实体和关系
        不添加模拟相关的前缀，避免误导图谱更新
        """
        # 根据不同的动作类型生成不同的描述
        action_descriptions = {
            "CREATE_POST": self._describe_create_post,
            "LIKE_POST": self._describe_like_post,
            "DISLIKE_POST": self._describe_dislike_post,
            "REPOST": self._describe_repost,
            "QUOTE_POST": self._describe_quote_post,
            "FOLLOW": self._describe_follow,
            "CREATE_COMMENT": self._describe_create_comment,
            "LIKE_COMMENT": self._describe_like_comment,
            "DISLIKE_COMMENT": self._describe_dislike_comment,
            "SEARCH_POSTS": self._describe_search,
            "SEARCH_USER": self._describe_search_user,
            "MUTE": self._describe_mute,
        }
        
        describe_func = action_descriptions.get(self.action_type, self._describe_generic)
        description = describe_func()
        
        # 直接返回 "agent名称: 活动描述" 格式，不添加模拟前缀
        return f"{self.agent_name}: {description}"
    
    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        if content:
            return f"发布了一条帖子：「{content}」"
        return "发布了一条帖子"
    
    def _describe_like_post(self) -> str:
        """点赞帖子 - 包含帖子原文和作者信息"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if post_content and post_author:
            return f"点赞了{post_author}的帖子：「{post_content}」"
        elif post_content:
            return f"点赞了一条帖子：「{post_content}」"
        elif post_author:
            return f"点赞了{post_author}的一条帖子"
        return "点赞了一条帖子"
    
    def _describe_dislike_post(self) -> str:
        """踩帖子 - 包含帖子原文和作者信息"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if post_content and post_author:
            return f"踩了{post_author}的帖子：「{post_content}」"
        elif post_content:
            return f"踩了一条帖子：「{post_content}」"
        elif post_author:
            return f"踩了{post_author}的一条帖子"
        return "踩了一条帖子"
    
    def _describe_repost(self) -> str:
        """转发帖子 - 包含原帖内容和作者信息"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        
        if original_content and original_author:
            return f"转发了{original_author}的帖子：「{original_content}」"
        elif original_content:
            return f"转发了一条帖子：「{original_content}」"
        elif original_author:
            return f"转发了{original_author}的一条帖子"
        return "转发了一条帖子"
    
    def _describe_quote_post(self) -> str:
        """引用帖子 - 包含原帖内容、作者信息和引用评论"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")
        
        base = ""
        if original_content and original_author:
            base = f"引用了{original_author}的帖子「{original_content}」"
        elif original_content:
            base = f"引用了一条帖子「{original_content}」"
        elif original_author:
            base = f"引用了{original_author}的一条帖子"
        else:
            base = "引用了一条帖子"
        
        if quote_content:
            base += f"，并评论道：「{quote_content}」"
        return base
    
    def _describe_follow(self) -> str:
        """关注用户 - 包含被关注用户的名称"""
        target_user_name = self.action_args.get("target_user_name", "")
        
        if target_user_name:
            return f"关注了用户「{target_user_name}」"
        return "关注了一个用户"
    
    def _describe_create_comment(self) -> str:
        """发表评论 - 包含评论内容和所评论的帖子信息"""
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if content:
            if post_content and post_author:
                return f"在{post_author}的帖子「{post_content}」下评论道：「{content}」"
            elif post_content:
                return f"在帖子「{post_content}」下评论道：「{content}」"
            elif post_author:
                return f"在{post_author}的帖子下评论道：「{content}」"
            return f"评论道：「{content}」"
        return "发表了评论"
    
    def _describe_like_comment(self) -> str:
        """点赞评论 - 包含评论内容和作者信息"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        
        if comment_content and comment_author:
            return f"点赞了{comment_author}的评论：「{comment_content}」"
        elif comment_content:
            return f"点赞了一条评论：「{comment_content}」"
        elif comment_author:
            return f"点赞了{comment_author}的一条评论"
        return "点赞了一条评论"
    
    def _describe_dislike_comment(self) -> str:
        """踩评论 - 包含评论内容和作者信息"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        
        if comment_content and comment_author:
            return f"踩了{comment_author}的评论：「{comment_content}」"
        elif comment_content:
            return f"踩了一条评论：「{comment_content}」"
        elif comment_author:
            return f"踩了{comment_author}的一条评论"
        return "踩了一条评论"
    
    def _describe_search(self) -> str:
        """搜索帖子 - 包含搜索关键词"""
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f"搜索了「{query}」" if query else "进行了搜索"
    
    def _describe_search_user(self) -> str:
        """搜索用户 - 包含搜索关键词"""
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f"搜索了用户「{query}」" if query else "搜索了用户"
    
    def _describe_mute(self) -> str:
        """屏蔽用户 - 包含被屏蔽用户的名称"""
        target_user_name = self.action_args.get("target_user_name", "")
        
        if target_user_name:
            return f"屏蔽了用户「{target_user_name}」"
        return "屏蔽了一个用户"
    
    def _describe_generic(self) -> str:
        # 对于未知的动作类型，生成通用描述
        return f"执行了{self.action_type}操作"


class ZepGraphMemoryUpdater:
    """
    Zep图谱记忆更新器
    
    监控模拟的actions日志文件，将新的agent活动实时更新到Zep图谱中。
    按平台分组，每累积BATCH_SIZE条活动后批量发送到Zep。
    
    所有有意义的行为都会被更新到Zep，action_args中会包含完整的上下文信息：
    - 点赞/踩的帖子原文
    - 转发/引用的帖子原文
    - 关注/屏蔽的用户名
    - 点赞/踩的评论原文
    """
    
    # 批量发送大小（每个平台累积多少条后发送）
    BATCH_SIZE = 5
    
    # 平台名称映射（用于控制台显示）
    PLATFORM_DISPLAY_NAMES = {
        'twitter': '世界1',
        'reddit': '世界2',
    }
    
    # 发送间隔（秒），避免请求过快
    SEND_INTERVAL = 0.5

    # 实体抽取配置
    ENABLE_ENTITY_EXTRACTION = True  # 默认启用实体抽取
    ENTITY_EXTRACTION_INTERVAL = 3   # 每N批活动后进行一次实体抽取（避免频繁调用LLM）

    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒

    def __init__(
        self,
        graph_id: str,
        api_key: Optional[str] = None,
        ontology: Dict[str, Any] = None,
        enable_entity_extraction: bool = True
    ):
        """
        初始化更新器

        Args:
            graph_id: Zep图谱ID
            api_key: Zep API Key（可选，默认从配置读取）
            ontology: 本体定义（用于实体抽取）
            enable_entity_extraction: 是否启用实时实体抽取
        """
        self.graph_id = graph_id
        self.api_key = api_key or Config.ZEP_API_KEY
        self._use_local = Config.ZEP_USE_LOCAL
        self.ontology = ontology
        self._enable_entity_extraction = enable_entity_extraction and self._use_local  # 仅本地模式支持

        if self._use_local:
            # 本地模式使用 ZepClient 适配器
            from .zep_adapter import ZepClient
            self.client = ZepClient()
        else:
            # 云端模式使用原始 Zep SDK
            if not self.api_key:
                raise ValueError("ZEP_API_KEY未配置")
            self.client = Zep(api_key=self.api_key)

        # 实体抽取器（仅本地模式且启用时创建）
        self._entity_extractor = None
        if self._enable_entity_extraction:
            from .entity_extractor import GraphEntityExtractor
            self._entity_extractor = GraphEntityExtractor()
            logger.info("实体抽取器已启用，将实时从活动文本中提取实体和关系")

        # 活动队列
        self._activity_queue: Queue = Queue()

        # 按平台分组的活动缓冲区（每个平台各自累积到BATCH_SIZE后批量发送）
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()

        # 控制标志
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # 统计
        self._total_activities = 0  # 实际添加到队列的活动数
        self._total_sent = 0        # 成功发送到Zep的批次数
        self._total_items_sent = 0  # 成功发送到Zep的活动条数
        self._failed_count = 0      # 发送失败的批次数
        self._skipped_count = 0     # 被过滤跳过的活动数（DO_NOTHING）
        self._extraction_count = 0  # 实体抽取次数

        mode_str = "本地模式" if self._use_local else "云端模式"
        extraction_str = f", 实体抽取: {'启用' if self._enable_entity_extraction else '禁用'}" if self._use_local else ""
        logger.info(f"ZepGraphMemoryUpdater 初始化完成 ({mode_str}): graph_id={graph_id}, batch_size={self.BATCH_SIZE}{extraction_str}")
    
    def _get_platform_display_name(self, platform: str) -> str:
        """获取平台的显示名称"""
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)
    
    def start(self):
        """启动后台工作线程"""
        if self._running:
            return
        
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"ZepMemoryUpdater-{self.graph_id[:8]}"
        )
        self._worker_thread.start()
        logger.info(f"ZepGraphMemoryUpdater 已启动: graph_id={self.graph_id}")
    
    def stop(self):
        """停止后台工作线程"""
        self._running = False

        # 发送剩余的活动
        self._flush_remaining()

        # 停止前进行最后一次实体抽取（如果有积累的活动文本）
        if self._enable_entity_extraction and self._entity_extractor and self._total_sent > 0:
            try:
                # 获取最近的文本条目进行抽取
                from .zep_adapter.graph import Neo4jRepository
                neo4j = Neo4jRepository()
                query = """
                MATCH (t:TextEntry {graph_id: $graph_id})
                WHERE NOT t.extracted
                RETURN t.content as content
                ORDER BY t.created_at DESC
                LIMIT 10
                """
                results = neo4j._execute_query(query, {"graph_id": self.graph_id})
                if results:
                    combined = "\n\n".join([r["content"] for r in results if r.get("content")])
                    if combined:
                        logger.info("停止前进行最后一次实体抽取...")
                        result = self._entity_extractor.extract_and_store(
                            graph_id=self.graph_id,
                            text=combined,
                            ontology=self.ontology,
                            enable_resolution=True
                        )
                        self._extraction_count += 1
                        logger.info(f"最终实体抽取完成: {len(result.entities)} 个实体, {len(result.relations)} 个关系")

                        # 标记为已抽取
                        mark_query = """
                        MATCH (t:TextEntry {graph_id: $graph_id})
                        WHERE NOT t.extracted
                        SET t.extracted = true
                        """
                        neo4j._execute_write(mark_query, {"graph_id": self.graph_id})
            except Exception as e:
                logger.warning(f"停止前实体抽取失败: {e}")

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

        logger.info(f"ZepGraphMemoryUpdater 已停止: graph_id={self.graph_id}, "
                   f"total_activities={self._total_activities}, "
                   f"batches_sent={self._total_sent}, "
                   f"items_sent={self._total_items_sent}, "
                   f"failed={self._failed_count}, "
                   f"skipped={self._skipped_count}, "
                   f"extractions={self._extraction_count}")
    
    def add_activity(self, activity: AgentActivity):
        """
        添加一个agent活动到队列
        
        所有有意义的行为都会被添加到队列，包括：
        - CREATE_POST（发帖）
        - CREATE_COMMENT（评论）
        - QUOTE_POST（引用帖子）
        - SEARCH_POSTS（搜索帖子）
        - SEARCH_USER（搜索用户）
        - LIKE_POST/DISLIKE_POST（点赞/踩帖子）
        - REPOST（转发）
        - FOLLOW（关注）
        - MUTE（屏蔽）
        - LIKE_COMMENT/DISLIKE_COMMENT（点赞/踩评论）
        
        action_args中会包含完整的上下文信息（如帖子原文、用户名等）。
        
        Args:
            activity: Agent活动记录
        """
        # 跳过DO_NOTHING类型的活动
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return
        
        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(f"添加活动到Zep队列: {activity.agent_name} - {activity.action_type}")
    
    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """
        从字典数据添加活动
        
        Args:
            data: 从actions.jsonl解析的字典数据
            platform: 平台名称 (twitter/reddit)
        """
        # 跳过事件类型的条目
        if "event_type" in data:
            return
        
        activity = AgentActivity(
            platform=platform,
            agent_id=data.get("agent_id", 0),
            agent_name=data.get("agent_name", ""),
            action_type=data.get("action_type", ""),
            action_args=data.get("action_args", {}),
            round_num=data.get("round", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )
        
        self.add_activity(activity)
    
    def _worker_loop(self):
        """后台工作循环 - 按平台批量发送活动到Zep"""
        while self._running or not self._activity_queue.empty():
            try:
                # 尝试从队列获取活动（超时1秒）
                try:
                    activity = self._activity_queue.get(timeout=1)
                    
                    # 将活动添加到对应平台的缓冲区
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)
                        
                        # 检查该平台是否达到批量大小
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]
                            # 释放锁后再发送
                            self._send_batch_activities(batch, platform)
                            # 发送间隔，避免请求过快
                            time.sleep(self.SEND_INTERVAL)
                    
                except Empty:
                    pass
                    
            except Exception as e:
                logger.error(f"工作循环异常: {e}")
                time.sleep(1)
    
    def _send_batch_activities(self, activities: List[AgentActivity], platform: str):
        """
        批量发送活动到Zep图谱（合并为一条文本）
        发送成功后进行实体抽取（如果启用）

        Args:
            activities: Agent活动列表
            platform: 平台名称
        """
        if not activities:
            return

        # 将多条活动合并为一条文本，用换行分隔
        episode_texts = [activity.to_episode_text() for activity in activities]
        combined_text = "\n".join(episode_texts)

        # 带重试的发送
        for attempt in range(self.MAX_RETRIES):
            try:
                # 使用 type_ 参数名（本地适配器要求）
                self.client.graph.add(
                    graph_id=self.graph_id,
                    type_="text",
                    data=combined_text
                )

                self._total_sent += 1
                self._total_items_sent += len(activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(f"成功批量发送 {len(activities)} 条{display_name}活动到图谱 {self.graph_id}")
                logger.debug(f"批量内容预览: {combined_text[:200]}...")

                # 发送成功后，进行实体抽取（如果启用且达到间隔）
                self._maybe_extract_entities(combined_text)

                return

            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"批量发送到Zep失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"批量发送到Zep失败，已重试{self.MAX_RETRIES}次: {e}")
                    self._failed_count += 1

    def _maybe_extract_entities(self, text: str):
        """
        条件性地进行实体抽取

        每 N 批活动后进行一次抽取，避免频繁调用 LLM

        Args:
            text: 待抽取的文本
        """
        if not self._enable_entity_extraction or not self._entity_extractor:
            return

        # 每N批活动后进行一次实体抽取
        if self._total_sent % self.ENTITY_EXTRACTION_INTERVAL == 0:
            try:
                logger.info(f"开始对第 {self._total_sent} 批活动进行实体抽取...")
                result = self._entity_extractor.extract_and_store(
                    graph_id=self.graph_id,
                    text=text,
                    ontology=self.ontology,
                    enable_resolution=True
                )
                self._extraction_count += 1
                logger.info(f"实体抽取完成: {len(result.entities)} 个实体, {len(result.relations)} 个关系")

            except Exception as e:
                logger.warning(f"实体抽取失败（不影响活动记录）: {e}")
    
    def _flush_remaining(self):
        """发送队列和缓冲区中剩余的活动"""
        # 首先处理队列中剩余的活动，添加到缓冲区
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                platform = activity.platform.lower()
                with self._buffer_lock:
                    if platform not in self._platform_buffers:
                        self._platform_buffers[platform] = []
                    self._platform_buffers[platform].append(activity)
            except Empty:
                break
        
        # 然后发送各平台缓冲区中剩余的活动（即使不足BATCH_SIZE条）
        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    display_name = self._get_platform_display_name(platform)
                    logger.info(f"发送{display_name}平台剩余的 {len(buffer)} 条活动")
                    self._send_batch_activities(buffer, platform)
            # 清空所有缓冲区
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}

        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,  # 添加到队列的活动总数
            "batches_sent": self._total_sent,            # 成功发送的批次数
            "items_sent": self._total_items_sent,        # 成功发送的活动条数
            "failed_count": self._failed_count,          # 发送失败的批次数
            "skipped_count": self._skipped_count,        # 被过滤跳过的活动数（DO_NOTHING）
            "extraction_count": self._extraction_count,  # 实体抽取次数
            "entity_extraction_enabled": self._enable_entity_extraction,  # 实体抽取是否启用
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,                # 各平台缓冲区大小
            "running": self._running,
        }


class ZepGraphMemoryManager:
    """
    管理多个模拟的Zep图谱记忆更新器
    
    每个模拟可以有自己的更新器实例
    """
    
    _updaters: Dict[str, ZepGraphMemoryUpdater] = {}
    _lock = threading.Lock()
    
    @classmethod
    def create_updater(
        cls,
        simulation_id: str,
        graph_id: str,
        ontology: Dict[str, Any] = None,
        enable_entity_extraction: bool = True,
        project_id: str = None,
        max_retries: int = 5,
        retry_interval: float = 2.0
    ) -> ZepGraphMemoryUpdater:
        """
        为模拟创建图谱记忆更新器

        Args:
            simulation_id: 模拟ID
            graph_id: Zep图谱ID
            ontology: 本体定义（可选，用于实体抽取）
            enable_entity_extraction: 是否启用实时实体抽取
            project_id: 项目ID（用于获取本体）
            max_retries: 最大重试次数（当Neo4j未就绪时）
            retry_interval: 重试间隔（秒）

        Returns:
            ZepGraphMemoryUpdater实例
        """
        import time

        # 如果没有提供本体，尝试从项目获取
        if ontology is None and project_id:
            try:
                from ..models.project import ProjectManager
                project = ProjectManager.get_project(project_id)
                if project and project.ontology:
                    ontology = project.ontology
                    logger.info(f"从项目 {project_id} 获取到本体定义")
            except Exception as e:
                logger.warning(f"获取项目本体失败: {e}")

        with cls._lock:
            # 如果已存在，先停止旧的
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()

            # 尝试创建更新器，如果Neo4j未就绪则重试
            updater = None
            last_error = None
            for attempt in range(max_retries):
                try:
                    updater = ZepGraphMemoryUpdater(
                        graph_id=graph_id,
                        ontology=ontology,
                        enable_entity_extraction=enable_entity_extraction
                    )
                    updater.start()
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"创建图谱记忆更新器失败 (尝试 {attempt + 1}/{max_retries}): {e}, "
                                     f"{retry_interval}秒后重试...")
                        time.sleep(retry_interval)
                    else:
                        logger.error(f"创建图谱记忆更新器失败，已达最大重试次数: {e}")
                        raise

            if updater:
                cls._updaters[simulation_id] = updater
                logger.info(f"创建图谱记忆更新器: simulation_id={simulation_id}, graph_id={graph_id}, "
                           f"entity_extraction={enable_entity_extraction}")
                return updater
            else:
                raise last_error
    
    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[ZepGraphMemoryUpdater]:
        """获取模拟的更新器"""
        return cls._updaters.get(simulation_id)
    
    @classmethod
    def stop_updater(cls, simulation_id: str):
        """停止并移除模拟的更新器"""
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"已停止图谱记忆更新器: simulation_id={simulation_id}")
    
    # 防止 stop_all 重复调用的标志
    _stop_all_done = False
    
    @classmethod
    def stop_all(cls):
        """停止所有更新器"""
        # 防止重复调用
        if cls._stop_all_done:
            return
        cls._stop_all_done = True
        
        with cls._lock:
            if cls._updaters:
                for simulation_id, updater in list(cls._updaters.items()):
                    try:
                        updater.stop()
                    except Exception as e:
                        logger.error(f"停止更新器失败: simulation_id={simulation_id}, error={e}")
                cls._updaters.clear()
            logger.info("已停止所有图谱记忆更新器")
    
    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有更新器的统计信息"""
        return {
            sim_id: updater.get_stats() 
            for sim_id, updater in cls._updaters.items()
        }
