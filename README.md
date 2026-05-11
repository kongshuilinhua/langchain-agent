# 扫地机器人 Agent 项目

这是一个基于 Streamlit、LangChain、Chroma 和 DashScope 的中文智能客服项目，面向扫地机器人与扫拖一体机场景，支持知识库问答、故障排查、维护建议、天气辅助判断和用户使用报告生成。

项目当前已经从简单 Demo 演进到“可持续维护”的版本，重点补了多轮对话、真实工具接入、知识库增量同步、来源展示和前端运维能力。

## 主要能力

- 支持多轮对话，历史消息会一起传入 Agent，而不是只看当前一句。
- 基于本地知识库进行 RAG 检索与总结。
- 支持报告场景的动态提示词切换。
- 支持读取外部用户记录，生成个人使用报告。
- 支持查询真实天气，辅助给出使用建议。
- 支持展示知识库引用来源，并可展开查看命中的本地知识片段。
- 支持在页面中直接清空会话、重建知识库。
- 支持知识库文本清洗、FAQ 问答切分、结构化切块和增量同步。
- 检测到 Chroma 索引异常时可自动重建。
- 启动前会进行运行环境自检，缺少关键配置时直接阻止应用启动。

## 当前项目结构

- `app.py`
  Streamlit 前端入口，负责聊天界面、引用展示、会话管理和知识库运维按钮。

- `agent/react_agent.py`
  Agent 构建入口，封装模型、提示词、中间件和工具注册。

- `agent/tools/agent_tools.py`
  业务工具定义，包括：
  - 知识库检索总结
  - 实时天气查询
  - 用户 ID / 城市读取
  - 用户画像、可用月份、最近一期记录、指定月份报告读取

- `agent/tools/middleware.py`
  中间件逻辑，包括工具监控、模型调用前日志和报告场景的动态提示词切换。

- `rag/vector_store.py`
  知识库入库和向量库管理，负责：
  - 文档加载
  - 文本清洗
  - FAQ 问答拆分
  - 切块
  - 向量化
  - manifest 增量同步
  - 陈旧切片清理
  - 向量库重建

- `rag/rag_service.py`
  RAG 检索和总结服务，负责：
  - 查询改写
  - 扩召回
  - 轻量重排
  - 参考来源整理
  - 检索异常恢复

- `config/`
  项目配置目录：
  - `rag.yaml`：模型配置
  - `chroma.yaml`：向量库和切块配置
  - `prompt.yaml`：提示词路径配置
  - `agent.yaml`：外部用户数据配置

- `prompts/`
  提示词目录：
  - `main_prompt.txt`
  - `rag_summarize.txt`
  - `report_prompt.txt`

- `data/`
  本地知识库目录，支持递归扫描子目录。

- `data/external/records.csv`
  用户使用记录数据源，用于报告类场景。

- `storage/`
  向量库存储目录。

- `storage/knowledge_manifest.json`
  知识库 manifest 文件，记录每个来源文件的 md5、切片数和更新时间。

- `logs/`
  运行日志目录。

## 知识库机制

当前知识库不是简单“把 txt 扔进去就结束”，而是有一套基本可维护的入库流程。

### 入库流程

1. 递归扫描 `data/` 目录下的可用文件。
2. 根据文件类型读取内容。
3. 对文本做清洗，统一换行和空白。
4. 对 FAQ / `100问` 类文档优先按“问题-答案”结构切分。
5. 按 `txt/pdf` 使用不同的切块参数。
6. 为每个 chunk 生成稳定 ID：
   `source + chunk_index + content_hash`
7. 写入 Chroma 向量库。
8. 同步更新 `storage/knowledge_manifest.json`。

### 增量同步逻辑

- 文件未变化：跳过入库。
- 文件已更新：删除旧切片，重新切块并写入。
- 文件已删除：清理向量库中残留的旧切片。
- 首次运行或 manifest 缺失：自动按当前文件状态重建同步信息。

### 检索增强逻辑

当前 RAG 已做的增强包括：

- 查询规范化
- 常见口语问法扩展
- 扩召回
- 轻量重排
- 引用来源整理

适合的问题类型包括：

- 选购建议
- 故障排查
- 使用技巧
- 维护保养
- 场景适配

## 已接入工具

### 1. 知识库工具

- `rag_summarize(query)`
  从本地知识库检索资料并总结返回。

### 2. 天气工具

- `get_weather(city)`
  基于 Open-Meteo 查询实时天气，不需要额外 API Key。

### 3. 会话/用户信息工具

- `get_user_location()`
  读取当前会话绑定城市。

