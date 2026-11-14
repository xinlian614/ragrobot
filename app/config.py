"""应用配置：从 .env 读取模型、分块与检索参数。"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get_int(name: str, default: int) -> int:
    """读取整数型环境变量，非法值回退到默认值。"""
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    """读取浮点型环境变量，非法值回退到默认值。"""
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


# 数据目录与数据库
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "rag.db")))

# 对话模型（OpenAI 兼容协议）
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://token.sensenova.cn/v1").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CHAT_MODEL = os.getenv("CHAT_MODEL", "sensenova-6.8-flash-lite")

# 向量模型，默认复用对话模型的服务地址与密钥
EMBEDDING_BASE_URL = (os.getenv("EMBEDDING_BASE_URL") or OPENAI_BASE_URL).rstrip("/")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY") or OPENAI_API_KEY
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sensenova-embedding")
# 检索方式：bm25 = 内置关键词检索，api = 调用向量模型接口
EMBEDDING_PROVIDER = (os.getenv("EMBEDDING_PROVIDER") or "bm25").strip().lower()
if EMBEDDING_PROVIDER not in {"bm25", "api"}:
    EMBEDDING_PROVIDER = "bm25"

# 文本切块与检索
CHUNK_SIZE = _get_int("CHUNK_SIZE", 500)
CHUNK_OVERLAP = _get_int("CHUNK_OVERLAP", 80)
TOP_K = _get_int("TOP_K", 5)
MIN_SCORE = _get_float("MIN_SCORE", 0.2)
EMBED_BATCH_SIZE = _get_int("EMBED_BATCH_SIZE", 16)

# 上传限制
MAX_FILE_MB = _get_int("MAX_FILE_MB", 20)
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}

# 管理页可选口令，为空则不做校验
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def ensure_dirs() -> None:
    """确保数据目录存在。"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
