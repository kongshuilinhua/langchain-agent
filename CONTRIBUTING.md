# Contributing

感谢关注 Lingshu Agent。当前项目主线是团队空间版自定义智能体平台。

## 本地开发

```bash
pip install -r requirements.txt
python scripts/release_check.py
```

前端：

```bash
cd frontend
npm install
npm run build
```

## 贡献优先级

- Auth、workspace、agent、knowledge、RAG、tools 的测试覆盖。
- PostgreSQL/Milvus/Redis 部署验证。
- 后端默认执行链路稳定性和可观测性。
- 知识库多格式解析。
- 前端工作台交互完善。

## 文档规则

- 不再把 Streamlit、Chroma 或 Qdrant 写成当前主线。
- 当前默认产品形态是 FastAPI + React + PostgreSQL + Milvus。
- 本地最小启动使用 PostgreSQL + memory vector + mock LLM。
- 不要在 UI 文档中暴露五步工作流节点作为产品配置入口。

## 提交前检查

```bash
python scripts/release_check.py --with-frontend
```

不要提交：

- `.env`
- `storage/`
- `logs/`
- `frontend/node_modules/`
- `frontend/dist/`

## License

提交贡献即表示你同意该贡献按本仓库 MIT License 发布。

