# Lingshu Agent

---

## 项目概述

Lingshu Agent 是一个本地可运行的自定义智能体平台，提供完整的闭环能力，包括：
- **聊天页面**（GPT 风格主聊天页）
- **智能体配置页**（Coze 风格）
- **用户私有模型配置**
- **知识库 RAG**
- **工具集成**
- **发布审核、内部市场复制**
- **会话恢复、头像和个人资料**

项目旨在帮助开发者快速搭建具备多模态、检索增强（RAG）以及可自定义模型的对话系统。

---

## 核心功能

- **账号体系**：本地注册/登录、JWT 鉴权、个人资料管理、头像上传、注销。
- **角色管理**：`admin` 与 `user` 两种角色，管理员可审核智能体并查看成员只读列表。
- **模型配置**：在 “我的模型” 页面配置 `base_url`、`api_key`、模型名称、深度思考能力及常用参数。系统模型仅作预设/兜底。
- **智能体管理**：创建、编辑、删除、草稿调试、发布；普通用户发布后需管理员审核，审核通过后进入内部市场，其他用户可复制使用。
- **聊天交互**：仅可选择已审核发布的智能体；聊天支持 Markdown、表格、代码块复制；可按模型能力开启单轮 “深度思考”。
- **多模态与附件**：支持图片上传、粘贴以及 TXT/MD/CSV/PDF/DOCX 文档。图片直接随聊天请求发送至模型；文档解析为本轮上下文，不自动入库。
- **RAG 与检索**：默认开启 RAG 开关，支持单轮 RAG pill，提供 `rag_options` 覆盖。检索链路包括 parent‑child chunk、dense retrieval、中文 BM25、RRF、可选 `qwen3‑rerank`、Redis 缓存、结构化引用与证据不足拒答。
- **知识库**：创建、文本/文件入库、同步索引、文档列表、删除文档（会清理 PostgreSQL chunk 与向量数据）。
- **工具集成**：内置工具和用户自定义 HTTP 工具的 CRUD、测试、绑定与运行记录。
- **会话记忆**：Session summary 记忆；发布快照影响草稿/已发布聊天。
- **评测**：提供 `eval/rag_cases.jsonl` 与运行脚本 `python eval/run_rag_eval.py --mock` 用于 RAG 评估。

---

## 技术栈与框架

- **后端**：FastAPI（Python 3.11），使用 Uvicorn 作为 ASGI 服务器。
- **前端**：Vite + Vue 3（或 React，项目中实际使用 Vue），采用 TypeScript 与 Tailwind CSS（已固定 `127.0.0.1:5174 --strictPort`）。
- **数据库**：PostgreSQL（通过 SQLAlchemy ORM 访问），默认连接字符串在 `.env` 中配置。
- **向量检索**：默认使用内存实现（`LINGSHU_VECTOR_BACKEND=memory`），可切换为 Milvus（`MILVUS_COLLECTION`、`MILVUS_DIMENSION` 配置）。
- **RAG 模型**：支持 Qwen、DashScope 兼容 OpenAI 接口，环境变量 `OPENAI_API_BASE`、`OPENAI_MODEL`、`OPENAI_EMBEDDING_MODEL` 配置。
- **容器化**：提供 `Dockerfile.api` 与 `docker-compose.yml`，便于一键部署。
- **测试**：使用 PyTest，覆盖单元测试与集成测试。

---

## 环境变量与关键配置

```env
# 安全密钥（请自行替换为长随机字符串）
JWT_SECRET=replace-with-a-long-random-secret

# API Key 加密密钥（可选）
API_KEY_ENCRYPTION_KEY=

# 是否启用邀请 API
INVITE_API_ENABLED=false

# 数据库连接（请根据实际部署修改）
DATABASE_URL=postgresql+psycopg2://lingshu:lingshu@192.168.150.101:5433/lingshu_agent

# OpenAI 兼容网关（默认使用阿里云 DashScope）
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=
OPENAI_MODEL=qwen-plus
OPENAI_EMBEDDING_MODEL=text-embedding-v4

# 向量后端配置（memory 或 Milvus）
LINGSHU_VECTOR_BACKEND=memory
MILVUS_COLLECTION=lingshu_chunks
MILVUS_DIMENSION=

# RAG 参数
RAG_TOP_K=4
RAG_DENSE_TOP_K=12
RAG_BM25_TOP_K=12
RAG_RRF_K=60
RAG_RERANK_ENABLED=true
RAG_RERANK_MODEL=qwen3-rerank
RAG_CACHE_TTL_SECONDS=3600

# 上传文件大小上限（8 MB）
UPLOAD_MAX_BYTES=8388608
```

**端口约束**（不可变）
- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5174`

如果端口被占用，请先停止旧进程后仍使用同一端口，不会自动切换。

```powershell
Get-NetTCPConnection -LocalPort 8000,5174 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

---

## 快速启动

```powershell
# 复制环境变量示例并自行填写
Copy-Item .env.example .env

# 安装依赖
pip install -r requirements.txt

# 启动后端 API（默认 8000 端口）
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

前端开发（确保已安装 Node.js）

```powershell
cd frontend
npm install
npm run dev   # 访问 http://127.0.0.1:5174
```

---

## 主要 API 列表

- **Auth**: `POST /api/auth/register`, `POST /api/auth/login`, `GET/PATCH /api/auth/me`
- **Members**: `GET /api/workspaces/members`（只读成员列表）
- **User Models**: `GET/POST/PATCH/DELETE /api/user-models`, `POST /api/user-models/{id}/test`
- **System Models**: `GET /api/models`, `POST/PATCH/DELETE /api/admin/models`
- **Agents**: `GET/POST /api/agents`, `GET/PATCH/DELETE /api/agents/{id}`, `POST /api/agents/{id}/publish`
- **Review/Market**: `GET /api/admin/agent-reviews`, `POST /api/admin/agent-reviews/{id}/approve`, `GET /api/market/agents`, `POST /api/market/agents/{id}/copy`
- **Knowledge**: `GET/POST /api/knowledge-bases`, `POST /api/knowledge-bases/{id}/documents`, `POST /api/knowledge-bases/{id}/index`, `GET /api/knowledge/jobs/{job_id}`
- **Chat**: `POST /api/agents/{id}/chat/stream`
- **Sessions/Runs/Feedback**: `GET /api/sessions/{id}`, `GET /api/runs/{id}`, `POST /api/messages/{id}/feedback`

---

## 文档与帮助

- **快速入门**：`docs/quickstart.md`
- **产品需求**：`docs/product-requirements.md`
- **架构说明**：`docs/architecture.md`
- **API 设计**：`docs/api-design.md`
- **存储设计**：`docs/storage-design.md`
- **RAG 设计**：`docs/rag-design.md`
- **部署说明**：`docs/deployment.md`
- **故障排查**：`docs/troubleshooting.md`
- **贡献指南**：`CONTRIBUTING.md`
- **变更记录**：`CHANGELOG.md`

---

## 贡献指南

欢迎提交 Pull Request！在提交前请运行以下检查脚本确保代码质量：

```powershell
python -m pytest -q
python scripts/check_markdown_links.py
python scripts/check_text_encoding.py README.md docs/**/*.md
python scripts/release_check.py --with-frontend
```

---

## 许可证

本项目遵循 MIT 许可证，详细内容请参见 `LICENSE` 文件。

---
