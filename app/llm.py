"""模型调用封装：OpenAI 兼容协议的对话与向量接口。"""

from typing import Any

import httpx

from . import config


class ModelError(RuntimeError):
    """模型接口调用失败。"""


def _raise_for_response(resp: httpx.Response, action: str) -> None:
    """将非 2xx 响应转换为带可读信息的异常。"""
    if resp.is_success:
        return
    detail = resp.text.strip().replace("\n", " ")[:300]
    if resp.status_code in (401, 403):
        raise ModelError(
            f"{action}鉴权失败（HTTP {resp.status_code}）：API Key 无效、已过期或未开通该模型权限，"
            f"请到服务商控制台确认后更新 .env 中的密钥（服务端返回：{detail or '无响应内容'}）"
        )
    raise ModelError(f"{action}失败（HTTP {resp.status_code}）：{detail or '无响应内容'}")


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量文本向量化，保持输入顺序返回向量列表。"""
    if not texts:
        return []
    if not config.EMBEDDING_API_KEY:
        raise ModelError("未配置 EMBEDDING_API_KEY / OPENAI_API_KEY")

    vectors: list[list[float]] = []
    headers = {"Authorization": f"Bearer {config.EMBEDDING_API_KEY}"}
    async with httpx.AsyncClient(timeout=60) as client:
        for start in range(0, len(texts), config.EMBED_BATCH_SIZE):
            batch = texts[start : start + config.EMBED_BATCH_SIZE]
            resp = await client.post(
                f"{config.EMBEDDING_BASE_URL}/embeddings",
                headers=headers,
                json={"model": config.EMBEDDING_MODEL, "input": batch},
            )
            _raise_for_response(resp, "向量化请求")
            data = sorted(resp.json()["data"], key=lambda item: item.get("index", 0))
            if len(data) != len(batch):
                raise ModelError("向量化返回数量与输入不一致")
            vectors.extend(item["embedding"] for item in data)
    return vectors


async def chat_completion(messages: list[dict[str, str]], temperature: float = 0.3) -> str:
    """调用对话模型并返回回答文本。"""
    if not config.OPENAI_API_KEY:
        raise ModelError("未配置 OPENAI_API_KEY")

    payload: dict[str, Any] = {
        "model": config.CHAT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{config.OPENAI_BASE_URL}/chat/completions", headers=headers, json=payload
        )
    _raise_for_response(resp, "对话请求")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelError("对话接口返回格式异常") from exc
    return (content or "").strip()
