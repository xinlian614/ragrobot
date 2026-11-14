"""FastAPI 入口：知识库管理接口与 RAG 问答接口。"""

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, database, ingest, llm, rag

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时初始化数据目录与数据库。"""
    config.ensure_dirs()
    database.init_db()
    yield


app = FastAPI(title="RAG 知识库机器人", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list)


def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    """校验管理口令（未配置 ADMIN_PASSWORD 时放行）。"""
    if config.ADMIN_PASSWORD and x_admin_token != config.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="管理口令错误或缺失")


async def _run_ingest(doc_id: str, filename: str, data: bytes) -> None:
    """后台执行解析入库，失败时记录原因。"""
    try:
        await ingest.ingest_document(doc_id, filename, data)
    except Exception as exc:  # noqa: BLE001 - 需把任意异常反馈到管理页
        database.mark_document_failed(doc_id, str(exc) or exc.__class__.__name__)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """聊天首页。"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page() -> FileResponse:
    """知识库管理页。"""
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """健康检查与当前模型信息。"""
    return {
        "status": "ok",
        "chat_model": config.CHAT_MODEL,
        "embedding_provider": config.EMBEDDING_PROVIDER,
        "embedding_model": config.EMBEDDING_MODEL,
        **database.stats(),
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict[str, Any]:
    """基于知识库的问答接口。"""
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    try:
        result = await rag.answer_question(
            question, [message.model_dump() for message in payload.history]
        )
    except llm.ModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@app.get("/api/admin/overview")
async def admin_overview(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> dict[str, Any]:
    """管理页概览：统计信息与模型配置（密钥脱敏）。"""
    require_admin(x_admin_token)
    key = config.OPENAI_API_KEY
    masked = f"{key[:6]}****{key[-4:]}" if len(key) > 10 else ("未配置" if not key else "****")
    return {
        "stats": database.stats(),
        "config": {
            "openai_base_url": config.OPENAI_BASE_URL,
            "chat_model": config.CHAT_MODEL,
            "embedding_provider": config.EMBEDDING_PROVIDER,
            "embedding_base_url": config.EMBEDDING_BASE_URL,
            "embedding_model": config.EMBEDDING_MODEL,
            "api_key": masked,
            "chunk_size": config.CHUNK_SIZE,
            "chunk_overlap": config.CHUNK_OVERLAP,
            "top_k": config.TOP_K,
            "max_file_mb": config.MAX_FILE_MB,
            "admin_password_enabled": bool(config.ADMIN_PASSWORD),
        },
    }


@app.get("/api/admin/documents")
async def list_documents(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> dict[str, Any]:
    """列出知识库文档。"""
    require_admin(x_admin_token)
    return {"documents": database.list_documents()}


@app.post("/api/admin/documents", status_code=202)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """上传知识库文件并在后台解析向量化。"""
    require_admin(x_admin_token)
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")

    max_bytes = config.MAX_FILE_MB * 1024 * 1024
    accepted: list[dict[str, Any]] = []
    for upload in files:
        filename = os.path.basename(upload.filename or "").strip()
        if not filename:
            continue
        ext = os.path.splitext(filename)[1].lower()
        if ext not in config.ALLOWED_EXTENSIONS:
            accepted.append({"filename": filename, "ok": False, "message": f"不支持的文件类型 {ext}"})
            continue

        data = await upload.read()
        if len(data) > max_bytes:
            accepted.append({"filename": filename, "ok": False, "message": f"文件超过 {config.MAX_FILE_MB}MB 限制"})
            continue
        if not data:
            accepted.append({"filename": filename, "ok": False, "message": "文件内容为空"})
            continue

        doc_id = uuid.uuid4().hex
        database.create_document(doc_id, filename, ext.lstrip("."), len(data))
        (config.UPLOAD_DIR / f"{doc_id}{ext}").write_bytes(data)
        background_tasks.add_task(_run_ingest, doc_id, filename, data)
        accepted.append({"filename": filename, "ok": True, "id": doc_id, "message": "已加入解析队列"})

    if not any(item["ok"] for item in accepted):
        raise HTTPException(status_code=400, detail="；".join(item["message"] for item in accepted))
    return {"results": accepted}


@app.delete("/api/admin/documents/{doc_id}")
async def remove_document(
    doc_id: str, x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")
) -> dict[str, Any]:
    """删除文档及其向量分块。"""
    require_admin(x_admin_token)
    if not database.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    for path in config.UPLOAD_DIR.glob(f"{doc_id}.*"):
        path.unlink(missing_ok=True)
    return {"ok": True}
