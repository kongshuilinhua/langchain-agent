# Agent 初学者指南

## 目录
1. 项目概述
2. 技术栈详解
3. 项目结构
4. 关键概念与约束
5. 常见开发流程
6. 调试与测试
7. 部署与运行
8. 常见问题 (FAQ)

---

## 1. 项目概述

**Lingshu Agent** 是一个本地可运行的自定义智能体平台，提供从前端聊天界面到后端模型推理的完整闭环能力。它旨在让开发者无需搭建复杂的云服务，即可在本地快速实验多模态对话、知识库检索（RAG）以及自定义工具调用。

---

## 2. 技术栈详解

| 层级 | 技术 | 作用 | 学习建议 |
|------|------|------|----------|
| **后端** | **FastAPI** (Python 3.11) | 高性能的 HTTP API 框架，支持异步、自动生成 OpenAPI 文档。 | 阅读官方快速入门章节，关注 `@app.post`、`@app.get` 装饰器以及依赖注入 (`Depends`)。
| | **Uvicorn** | ASGI 服务器，用于运行 FastAPI 应用。 | `uvicorn api.main:app --reload` 即可启动开发服务器。
| | **SQLAlchemy** + **PostgreSQL** | ORM 与数据库，管理用户、智能体、会话等持久化数据。 | 了解模型类 (`BaseModel`) 与会话 (`Session`) 的基本用法。
| | **Pydantic** | 数据校验与序列化，定义请求/响应模型。 | 查看 `BaseModel` 子类的字段声明方式。
| **前端** | **Vite** + **Vue 3** (或 React) | 前端开发工具链与框架，提供热更新、模块化构建。 | Vite 文档的 `dev server` 与 `build` 部分；Vue 3 官方教程的 `Composition API`。
| | **TypeScript** | 静态类型检查，提升代码可维护性。 | 学习基础类型、接口 (`interface`) 与泛型。
| | **Tailwind CSS** (已固定) | 实用的原子化 CSS，快速搭建 UI。 | 浏览官方 `utility-first` 示例，理解类名组合。
| **向量检索** | **Memory** (默认) / **Milvus** (可选) | 用于存储文档向量，实现 RAG 检索。 | Memory 是 Python dict，适合小数据；Milvus 需要额外部署，可查官方文档了解概念。
| **模型** | **OpenAI‑compatible 接口**（如 Qwen、DashScope） | 对话、嵌入、重排序模型的统一调用入口。 | 关注 `OPENAI_API_BASE`、`OPENAI_MODEL`、`OPENAI_EMBEDDING_MODEL` 环境变量的意义。

---

## 3. 项目结构

```
langchain/
├─ api/               # FastAPI 路由和业务逻辑
├─ core/              # 核心模型、工具与 RAG 实现
├─ data/              # 示例数据、初始化脚本
├─ docs/              # 项目文档（包括本指南）
│   ├─ agent_guide.md # **本文件**
│   └─ ...
├─ frontend/          # Vue 前端代码
├─ scripts/           # 辅助脚本（检查、发布等）
├─ tests/             # PyTest 单元/集成测试
├─ Dockerfile.api      # 用于容器化后端
├─ docker-compose.yml # 一键启动后端、数据库、Milvus（可选）
└─ README.md          # 面向公众的项目介绍（已在 GitHub）
```

