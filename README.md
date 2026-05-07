# 扫地机器人 Agent 项目

这是一个基于 Streamlit、LangChain、Chroma 和 DashScope 的中文智能客服项目，面向扫地机器人与扫拖一体机场景。项目当前重点覆盖知识库问答、故障排查、维护建议、天气辅助判断和用户使用报告生成。

## 项目结构

- `app.py`
  Streamlit 前端入口，负责聊天界面、会话管理、知识来源展示和知识库维护按钮。

- `agent/`
  Agent 相关代码。
  - `react_agent.py`：组装模型、工具、中间件和会话上下文。
  - `tools/agent_tools.py`：业务工具定义。
  - `tools/middleware.py`：工具监控、提示词切换和调用日志。

- `rag/`
  RAG 与向量库相关代码。
  - `rag_service.py`：检索、重排、总结和来源整理。
  - `vector_store.py`：知识库入库、切块、增量同步和向量库重建。

- `config/`
  项目配置文件。
  - `agent.yaml`
  - `chroma.yaml`
  - `prompt.yaml`
  - `rag.yaml`

- `prompts/`
  提示词文件。
  - `main_prompt.txt`
  - `rag_summarize.txt`
  - `report_prompt.txt`

- `model/`
  模型工厂与模型初始化逻辑。

- `utils/`
  通用工具模块，例如配置读取、日志、路径处理、文件解析和会话存储。

- `data/`
  本地知识库目录，支持递归扫描。

## 主要能力

- 支持多轮对话，会把历史消息一并传入 Agent。
- 支持基于本地知识库的 RAG 检索与总结。
- 支持根据场景动态切换提示词，例如报告生成场景。
- 支持读取外部用户记录，生成用户使用报告。
- 支持查询实时天气，辅助给出维护和使用建议。
- 支持展示知识来源，并在前端预览命中的知识片段。
- 支持清空会话和重建知识库。

## 环境要求

- Python `3.10+`
- 建议使用虚拟环境或 Conda 环境
- 所有源码、提示词和知识库文本建议统一使用 `UTF-8`

## 环境变量

必需环境变量：

- `DASHSCOPE_API_KEY`
  DashScope 模型调用所需密钥。

可选环境变量：

- `AGENT_USER_CITY`
  当前会话绑定城市，供天气或场景工具使用。

- `AGENT_USER_ID`
  当前会话绑定用户 ID，供报告场景使用。

可以参考 [`.env.example`](D:\pycharmprojects\langchain\.env.example) 自行创建 `.env` 文件，但 `.env` 不应提交到仓库。

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动方式

启动主应用：

```bash
streamlit run app.py
```

可选：手动预构建知识库：

```bash
python -m rag.vector_store
```

## 知识库机制

当前知识库不是简单地把文本写入向量库，而是带有一套可维护的入库流程：

- 递归扫描 `data/` 目录下的知识文件
- 按文件类型读取并清洗内容
- 对 FAQ 和结构化文本做切分
- 为每个文本块生成稳定 ID
- 写入 Chroma 向量库
- 通过 manifest 记录文件哈希、切块数量和更新时间

增量同步时会处理以下情况：

- 文件未变化：跳过
- 文件已更新：删除旧切片后重新入库
- 文件已删除：清理向量库残留切片
- 索引异常：按需要重建向量库

## 当前依赖说明

`requirements.txt` 主要包含以下几类依赖：

- LangChain 与 LangGraph
- Chroma 向量库
- 文本切分与 PDF 解析
- Streamlit Web 应用
- YAML 配置读取
- DashScope 模型接入

## 已忽略的本地文件

`.gitignore` 已排除以下内容：

- Python 缓存和编译产物
- 虚拟环境目录
- `.env`
- IDE 配置
- 日志文件
- 本地向量库和 SQLite 文件
- 本地聊天记录

## 后续建议

- 为工具层和 RAG 检索层补自动化测试
- 增加更细粒度的知识库管理页面
- 引入更强的重排能力和更稳定的引用高亮
- 继续补充真实售后案例、故障码和机型差异知识
