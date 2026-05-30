# 项目约束与部署细节

## 端口约束

- 本地端口不可变：
  - Backend: `http://127.0.0.1:8000`
  - Frontend: `http://127.0.0.1:5174`

如果端口被占用，停止旧进程后仍使用同一端口，不切换到其他端口。

```powershell
Get-NetTCPConnection -LocalPort 8000,5174 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

## 关键环境变量

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

> 真实聊天模型优先在前端“我的模型”中由用户自己配置；环境变量是后端 embedding、rerank 和开发兜底配置。