- **api/**：主要入口，`api/main.py` 创建 `FastAPI` 实例，加载子路由（`auth`, `agents`, `knowledge` 等）。
- **core/**：实现 RAG 检索、工具调用、对话流水线。这里的代码大多是与模型交互的抽象层。
- **frontend/**：使用 Vite + Vue 构建的 SPA，指向后端 API 完成聊天、智能体配置等功能。
- **docs/**：存放所有面向开发者的文档，**不上传到 GitHub**的内容放在此目录下（如本指南、内部约束文档）。

---

## 4. 关键概念与约束

1. **端口约束**（不可变）
   - 后端固定在 `127.0.0.1:8000`
   - 前端固定在 `127.0.0.1:5174`
   - 如冲突，请先停止占用端口的进程（`Get-NetTCPConnection` 示例在 `docs/constraints.md`）。
2. **环境变量**（在 `.env` 中配置）
   - `JWT_SECRET`：用于签发 JWT，必须是强随机字符串。
   - `DATABASE_URL`：PostgreSQL 连接串，确保数据库已启动。
   - `OPENAI_API_BASE`、`OPENAI_MODEL`、`OPENAI_EMBEDDING_MODEL`：决定使用哪款大模型及其嵌入模型。
   - `LINGSHU_VECTOR_BACKEND`：`memory`（默认）或 `milvus`，后者需要额外的 Milvus 服务。
3. **RAG 工作流**
   - **文档切片** → 向量化 → 存入向量库 → 查询时检索相似切片 → 与 LLM 结合生成答案。
   - 关键参数如 `RAG_TOP_K`、`RAG_DENSE_TOP_K` 控制检索返回的切片数量，`RAG_RERANK_ENABLED` 决定是否使用二次排序模型。
4. **工具调用**
   - 系统内置 HTTP 工具（GET/POST）和自定义工具（如文件操作），通过统一的 `tool` 接口暴露给 LLM。
   - 只要在后端 `core/tools/` 注册，即可在对话中通过 `tool_name` 调用。

---

## 5. 常见开发流程

1. **准备环境**
   ```powershell
   cp .env.example .env   # 根据实际情况填写
   pip install -r requirements.txt
   ```
2. **启动后端**
   ```powershell
   uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
   ```
3. **启动前端**
   ```powershell
   cd frontend
   npm install
   npm run dev   # 浏览器打开 http://127.0.0.1:5174
   ```
4. **添加/编辑智能体**
   - 打开前端 UI → “我的智能体” → “新建智能体”。
   - 配置模型、RAG 开关、工具列表后保存。
5. **调试 RAG**
   - 将文档放入 `data/knowledge/`，运行 `python scripts/index_documents.py` 自动切片并写入向量库。
6. **运行测试**
   ```powershell
   python -m pytest -q
   ```
   - 通过后即可提交 PR（如果是团队协作）。

---

## 6. 调试与测试

- **日志**：后端默认使用 `logging`，日志输出到控制台，调试时可在 `api/main.py` 调整 `logging.basicConfig(level=logging.DEBUG)`。
- **单元测试**：`tests/` 目录下的 `test_*.py` 文件覆盖路由、模型包装、RAG 检索等核心功能。
- **快速定位错误**：
  1. 查看前端网络请求（Chrome DevTools → Network），确认返回的 HTTP 状态码。
  2. 后端如果抛异常，检查堆栈信息并对照 `core/` 对应模块。

---

## 7. 部署与运行（生产环境）

1. **Docker Compose**（推荐）
   ```yaml
   version: "3.8"
   services:
     api:
       build: .
       command: uvicorn api.main:app --host 0.0.0.0 --port 8000
       ports:
         - "8000:8000"
       env_file:
         - .env
       depends_on:
         - db
     db:
       image: postgres:15
       environment:
         POSTGRES_USER: lingshu
         POSTGRES_PASSWORD: secret
         POSTGRES_DB: lingshu
       volumes:
         - pg_data:/var/lib/postgresql/data
   volumes:
     pg_data:
   ```
   - `docker compose up -d` 一键启动后端、数据库。
2. **Milvus（可选）**
   - 若使用向量检索的 Milvus，需要在 `docker-compose.yml` 再添加 Milvus 服务并将 `LINGSHU_VECTOR_BACKEND=milvus`。
3. **前端构建**
   ```powershell
   cd frontend
   npm run build   # 生成 dist/，配合 Nginx 部署
   ```
4. **环境变量安全**：生产环境请使用 secrets 管理（如 Docker secret、K8s ConfigMap），切勿把真实密钥直接写进 `.env`。

---

## 8. 常见问题 (FAQ)

| 问题 | 解答 |
|------|------|
| **为什么没有自动切换端口？** | 为了保持 API 稳定性，端口固定。若冲突，请手动停止占用进程或在 `docker-compose.yml` 中自行修改端口映射。 |
| **RAG 检索慢怎么办？** | 检查向量库是否使用 `memory`（小数据快）或 `Milvus`（大数据更佳）。确认 `RAG_TOP_K`、`RAG_DENSE_TOP_K` 没设得过大。 |
| **模型调用报错 `Invalid request`** | 确认 `OPENAI_API_BASE`、`OPENAI_MODEL` 与对应的 API Key 正确，且网络可以访问对应域名。 |
| **前端报 `Failed to fetch`** | 检查后端是否在 `8000` 端口运行，且浏览器 CORS 已在 `api/main.py` 中允许 `http://127.0.0.1:5174`。 |
| **如何添加自定义工具？** | 在 `core/tools/` 新增 Python 类实现统一的 `Tool` 接口，随后在 `api/tools.py` 注册路由即可。 |

---

### 小结

本指南面向 **Agent 初学者**，从整体技术栈、项目结构到常见调试、部署细节全链路覆盖，帮助你快速上手并深入理解每一层的工作原理。所有不适合公开的约束细节已被抽离到 `docs/constraints.md`，仅在本地阅读即可。

如需进一步的案例或源码级别的讲解，请告诉我具体感兴趣的模块，我将为你提供更细化的示例代码。
