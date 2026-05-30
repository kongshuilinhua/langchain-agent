# Changelog

## 0.1.0-unreleased

### Changed

- 项目重做为团队空间版自定义智能体平台。
- 默认入口改为 FastAPI + React 应用，登录后先进入 GPT 风格主页面。
- 主数据模型改为 workspace、agent、knowledge base、workflow、session 和 run。
- 旧扫地机器人客服能力降级为内置模板场景。
- 模型接口改为 OpenAI-compatible。
- 目标向量库改为 Milvus，本地测试支持内存 fallback。
- 主业务数据库目标改为 PostgreSQL。

### Added

- 完整 RAG 链路：parent-child chunk、dense retrieval、中文 BM25、RRF、可选 `qwen3-rerank`、Redis 查询缓存、结构化引用和证据不足拒答。
- `rag_options` 单轮覆盖，扩展 `rag_status` 输出 dense/BM25/RRF/rerank/cache/no-evidence 状态。
- Milvus collection 维度支持从 `MILVUS_DIMENSION` 或首次真实 embedding 自动确定，不再写死 32 维。
- RAG 和上传关键默认值进入 `.env.example`：`RAG_*`、`MILVUS_DIMENSION`、`UPLOAD_MAX_BYTES`。
- `GET /api/knowledge/jobs/{job_id}` 知识库索引任务状态兼容接口。
- RAG eval smoke：`eval/rag_cases.jsonl` 和 `eval/run_rag_eval.py --mock`。
- 管理员成员只读列表页面；最终版不提供邀请用户和邀请列表 UI。
- 前端引入 Markdown/GFM 渲染，支持表格、链接、引用、代码块复制和横向滚动。
- 本地账号 + JWT。
- 当前用户资料更新接口，支持修改姓名和上传头像。
- 管理员和普通用户两角色，旧本地数据中的 Owner/Member 会兼容映射。
- 首个注册用户自动成为管理员，后续注册用户自动成为普通用户；成员列表为管理员只读视图。
- 按智能体列出会话、恢复会话消息和同一 session 多轮续聊。
- 管理员模型管理：创建、启用/停用模型，维护 provider、模型名、显示名、文本/图片/文档能力、上下文长度和默认温度。
- 深度思考能力：用户模型和系统模型可声明 `supports_reasoning` / `reasoning_type`，聊天输入区可按单轮开启，调试流输出 `thinking_status`。
- 用户私有模型的图片能力改为显式声明 + 探测确认；图片探测失败只显示未确认，不再误写为模型不支持图片。
- 会话标题编辑。
- 智能体创建、编辑、草稿、发布版本、管理员审核和团队内市场复制。
- Coze/GPT Builder 风格智能体 settings：推荐问、变量、默认 RAG 开关、session summary 记忆和 tool policy。
- `agent_settings` 表，用于保存推荐问、变量、记忆和工具策略。
- `session_memory` 表，用于按会话保存摘要记忆。
- `model_configs` 表，用于保存管理员维护的模型列表和能力标签。
- `uploads` 表，用于保存聊天本轮图片附件和文档抽取文本。
- 智能体删除功能：非模板智能体可按权限删除，并清理关联会话、消息、反馈、运行记录、发布版本和绑定关系。
- 聊天请求 `mode=draft|published`，草稿调试使用当前配置，已发布预览使用发布快照。
- 聊天请求 `rag_enabled`，可按单轮覆盖智能体默认 RAG 配置。
- 聊天请求 `attachments`，支持图片和 TXT/MD/CSV/PDF/DOCX 文档作为单轮上下文。
- 主对话页只允许选择已通过审核并上架的智能体，草稿和待审核智能体留在配置页调试。
- 聊天请求 `variables`，运行记录会输出合并后的变量。
- 模型能力校验：图片附件要求视觉模型，文档附件要求支持文档上下文的模型。
- 运行记录输出 `used_memory` 和 `citation_count`。
- 知识库创建、文本上传、文档列表、文档删除和索引清理。
- 后端保留默认执行链路；前端不展示五步节点卡片或工作流画布。
- SSE 聊天事件：`run_step`、`token`、`sources`、`done`、`error`。
- 弹窗交互修复：普通表单和确认弹窗不再因为点击遮罩区域而意外关闭。
- Assistant 消息正向/负向反馈。
- 运行步骤详情展开。
- GPT 风格主聊天页、真实账号菜单和 Coze 风格智能体配置工作台。
- ChatGPT 风格消息排版：用户消息在右侧，assistant 消息在左侧。
- Assistant 消息 Markdown 和代码块渲染，代码块支持复制。
- 聊天输入区上传图片/文档，并提供本轮 RAG 开关。
- Docker Compose：api、frontend、postgres、milvus、redis。
- 后端平台测试和发布检查脚本。


