"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

# 检查是否在 Docker 容器中运行
IN_DOCKER = os.path.exists('/.dockerenv')

if IN_DOCKER:
    # Docker 环境：环境变量已由 docker-compose 设置，不加载 .env 文件
    # 避免 .env 文件覆盖 Docker 传入的环境变量
    pass
elif os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=False)  # 不覆盖已存在的环境变量
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=False)


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        import secrets
        SECRET_KEY = secrets.token_hex(32)
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式，默认阿里云DashScope）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'qwen-plus')
    
    # Zep配置
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')

    # Zep 本地模式配置 (使用 Neo4j + Qdrant 替代 Zep Cloud)
    ZEP_USE_LOCAL = os.environ.get('ZEP_USE_LOCAL', 'false').lower() == 'true'

    # Neo4j 配置 (本地模式)
    _neo4j_uri = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    # 如果不在 Docker 中运行，将容器名替换为 localhost
    if not IN_DOCKER:
        if 'neo4j:7687' in _neo4j_uri:
            _neo4j_uri = _neo4j_uri.replace('bolt://neo4j:7687', 'bolt://localhost:7687')
    NEO4J_URI = _neo4j_uri
    NEO4J_USERNAME = os.environ.get('NEO4J_USERNAME', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD')  # 必须显式配置

    # Qdrant 配置 (本地模式)
    _qdrant_url = os.environ.get('QDRANT_URL', 'http://localhost:6333')
    # 如果不在 Docker 中运行，将容器名替换为 localhost
    if not IN_DOCKER:
        if 'qdrant:6333' in _qdrant_url:
            _qdrant_url = _qdrant_url.replace('http://qdrant:6333', 'http://localhost:6333')
    QDRANT_URL = _qdrant_url

    # Embedding 模型配置
    EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'text-embedding-v3')

    # 本地 Embedding 模型配置
    # 设置为 true 启用本地模型 (sentence-transformers)
    EMBEDDING_USE_LOCAL = os.environ.get('EMBEDDING_USE_LOCAL', 'false').lower() == 'true'
    # 本地模型名称或路径 (默认使用多语言轻量模型)
    EMBEDDING_LOCAL_MODEL = os.environ.get(
        'EMBEDDING_LOCAL_MODEL',
        'paraphrase-multilingual-MiniLM-L12-v2'  # 支持中英文，384维，速度快
    )
    # 模型缓存目录
    EMBEDDING_CACHE_DIR = os.environ.get('EMBEDDING_CACHE_DIR', '')

    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小
    
    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # 模拟脚本使用的 Python 解释器（camel-ai 需要 Python 3.12）
    SIMULATION_PYTHON = os.environ.get('SIMULATION_PYTHON', 'python3.12')
    
    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls):
        """验证必要配置"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")

        # 根据模式验证不同的配置
        if cls.ZEP_USE_LOCAL:
            if not cls.NEO4J_PASSWORD:
                errors.append("NEO4J_PASSWORD 未配置 (本地模式需要)")
        else:
            if not cls.ZEP_API_KEY:
                errors.append("ZEP_API_KEY 未配置 (云端模式需要)")

        return errors

