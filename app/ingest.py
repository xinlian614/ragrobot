"""文档解析、切块与入库。"""

import asyncio
import io
import re

from . import config, database, llm


def extract_text(filename: str, data: bytes) -> str:
    """按扩展名解析文件并返回纯文本。"""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)

    if ext == ".docx":
        import docx

        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        return "\n".join(parts)

    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请另存为 UTF-8 后重试")


def normalize_text(text: str) -> str:
    """清理多余空行与空格，便于切块。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """按字符长度切分文本，尽量在句子或段落边界断开并保留重叠。"""
    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            window = text[start:end]
            boundary = max(
                window.rfind("\n"),
                window.rfind("。"),
                window.rfind("！"),
                window.rfind("？"),
                window.rfind("；"),
                window.rfind(". "),
            )
            if boundary >= int(chunk_size * 0.6):
                end = start + boundary + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


async def ingest_document(doc_id: str, filename: str, data: bytes) -> int:
    """解析文档并写入分块，返回分块数量。"""
    text = await asyncio.to_thread(extract_text, filename, data)
    chunks = split_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP)
    if not chunks:
        raise ValueError("文档中没有可用的文本内容")

    vectors = await llm.embed_texts(chunks) if config.EMBEDDING_PROVIDER == "api" else None
    database.insert_chunks(doc_id, chunks, vectors)
    database.mark_document_ready(doc_id, len(chunks))
    return len(chunks)
