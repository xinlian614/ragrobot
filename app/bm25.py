"""本地 BM25 关键词检索：无需向量服务，作为向量检索的兜底方案。"""

import math
import re
from collections import Counter
from typing import Any

# 连续英文/数字、连续中文分别成词
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")

K1 = 1.5
B = 0.75
# 展示用分数：将无上限的 BM25 分数压缩到 0~1
SCORE_SCALE = 5.0


def tokenize(text: str) -> list[str]:
    """中文按字符二元组切分，英文数字按词切分。"""
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        piece = match.group()
        if piece[0].isascii():
            if len(piece) >= 2:
                tokens.append(piece)
        elif len(piece) == 1:
            tokens.append(piece)
        else:
            tokens.extend(piece[i : i + 2] for i in range(len(piece) - 1))
    return tokens


def search(question: str, chunks: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """按 BM25 打分返回最相关的分块，分数归一到 0~1。"""
    if not chunks:
        return []

    query_tokens = list(dict.fromkeys(tokenize(question)))
    if not query_tokens:
        return []

    corpus = [Counter(tokenize(chunk["content"])) for chunk in chunks]
    doc_count = len(corpus)
    avg_len = sum(sum(tf.values()) for tf in corpus) / doc_count or 1.0

    # 文档频率，用于计算 IDF
    doc_freq: Counter[str] = Counter()
    for tf in corpus:
        doc_freq.update(tf.keys())

    scored: list[tuple[int, float]] = []
    for index, tf in enumerate(corpus):
        length = sum(tf.values())
        score = 0.0
        for token in query_tokens:
            freq = tf.get(token, 0)
            if not freq:
                continue
            idf = math.log(1 + (doc_count - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5))
            score += idf * freq * (K1 + 1) / (freq + K1 * (1 - B + B * length / avg_len))
        if score > 0:
            scored.append((index, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    results = []
    for index, raw in scored[:top_k]:
        chunk = chunks[index]
        results.append(
            {
                "doc_id": chunk["doc_id"],
                "filename": chunk["filename"],
                "chunk_index": chunk["chunk_index"],
                "score": round(raw / (raw + SCORE_SCALE), 4),
                "content": chunk["content"],
            }
        )
    return results
