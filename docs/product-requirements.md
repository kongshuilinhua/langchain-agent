# Product Requirements

本文档记录近期需要补齐的产品口径，重点覆盖用户自配模型、数据存储位置和对话页 RAG 开关。它是后续后端、前端和测试验收的共同依据。

## 1. 模型配置主路径

### 产品目标

平台默认不把 GPT 作为推荐或默认模型。面向用户的默认路径是用户自己配置 OpenAI-compatible 协议的模型网关，优先提供 Qwen/DashScope 预设，同时允许接入 DeepSeek、Moonshot、智谱、百川等国产或私有兼容网关。

这里的 `OpenAI-compatible` 只表示接口协议，不表示默认使用 OpenAI 或 GPT。只有用户显式配置 OpenAI 网关和 GPT 模型时，平台才会调用 GPT。

### 用户体验

- 左下角账号菜单或设置页提供“我的模型”入口。
- “我的模型”列表展示用户自己的主聊天模型配置，字段包括显示名、聊天网关地址、聊天模型、上下文长度、默认温度、启用状态和默认配置标记。图片探测只作为诊断状态，不作为聊天发送门禁；文档附件由后端解析成文本，不作为模型能力开关。
- 新建模型时提供“Qwen 快捷预设”，自动填入：
  - `base_url=https://dashscope.aliyuncs.com/compatible-mode/v1`
  - `chat_model=qwen-plus`
  - `provider=openai-compatible`
  - `supports_document=true`
  - `supports_image=false`
  - `max_context=131072`
  - `default_temperature=0.4`
- 聊天 API key 是写入型字段。前端只在创建或替换时显示输入框，保存后只显示 `has_api_key=true/false`，不能回显明文。
- 模型编辑弹窗提供“测试连接”按钮。测试必须检查文本聊天连通性，并可选发起图片请求辅助诊断视觉能力；图片测试失败不等于聊天不能发送图片，也不应成为前端或后端运行时拦截条件。测试失败时只显示清洗后的错误，不显示请求头、密钥、完整上游响应或堆栈。
- 智能体配置页的模型选择优先展示“我的模型”，系统预设模型只作为次级选项或本地兜底。
- 用户选择私有模型时，智能体保存 `user_model_config_id`，并清空管理员系统预设的 `model_id`。
- 后端默认配置、`.env.example`、初始化种子模型和测试样例都应优先使用 Qwen/DashScope 示例。不得把 `gpt-*` 作为默认推荐项。

### 运行规则

运行时模型解析顺序：

1. 智能体绑定的 `user_model_config_id`。
2. 当前用户的默认且已启用私有模型配置。
3. 本地开发环境变量兜底，例如 `DASHSCOPE_API_KEY`、`OPENAI_API_BASE`、`OPENAI_MODEL`。
4. mock LLM，仅用于本地开发和 CI。

管理员维护的 `model_configs` 保留为系统预设、能力模板和本地兜底，不再作为普通用户的主要模型配置入口。

RAG/Embedding/Reranker 等基础检索模型由后端环境统一配置，例如 `OPENAI_EMBEDDING_MODEL=text-embedding-v4`。用户不在“我的模型”或智能体配置里单独选择 embedding 模型。

图片附件的运行时规则独立于图片探测结果：前端允许用户上传、粘贴并发送图片；后端把图片转换为 OpenAI-compatible `image_url` 内容交给当前聊天模型。如果模型或网关不支持图片，返回的上游错误或提示会作为聊天错误显示。文档附件仍受 `supports_document` 控制，因为文档解析是平台本地能力。

### 验收标准

- 新用户看到的推荐模型配置是 Qwen/DashScope 或“用户自配兼容网关”，不是 GPT。
- README、Quickstart、`.env.example` 和界面文案不把 `gpt-*` 写成默认推荐模型。
- 后端本地 fallback 和初始化种子模型不把 `gpt-*` 放在首个默认模型位置；如保留 GPT 示例，必须标为可选兼容网关示例。
- `/api/user-models` 全部响应不包含明文 `api_key`。
- 跨用户访问私有模型配置返回 `404 Model config not found`。
- 被智能体引用的私有模型配置不能删除，应返回 `409 Model config is in use`。
- 发布快照可保存 `user_model_config_id` 和非密钥参数，但不能保存明文或加密 API key。

## 2. 智能体、对话和知识数据存储

### 业务数据库

Docker Compose 和生产目标使用 PostgreSQL。当前开发部署把 PostgreSQL、Redis 和 Milvus 放在虚拟机 `192.168.150.101`，Windows 本机后端通过虚拟机 IP 访问；Compose 内部 API 容器仍连接 `postgres:5432`。以下业务数据都属于主业务数据库：

