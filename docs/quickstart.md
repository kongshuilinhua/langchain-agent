# Quickstart

本文档说明如何运行 Lingshu Agent 自定义智能体平台。

## 本地最小启动

本地开发推荐在虚拟机 `192.168.150.101` 上使用 Docker Compose 提供 PostgreSQL、Redis 和 Milvus，Windows 本机只运行后端和前端。为便于和 MOOC 项目共用一台虚拟机，Compose 会把 PostgreSQL 暴露到虚拟机 `5433`，把 Redis 暴露到虚拟机 `6380`。没有 Milvus 或模型 key 时，可以使用内存向量索引和 mock LLM。

本地 Web 服务端口固定：

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5174`

端口被占用时，停止占用进程后仍然使用同一个端口重启，不要换到其他端口：

```powershell
Get-NetTCPConnection -LocalPort 8000,5174 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess

# 确认占用的是旧的 Lingshu Agent / uvicorn / Vite 进程后再执行：
Get-NetTCPConnection -LocalPort 8000,5174 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

```powershell
$env:LINGSHU_MOCK_LLM="true"
$env:LINGSHU_VECTOR_BACKEND="memory"
$env:DATABASE_URL="postgresql+psycopg2://lingshu:lingshu@192.168.150.101:5433/lingshu_agent"
pip install -r requirements.txt
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

`npm run dev` 固定监听 `127.0.0.1:5174 --strictPort`。如果端口被占用，Vite 会失败而不是自动切换端口。

首次打开前端时注册管理员账号。首个用户会自动初始化本地工作台、内置工具和扫地机器人客服模板。

后续注册的账号会自动成为普通用户。最终版前端不提供邀请用户和邀请列表页面；管理员只能查看成员只读列表。后端邀请接口默认通过 `INVITE_API_ENABLED=false` 关闭。

登录后可以从左下角账号菜单进入设置页，更新头像、姓名，或退出登录。当前头像上传保存在本地数据库中，适合本地 MVP 和演示。

## Qwen/国产兼容模型配置

产品推荐用户在前端“我的模型”里配置自己的模型网关。页面提供 DashScope/Qwen、DeepSeek、Kimi/Moonshot、智谱 GLM、火山方舟/豆包、百度千帆、硅基流动、OpenRouter、Ollama 和自定义兼容网关预设。预设只负责填入常见 `base_url`、模型名和能力开关，保存前应按控制台实际模型名调整。

只要网关兼容 OpenAI Chat Completions 协议，就可以按同一路径接入。前端“我的模型”只填写主聊天模型：`chat_base_url`、`chat_api_key`、`chat_model` 和运行参数。知识库/RAG 使用后端统一配置的 `OPENAI_EMBEDDING_MODEL`，不在用户模型里单独填写。

图片输入不再依赖前端预判能力。新增或编辑模型时，测试会额外发起最小图片请求，但结果只作为诊断信息；聊天框始终允许发送图片，真实模型或网关不支持时，由上游返回错误或提示并显示在聊天里。文档附件会由后端解析成文本上下文，不要求模型支持文件输入。纯聊天模型仍可使用文档附件和后端默认 embedding 进行 RAG 检索。

环境变量只作为本地开发和部署兜底。默认示例使用 Qwen/DashScope，不使用 GPT：

```env
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=your_dashscope_or_compatible_key
OPENAI_MODEL=qwen-plus
OPENAI_EMBEDDING_MODEL=text-embedding-v4
```

变量名里的 `OPENAI` 表示兼容协议的历史命名，不表示必须使用 OpenAI 或 GPT。项目也兼容 `DASHSCOPE_API_KEY`，当 `OPENAI_API_KEY` 为空时会尝试读取它。

## Docker Compose

```bash
docker compose up --build
```

Compose 会启动 API、前端、PostgreSQL、Milvus 和 Redis。

Windows 本机连接虚拟机端口：

- PostgreSQL: `192.168.150.101:5433`
- Redis: `192.168.150.101:6380`
- Milvus: `192.168.150.101:19530`

## 验证

```bash
python scripts/release_check.py
cd frontend
npm run build
```

完整后端测试需要单独的 PostgreSQL 测试库。测试夹具会重置目标库的 `public` schema，不要把 `TEST_DATABASE_URL` 指向正在使用的业务库。

```powershell
$env:TEST_DATABASE_URL="postgresql+psycopg2://lingshu:lingshu@192.168.150.101:5433/lingshu_agent_test"
python -m pytest -q
```

## 常见第一步

1. 注册管理员。
2. 登录后默认进入 GPT 风格主页面，选择内置模板或已有智能体直接聊天。
3. 需要配置时打开“智能体”页面，点击“创建智能体”或“编辑”进入 Coze 风格工作台。
4. 在“人设与回复逻辑”中编辑 Prompt，也可以套用角色扮演模板。
5. 在“编排”里配置模型设置、技能、知识、记忆、变量和对话体验。
6. 新建知识库并上传一段资料，在知识库面板查看文档列表，必要时删除错误文档并重新上传。
7. 在智能体配置中绑定知识库和工具。
8. 在“开场白预置问题”里添加推荐问题；在“变量”里添加 `city` 或 `device_model` 等运行变量。
9. 管理员可以在“设置”页维护模型列表；智能体配置页只能选择已启用模型。
10. 普通用户优先在“我的模型”里添加自己的 Qwen/DashScope 或其他兼容模型，再到“模型与检索”里选择“我的模型”。
11. 在“模型与检索”里配置默认 RAG 开关和检索数量。
12. 保存草稿并发布。管理员会直接上架；普通用户会提交管理员审核。
13. 管理员在“审核”里通过后，智能体会显示在“市场”，其他用户可以复制使用。
14. 在预览区切换“草稿调试 / 已发布预览”。草稿调试使用当前配置，已发布预览使用最近一次已审核通过的发布快照。
15. 点击推荐问或手动发送测试消息；聊天框可上传或粘贴图片，可上传 TXT/MD/CSV/PDF/DOCX 附件，也可用 `RAG` 按钮覆盖本轮知识库检索。
16. 从主页面左侧会话列表重新打开历史会话，继续发送消息验证多轮 session，并可编辑会话标题。
17. 对 assistant 消息点有用/无用反馈，反馈会写入后端 `feedback` 表。



