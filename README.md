# RAG 知识库智能助手

基于 RAG（检索增强生成）的自动回复机器人，包含面向用户的问答页和面向管理员的知识库管理页。回答严格基于管理员上传的文档，并展示引用来源；知识库没有覆盖的问题会明确告知，不做编造。

## 功能

- 智能问答：多轮对话、流式输入体验、回答附带引用来源与相关度
- 知识库管理：拖拽/批量上传、解析状态轮询、文档删除、统计概览
- 文档解析：支持 PDF、DOCX、TXT、Markdown，按句子边界切块并保留重叠
- 检索方式可切换：内置中文 BM25 关键词检索（默认，无需向量接口），或调用 OpenAI 兼容的向量接口
- 模型接入：任意 OpenAI 兼容协议服务（本示例为商汤日日新）
- 数据本地化：SQLite 存储文档与分块，文件保存在 `data/` 目录

## 技术栈

- 后端：FastAPI + Uvicorn + httpx + SQLite
- 前端：原生 HTML / CSS / JavaScript（无需构建）
- 文档解析：pypdf、python-docx

## 目录结构

```
app/
  main.py        FastAPI 入口与接口路由
  config.py      .env 配置读取
  database.py    SQLite 存储（文档、分块、向量）
  ingest.py      文档解析、切块与入库
  bm25.py        本地 BM25 关键词检索
  rag.py         检索 + 提示词组装 + 回答生成
  llm.py         OpenAI 兼容的对话与向量接口封装
  static/        前端页面与静态资源
    index.html   问答页
    admin.html   知识库管理页
    assets/      样式与脚本
doc/             示例知识库文档
data/            运行时数据（数据库与上传文件，已忽略）
```

## 快速开始

```powershell
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 配置模型密钥
copy .env.example .env
# 编辑 .env，填入 OPENAI_BASE_URL / OPENAI_API_KEY / CHAT_MODEL

# 3. 启动服务
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动后访问：

- 问答页：http://127.0.0.1:8000/
- 管理页：http://127.0.0.1:8000/admin

先在管理页上传文档，等待状态变为「已就绪」，即可在问答页提问。

## 配置说明（.env）

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `OPENAI_BASE_URL` | 对话模型 OpenAI 兼容地址 | `https://token.sensenova.cn/v1` |
| `OPENAI_API_KEY` | 模型 API Key | 无 |
| `CHAT_MODEL` | 对话模型 ID | `sensenova-6.8-flash-lite` |
| `EMBEDDING_PROVIDER` | 检索方式：`bm25` 或 `api` | `bm25` |
| `EMBEDDING_MODEL` | 向量模型 ID，`api` 模式生效 | `sensenova-embedding` |
| `EMBEDDING_BASE_URL` | 向量接口地址，默认复用 `OPENAI_BASE_URL` | 无 |
| `EMBEDDING_API_KEY` | 向量接口密钥，默认复用 `OPENAI_API_KEY` | 无 |
| `CHUNK_SIZE` | 分块长度（字符） | `500` |
| `CHUNK_OVERLAP` | 分块重叠长度（字符） | `80` |
| `TOP_K` | 检索条数 | `5` |
| `MIN_SCORE` | 向量检索最低相似度 | `0.2` |
| `EMBED_BATCH_SIZE` | 向量化批大小 | `16` |
| `MAX_FILE_MB` | 上传文件大小上限（MB） | `20` |
| `ADMIN_PASSWORD` | 管理页口令，留空则不校验 | 空 |
| `DATA_DIR` | 数据目录，默认项目下 `data/` | 无 |
| `DB_PATH` | 数据库路径，默认 `data/rag.db` | 无 |

### 切换为向量检索

如果所用服务商提供 OpenAI 兼容的向量接口：

```dotenv
EMBEDDING_PROVIDER=api
EMBEDDING_BASE_URL=https://your-provider/v1
EMBEDDING_MODEL=your-embedding-model
```

切换后需要清空知识库并重新上传文档，使分块带上向量数据。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/chat` | 提问，返回回答与引用来源 |
| GET | `/api/health` | 健康检查与模型、统计信息 |
| GET | `/api/admin/overview` | 管理概览：统计与脱敏后的配置 |
| GET | `/api/admin/documents` | 文档列表 |
| POST | `/api/admin/documents` | 上传文件（multipart，字段名 `files`） |
| DELETE | `/api/admin/documents/{id}` | 删除文档及其分块 |

设置了 `ADMIN_PASSWORD` 时，管理接口需携带请求头 `X-Admin-Token: <口令>`。

## 常见问题

**问答返回 502 / 鉴权失败（HTTP 401）**

模型网关拒绝了 Key。请确认 Key 有效、已开通对应模型权限，并确认 `OPENAI_BASE_URL` 与 `CHAT_MODEL` 匹配服务商文档。

**上传后状态为「失败」，错误提示向量化请求 404**

当前服务商的 `/v1/embeddings` 不可用。请保持 `EMBEDDING_PROVIDER=bm25`，或更换支持向量接口的服务商后按上文切换。

**回答提示「知识库中暂无相关信息」**

检索没有命中：确认文档状态为「已就绪」，并尝试使用文档中的关键词提问；BM25 属于关键词检索，对同义改写不敏感。

**PDF 解析不到文字**

扫描版 PDF 没有文本层，需要先做 OCR 再上传。

## 说明

- `.env`、`data/`、`.venv/` 已在 `.gitignore` 中忽略，不会提交密钥和运行数据
- 管理页默认无口令，公网部署前请设置 `ADMIN_PASSWORD`
