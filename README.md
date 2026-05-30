# Lingshu Agent

Lingshu Agent 是一个本地可运行的自定义智能体平台。当前最终版提供 GPT 风格主聊天页、Coze 风格智能体配置页、用户私有模型配置、知识库 RAG、工具、发布审核、内部市场复制、会话恢复、头像和个人资料等闭环能力。

默认推荐 Qwen/DashScope 或用户自有 OpenAI-compatible 网关，不推荐 GPT 作为默认模型。`OPENAI_*` 环境变量只是兼容协议命名。

## 当前能力

- 账号：本地注册/登录、JWT、个人资料、头像、退出登录。
- 角色：只保留 `admin` 和 `user`。管理员可审核智能体、查看成员只读列表；不做邀请用户 UI。
- 模型：用户在“我的模型”里配置 `base_url`、`api_key`、模型名、深度思考能力和常用参数；API key 不回显。系统模型仅作为预设/兜底。
- 智能体：创建、编辑、删除、草稿调试、发布；普通用户发布后需要管理员审核，通过后进入市场，其他用户可复制使用。
- 聊天：只允许选择已审核发布的智能体；用户消息和 assistant 消息左右分侧；assistant 支持 Markdown、表格和代码块复制；支持按模型能力开启单轮“深度思考”。
- 多模态与附件：聊天可上传、粘贴图片，也可上传 TXT/MD/CSV/PDF/DOCX 文档。图片不会被 `supports_image` 预判拦截，会直接随聊天请求交给所选模型；如果上游模型或网关不支持图片，真实返回会显示在聊天里。文档会解析成本轮上下文，不自动入知识库。
- RAG：智能体默认 RAG 开关 + 聊天单轮 RAG pill 开关；支持 `rag_options` 覆盖。
- 检索链路：parent-child chunk、dense retrieval、中文 BM25、RRF、可选 `qwen3-rerank`、Redis 查询缓存、结构化引用和证据不足拒答。
- 知识库：创建、文本/文件入库、同步索引、文档列表、删除文档；删除会清理 PostgreSQL chunk 和向量数据。
- 工具：内置工具和用户 HTTP 工具 CRUD、测试、绑定与运行记录。
- 记忆：session summary 记忆；进入发布快照并影响草稿/已发布聊天。
- 评测：提供 `eval/rag_cases.jsonl` 和 `eval/run_rag_eval.py --mock`。

不做：工作流画布、OAuth、计费、公开 API/embed、复杂 RBAC、公开 SaaS 市场、多租户运营后台、邀请用户页面、邀请列表页面。

## 固定端口

本地端口不可变：

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5174`

如果端口被占用，停止旧进程后仍使用同一端口，不切换到其他端口。

```powershell
Get-NetTCPConnection -LocalPort 8000,5174 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

## 快速启动

```powershell
Copy-Item .env.example .env
pip install -r requirements.txt
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

Vite 已固定 `127.0.0.1:5174 --strictPort`。

## 关键配置

```env
JWT_SECRET=replace-with-a-long-random-secret
API_KEY_ENCRYPTION_KEY=
INVITE_API_ENABLED=false
DATABASE_URL=postgresql+psycopg2://lingshu:lingshu@192.168.150.101:5433/lingshu_agent
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=
OPENAI_MODEL=qwen-plus
OPENAI_EMBEDDING_MODEL=text-embedding-v4
LINGSHU_VECTOR_BACKEND=memory
MILVUS_COLLECTION=lingshu_chunks
MILVUS_DIMENSION=
RAG_TOP_K=4
RAG_DENSE_TOP_K=12
RAG_BM25_TOP_K=12
RAG_RRF_K=60
RAG_RERANK_ENABLED=true
RAG_RERANK_MODEL=qwen3-rerank
RAG_CACHE_TTL_SECONDS=3600
UPLOAD_MAX_BYTES=8388608
```

真实聊天模型优先在前端“我的模型”中由用户自己配置；环境变量是后端 embedding、rerank 和开发兜底配置。

## 常用命令

```powershell
python -m pytest -q
python eval/run_rag_eval.py --cases eval/rag_cases.jsonl --mock
python scripts/check_markdown_links.py
python scripts/check_text_encoding.py README.md docs CHANGELOG.md CONTRIBUTING.md
python scripts/release_check.py --with-frontend
```

前端构建：

```powershell
cd frontend
npm run build
```

## 主要 API

- Auth: `POST /api/auth/register`, `POST /api/auth/login`, `GET/PATCH /api/auth/me`
- Members: `GET /api/workspaces/members`，只读成员列表
- User models: `GET/POST/PATCH/DELETE /api/user-models`, `POST /api/user-models/{id}/test`。测试入口在“我的模型”的编辑弹窗里，图片探测只作诊断，不决定聊天能否发送图片。
- System models: `GET /api/models`, `POST/PATCH/DELETE /api/admin/models`
- Agents: `GET/POST /api/agents`, `GET/PATCH/DELETE /api/agents/{id}`, `POST /api/agents/{id}/publish`
- Review/market: `GET /api/admin/agent-reviews`, `POST /api/admin/agent-reviews/{id}/approve`, `GET /api/market/agents`, `POST /api/market/agents/{id}/copy`
- Knowledge: `GET/POST /api/knowledge-bases`, `POST /api/knowledge-bases/{id}/documents`, `POST /api/knowledge-bases/{id}/index`, `GET /api/knowledge/jobs/{job_id}`
- Chat: `POST /api/agents/{id}/chat/stream`
- Sessions/runs/feedback: `GET /api/sessions/{id}`, `GET /api/runs/{id}`, `POST /api/messages/{id}/feedback`

## 文档

- [快速启动](docs/quickstart.md)
- [产品需求](docs/product-requirements.md)
- [架构说明](docs/architecture.md)
- [API 设计](docs/api-design.md)
- [存储设计](docs/storage-design.md)
- [RAG 设计](docs/rag-design.md)
- [评测设计](docs/evaluation.md)
- [部署说明](docs/deployment.md)
- [故障排查](docs/troubleshooting.md)
- [贡献指南](CONTRIBUTING.md)
- [变更记录](CHANGELOG.md)