```env
DATABASE_URL=postgresql+psycopg2://lingshu:lingshu@192.168.150.101:5433/lingshu_agent
```

| 数据 | 表 | 说明 |
| --- | --- | --- |
| 用户、空间、角色 | `users`、`workspaces`、`workspace_members` | 本地账号、管理员/普通用户权限；首个用户为管理员，后续注册用户为普通用户 |
| 用户私有模型 | `user_model_configs` | 保存用户自己的 base URL、模型名、能力参数和加密后的 API key |
| 管理员系统预设 | `model_configs` | 系统预设和本地兜底模型，不保存用户私有密钥 |
| 智能体基础信息 | `agents` | 名称、头像、简介、system prompt、模型引用、状态和发布指针 |
| 智能体增强配置 | `agent_settings` | 推荐问、变量、记忆配置、RAG 默认开关、top_k 和 tool policy |
| 发布快照 | `agent_versions` | 发布或提交审核时冻结配置、绑定关系、工作流和 settings |
| 知识库元数据 | `knowledge_bases`、`knowledge_documents`、`knowledge_chunks` | 知识库、文档、chunk 文本和向量 id |
| 知识库绑定 | `agent_knowledge_bases` | 智能体绑定哪些知识库 |
| 工具绑定 | `tools`、`agent_tools` | 内置工具定义和智能体工具绑定 |
| 对话会话 | `sessions` | 某个用户和某个智能体下的一条会话 |
| 对话消息 | `messages` | 用户消息、assistant 消息、消息 sources |
| 会话记忆 | `session_memory` | 当前只保存 session summary |
| 运行调试记录 | `runs`、`run_steps` | 后端内部执行步骤和调试输出 |
| 消息反馈 | `feedback` | assistant 消息的有用/无用反馈 |
| 聊天附件 | `uploads` | 图片 data URL、文档抽取文本、文件元数据 |

### 向量数据

- 知识库 chunk 的元数据和原文存放在 `knowledge_chunks`。
- 向量本体存放在 Milvus；本地开发可以使用内存向量索引。
- 每条向量必须能按 `workspace_id`、`knowledge_base_id`、`document_id` 过滤和清理。

### 本地文件

- `storage/uploads/`：本地上传文件派生数据，具体取决于上传实现。
- `logs/`：本地运行日志。
- `frontend/dist/`、`frontend/node_modules/`：前端生成物和依赖。

这些目录都是本地运行产物，不应提交到 Git。

### 数据边界

- 市场复制只复制智能体发布快照，不复制原作者的会话、消息、反馈、run 记录或用户私有模型密钥。
- 聊天附件只服务本轮上下文，不自动进入知识库。
- session memory 只服务当前 session，不做跨 session、跨智能体或长期用户画像。
- `run_steps` 是调试数据，默认不在普通聊天界面展示。

## 3. 对话页 RAG 开关

### 产品目标

RAG 不只是在智能体配置页设置默认值，也要在对话界面提供明确开关，让用户能在发送前决定本轮是否检索绑定知识库。

### 界面要求

- 聊天输入区工具栏展示 RAG 开关，建议文案为“知识库”或“RAG”。
- 开关状态必须一眼可见：开启表示本轮会检索绑定知识库，关闭表示本轮不检索知识库。
- 默认状态来自当前智能体的 `rag.enabled_by_default`。用户在聊天页切换后，仅影响当前输入区后续发送的请求，不直接改写智能体配置。
- 当当前智能体没有绑定知识库时，RAG 开关置灰或显示不可用状态，并提示“当前智能体未绑定知识库”。
- 关闭 RAG 后，仍然允许使用本轮附件上下文和已启用工具。
- 有 sources 时在回答区域展示来源；关闭 RAG 或无命中时不展示空引用区域。

### 接口规则

聊天请求继续使用 `rag_enabled` 作为单轮覆盖字段：

```json
{
  "message": "这台设备报错 E12 怎么处理？",
  "session_id": 12,
  "mode": "published",
  "rag_enabled": true
}
```

- `rag_enabled` 省略：使用智能体发布快照或草稿里的 `rag.enabled_by_default`。
- `rag_enabled=true`：检索绑定知识库，可能返回 `sources` 事件。
- `rag_enabled=false`：不检索绑定知识库，不返回 `sources` 事件。

### 验收标准

- 主对话页和智能体预览区都能看到 RAG 开关。
- 切换开关后，下一次 `POST /api/agents/{agent_id}/chat/stream` 请求体包含正确的 `rag_enabled`。
- 后端 `run_step` 或调试输出能记录本轮 `rag_enabled` 的实际值。
- `rag_enabled=false` 时，即使智能体绑定了知识库，也不会返回知识库来源。
- 已发布模式读取发布快照中的默认 RAG 配置；发布后修改草稿默认值不会影响旧发布版本。



