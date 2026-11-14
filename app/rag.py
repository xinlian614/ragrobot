"""RAG 检索与回答生成。"""

from typing import Any

import numpy as np

from . import bm25, config, database, llm

SYSTEM_PROMPT = """你是企业知识库智能助手。请严格依据「参考资料」回答用户问题：
1. 只使用参考资料中的信息，禁止编造或补充资料之外的事实；
2. 回答末尾用 [编号] 标注引用的资料片段，例如 [1][2]；
3. 如果参考资料不足以回答，就直接说明「知识库中暂无相关信息」，不要猜测；
4. 使用简洁、条理清晰的中文作答，必要时用列表分点。"""

FALLBACK_ANSWER = "抱歉，我在知识库中没有找到与该问题相关的内容。你可以换一种问法，或联系管理员补充相关资料。"


async def retrieve(question: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """检索与问题最相关的知识分块，按配置使用 BM25 或向量检索。"""
    top_k = top_k or config.TOP_K
    chunks = database.load_chunks()
    if not chunks:
        return []

    if config.EMBEDDING_PROVIDER == "bm25":
        return bm25.search(question, chunks, top_k)

    vector_chunks = [chunk for chunk in chunks if chunk["vector"] is not None]
    if not vector_chunks:
        raise llm.ModelError("知识库分块没有向量数据，请切换 EMBEDDING_PROVIDER=bm25，或清空后重新上传")

    query_vector = np.asarray((await llm.embed_texts([question]))[0], dtype=np.float32)
    matrix = np.vstack([chunk["vector"] for chunk in vector_chunks])
    if matrix.shape[1] != query_vector.shape[0]:
        raise llm.ModelError(
            f"向量维度不一致（知识库 {matrix.shape[1]} 维，查询 {query_vector.shape[0]} 维），"
            "请确认 EMBEDDING_MODEL 未更换，或清空知识库后重新上传"
        )

    query_norm = np.linalg.norm(query_vector) or 1e-8
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0] = 1e-8
    scores = matrix @ query_vector / (norms * query_norm)

    order = np.argsort(-scores)[:top_k]
    results = []
    for idx in order:
        score = float(scores[idx])
        if score < config.MIN_SCORE:
            continue
        hit = vector_chunks[int(idx)]
        results.append(
            {
                "doc_id": hit["doc_id"],
                "filename": hit["filename"],
                "chunk_index": hit["chunk_index"],
                "score": round(score, 4),
                "content": hit["content"],
            }
        )
    return results


def build_messages(question: str, sources: list[dict[str, Any]], history: list[dict[str, str]]) -> list[dict[str, str]]:
    """组装带参考资料与多轮上下文的对话消息。"""
    context = "\n\n".join(
        f"[{i}] 来源：{src['filename']}（第 {src['chunk_index'] + 1} 段）\n{src['content']}"
        for i, src in enumerate(sources, start=1)
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history[-6:]:
        if item.get("role") in {"user", "assistant"} and item.get("content"):
            messages.append({"role": item["role"], "content": str(item["content"])[:2000]})
    messages.append(
        {
            "role": "user",
            "content": f"参考资料：\n{context}\n\n用户问题：{question}",
        }
    )
    return messages


async def answer_question(question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """完整问答流程：检索 -> 组织上下文 -> 调用模型。"""
    sources = await retrieve(question)
    if not sources:
        return {"answer": FALLBACK_ANSWER, "sources": []}

    answer = await llm.chat_completion(build_messages(question, sources, history))
    return {"answer": answer or FALLBACK_ANSWER, "sources": sources}