- `get_user_id()`
  读取当前会话绑定用户 ID。

默认不会随机编造城市或用户 ID。

### 4. 报告相关工具

- `get_current_month()`
  获取当前月份。

- `list_report_months(user_id)`
  获取某个用户有哪些可查询月份。

- `fetch_latest_external_data(user_id)`
  获取某个用户最近一期记录。

- `get_user_profile(user_id)`
  获取某个用户的基础画像和最近记录摘要。

- `fetch_external_data(user_id, month)`
  获取某个用户指定月份的使用记录。

- `fill_context_for_report()`
  为报告生成场景注入上下文标记。

## 前端交互能力

当前页面支持以下能力：

- 聊天输入
- 快捷问题按钮
- 历史消息展示
- 结构化引用来源展示
- 来源片段预览
- 清空会话
- 重建知识库

## 运行环境要求

### Python 与环境

- Python `3.10+`
- 推荐使用 Conda
- 当前约定环境名：`agent310`

### 编码要求

- 源码文件统一使用 `UTF-8`
- 提示词文件统一使用 `UTF-8`
- 知识库文本文件建议统一使用 `UTF-8`

### 必需环境变量

- `DASHSCOPE_API_KEY`
  DashScope 模型调用所需。

### 可选环境变量

- `AGENT_USER_CITY`
  为当前会话绑定城市，供 `get_user_location()` 使用。

- `AGENT_USER_ID`
  为当前会话绑定用户 ID，供报告场景使用。

## 依赖说明

项目依赖以 [requirements.txt](/D:/pycharmprojects/agent/requirements.txt) 为准，当前主要分为几类：

- LLM 与 Agent 相关依赖
- 向量库与检索相关依赖
- 文档解析依赖
- Web 应用与配置依赖
- DashScope 模型服务依赖

项目也使用了部分 Python 标准库，不需要写入 `requirements.txt`，例如：

- `json`
- `csv`
- `hashlib`
- `datetime`
- `urllib`
- `threading`
- `re`

## 安装方式

### 1. 激活环境

```powershell
conda activate agent310
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

### 3. 配置环境变量

```powershell
$env:DASHSCOPE_API_KEY="your_api_key_here"
```

可选：

```powershell
$env:AGENT_USER_CITY="上海"
$env:AGENT_USER_ID="1001"
```

## 启动方式

### 启动应用

```powershell
streamlit run app.py
```

### 可选：预构建知识库

```powershell
python -m rag.vector_store
```

## 启动前自检项

应用启动时会自动检查以下内容：

- `DASHSCOPE_API_KEY` 是否存在
- prompt 文件是否存在
- prompt 文件是否为 UTF-8
- 知识库目录是否存在
- 外部数据文件是否存在
- 关键配置项是否缺失

如果这些检查不通过，应用会直接停止启动。

## 知识来源展示

当回答命中知识库内容时，前端会：

1. 在回答下方显示 `参考来源`
2. 以标签形式展示命中的来源文件
3. 支持展开查看本地知识片段预览

目前支持的预览类型：

- `txt`
- `pdf`

## 常见操作

### 清空会话

在页面顶部点击 `清空会话` 按钮即可。

### 重建知识库

在页面顶部点击 `重建知识库` 按钮即可。

该操作会：

- 清空当前向量库
- 重新扫描 `data/`
- 重新切块并入库
- 重建 manifest

## 当前限制

- 天气工具依赖网络；网络不可用时会返回失败信息。
- `get_user_location` 和 `get_user_id` 目前仍主要依赖环境变量绑定，不是完整的用户体系。
- 当前知识库仍以本地静态文件为主，缺少在线知识管理后台。
- FAQ 切分目前基于规则，复杂格式文档仍可能拆分不理想。
- 来源预览目前只展示局部片段，不支持高亮命中词。

## 建议的后续工作

- 增加知识库管理面板，展示：
  - 当前文档总数
  - 当前 chunk 数
  - manifest 状态
  - 最后更新时间

- 补充自动化测试：
  - 工具层测试
  - RAG 检索测试
  - 入库同步测试
  - 报告流程测试

- 引入更强的知识来源：
  - 产品说明书
  - 故障码手册
  - 客服工单 FAQ
  - 机型差异表
  - 维修经验库

- 增强知识检索：
  - 更细粒度的 query rewrite
  - rerank 模型
  - 更强的 FAQ 结构化切分
  - 引用片段高亮

## 备注

如果后续继续扩展知识库，建议优先补这三类内容：

- 机型级知识
- 故障排查知识
- 真实客服案例知识

比单纯继续堆更多纯文本，更能提升实际回答质量。
