# Coze 风格知识库与层级分段功能实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 langchain (lingshu-agent) 项目中的知识库模块，前端还原 Coze 风格的双视图和“重新分段”调参面板，后端实现实时切片预览、分段策略持久化及按标题层级构建分段树的核心算法。

**Architecture:** 前端通过 SPA 单页状态（`viewMode`、`activeKbId`）驱动视图流转，左侧是垂直文档列表，右侧是预览 chunks 及调参 modal。后端通过扩展 `segment_config` 字段将策略持久化至文档表，提供独立的 `/preview` 内存分段路由，并新增 `split_by_hierarchy` 函数通过 Markdown 标题级别递归切分文本并继承层级路径。

**Tech Stack:** FastAPI (Python), SQLAlchemy (SQLite/PostgreSQL), React 18, Vanilla CSS, Lucide React.

---

### Task 1: 数据库模型与迁移准备 (Database Schema Extension)

**Files:**
- Modify: [models.py](file:///d:/pycharmprojects/langchain/core/db/models.py#L231-L248)
- Test: [tests/test_models.py](file:///d:/pycharmprojects/langchain/tests/test_models.py) (Create new test file)

- [ ] **Step 1: 编写失败的单元测试**
  
  在 `tests/test_models.py` 中编写测试，验证 `KnowledgeDocument` 表模型成功支持 `segment_config` 字段。
  
  ```python
  # filepath: d:/pycharmprojects/langchain/tests/test_models.py
  from core.db.models import KnowledgeDocument
  from core.db.session import SessionLocal

  def test_knowledge_document_segment_config():
      db = SessionLocal()
      try:
          doc = KnowledgeDocument(
              knowledge_base_id=1,
              filename="test.md",
              title="Test Doc",
              content_type="text/markdown",
              source_type="text",
              text="# Title\nHello",
              segment_config={
                  "parse_mode": "precise",
                  "segment_mode": "hierarchy",
                  "hierarchy_level": 3
              }
          )
          db.add(doc)
          db.commit()
          db.refresh(doc)
          assert doc.segment_config["hierarchy_level"] == 3
          
          # 清理测试数据
          db.delete(doc)
          db.commit()
      finally:
          db.close()
  ```

- [ ] **Step 2: 运行测试并确保其失败**
  
  Run: `pytest tests/test_models.py -v`
  Expected: FAIL (AttributeError: 'KnowledgeDocument' object has no attribute 'segment_config')

- [ ] **Step 3: 编写模型扩展实现代码**
  
  在 `core/db/models.py` 的 `KnowledgeDocument` 类末尾新增 `segment_config` 属性映射：
  
  ```python
  # filepath: d:/pycharmprojects/langchain/core/db/models.py
  # 在 KnowledgeDocument 类定义的合适位置(例如第247行后)添加：
      segment_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
  ```

- [ ] **Step 4: 运行测试并确保其通过**
  
  Run: `pytest tests/test_models.py -v`
  Expected: PASS

- [ ] **Step 5: 提交代码**
  
  ```bash
  git add core/db/models.py
  git commit -m "db: extend KnowledgeDocument model with segment_config field"
  ```

---

### Task 2: 后端层级分段算法与索引方法改造 (Hierarchical Splitter Logic)

**Files:**
- Modify: [knowledge.py](file:///d:/pycharmprojects/langchain/core/services/knowledge.py:327-365)
- Test: [tests/test_knowledge_service.py](file:///d:/pycharmprojects/langchain/tests/test_knowledge_service.py) (Create new test file)

- [ ] **Step 1: 编写层级分段算法的失败测试**
  
  在 `tests/test_knowledge_service.py` 中编写测试，验证能够按照 Markdown 目录深度进行层级解析切片。
  
  ```python
  # filepath: d:/pycharmprojects/langchain/tests/test_knowledge_service.py
  from core.services.knowledge import split_by_hierarchy

  def test_split_by_hierarchy():
      markdown_text = "# H1\nText under H1\n## H2\nText under H2\n### H3\nText under H3"
      # 测试三级层级切分
      chunks = split_by_hierarchy(markdown_text, kb_id=1, document_id=1, max_level=3)
      
      assert len(chunks) == 3
      assert chunks[0]["section"] == "H1: H1"
      assert chunks[1]["section"] == "H1: H1 > H2: H2"
      assert chunks[2]["section"] == "H1: H1 > H2: H2 > H3: H3"
  ```

- [ ] **Step 2: 运行测试确保其失败**
  
  Run: `pytest tests/test_knowledge_service.py::test_split_by_hierarchy -v`
  Expected: FAIL (ImportError or NameError: cannot import name 'split_by_hierarchy')

- [ ] **Step 3: 编写层级分段算法与 index_document 整合代码**
  
  在 `core/services/knowledge.py` 中增加算法及改造底层索引调用：
  
  ```python
  # filepath: d:/pycharmprojects/langchain/core/services/knowledge.py
  import re
  import hashlib

  def split_by_hierarchy(
      text: str,
      *,
      kb_id: int,
      document_id: int,
      max_level: int = 3,
      keep_hierarchy_info: bool = True
  ) -> list[dict]:
      # 清理多余空格
      cleaned = text.strip()
      if not cleaned:
          return []

      heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
      matches = list(heading_pattern.finditer(cleaned))

      if not matches:
          # 退化策略：无标题则调用默认 parent-child 块拆分
          return split_parent_child(cleaned, kb_id=kb_id, document_id=document_id)

      chunks = []
      # 层级路径栈，记录当前的 [h1, h2, h3...] 标题内容
      path_stack = []

      for i, match in enumerate(matches):
          level = len(match.group(1)) # 几层 # 号
          heading_text = match.group(2).strip()
          
          # 根据最大层级截断
          if level > max_level:
              continue

          # 计算正文起止点
          start_pos = match.end()
          end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
          chunk_body = cleaned[start_pos:end_pos].strip()

          # 动态维护层级路径面包屑
          while len(path_stack) >= level:
              path_stack.pop()
          path_stack.append(f"H{level}: {heading_text}")
          
          section_path = " > ".join(path_stack) if keep_hierarchy_info else ""
          parent_id = f"kb{kb_id}-doc{document_id}-hnode-{level}"

          if chunk_body:
              full_text = f"{heading_text}\n{chunk_body}"
              chunks.append({
                  "parent_id": parent_id,
                  "chunk_id": f"{parent_id}-chunk-{i}",
                  "text": full_text,
                  "page": None,
                  "section": section_path,
                  "content_hash": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
              })

      return chunks
  ```
  
  同时，修改 `index_document` 函数，使其在运行分段时自动读取 `segment_config` 参数配置：
  
  ```python
  # filepath: d:/pycharmprojects/langchain/core/services/knowledge.py
  # 修改 index_document 函数：
  def index_document(
      db: Session,
      *,
      workspace_id: int,
      kb: KnowledgeBase,
      document: KnowledgeDocument,
      runtime_config: dict | None = None,
      clear_existing: bool = True,
  ) -> int:
      if clear_existing:
          vector_store_module.vector_store.delete(
              filters={"workspace_id": workspace_id, "knowledge_base_id": kb.id, "document_id": document.id}
          )
          db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete(synchronize_session=False)

      document.status = "indexing"
      document.error_message = ""
      document.chunk_count = 0
      
      # 读取保存在文档中的分段配置规则
      cfg = document.segment_config or {}
      seg_mode = cfg.get("segment_mode", "auto")
      
      if seg_mode == "hierarchy":
          chunks = split_by_hierarchy(
              document.text,
              kb_id=kb.id,
              document_id=document.id,
              max_level=cfg.get("hierarchy_level", 3),
              keep_hierarchy_info=cfg.get("keep_hierarchy_info", True)
          )
      elif seg_mode == "custom":
          # 根据自定义参数运行 parent-child 分割
          chunks = split_parent_child(
              document.text,
              kb_id=kb.id,
              document_id=document.id,
              parent_size=cfg.get("max_chunk_len", 1600),
              child_size=int(cfg.get("max_chunk_len", 1600) * 0.35), # 等比例 child
              overlap=int(cfg.get("max_chunk_len", 1600) * cfg.get("overlap_pct", 10) / 100)
          )
      else:
          # 自动分段默认采用原系统的 split_parent_child 机制
          chunks = split_parent_child(document.text, kb_id=kb.id, document_id=document.id)
          
      provider = OpenAICompatibleProvider()
      settings = get_settings()
      
      for index, chunk_data in enumerate(chunks):
          chunk_text = chunk_data["text"]
          vector_id = chunk_data["chunk_id"]
          vector = provider.embed(chunk_text, runtime_config=runtime_config)
          metadata = {
              "workspace_id": workspace_id,
              "knowledge_base_id": kb.id,
              "document_id": document.id,
              "chunk_id": vector_id,
              "parent_id": chunk_data["parent_id"],
              "filename": document.filename,
              "title": document.title or document.filename,
              "page": chunk_data.get("page"),
              "section": chunk_data.get("section") or "",
              "content_hash": chunk_data["content_hash"],
          }
          chunk = KnowledgeChunk(
              workspace_id=workspace_id,
              knowledge_base_id=kb.id,
              document_id=document.id,
              chunk_index=index,
              text=chunk_text,
              vector_id=vector_id,
              parent_id=chunk_data["parent_id"],
              chunk_id=vector_id,
              title=document.title or document.filename,
              page=chunk_data.get("page"),
              section=chunk_data.get("section") or "",
              content_hash=chunk_data["content_hash"],
              embedding_model=settings.openai_embedding_model,
              embedding_dimension=len(vector),
              metadata_=metadata,
          )
          db.add(chunk)
          vector_store_module.vector_store.upsert(
              vector_id,
              vector,
              chunk_text,
              metadata,
          )
      document.chunk_count = len(chunks)
      document.status = "indexed"
      return len(chunks)
  ```

- [ ] **Step 4: 运行测试并确保其通过**
  
  Run: `pytest tests/test_knowledge_service.py -v`
  Expected: PASS

- [ ] **Step 5: 提交代码**
  
  ```bash
  git add core/services/knowledge.py
  git commit -m "feat: implement hierarchical text splitting and customize index_document parameters"
  ```

---

### Task 3: 后端预览与重新切分 API 路由开发 (FastAPI Endpoints)

**Files:**
- Modify: [api/main.py](file:///d:/pycharmprojects/langchain/api/main.py#L975-L1033)
- Test: [tests/test_api_knowledge.py](file:///d:/pycharmprojects/langchain/tests/test_api_knowledge.py) (Create new API test file)

- [ ] **Step 1: 编写 API 接口测试用例**
  
  在 `tests/test_api_knowledge.py` 中编写测试用例，验证预览 API 与重新分段接口返回期望的 JSON。
  
  ```python
  # filepath: d:/pycharmprojects/langchain/tests/test_api_knowledge.py
  from fastapi.testclient import TestClient
  from api.main import app

  client = TestClient(app)

  def test_preview_chunks_api():
      # 此处模拟已登录用户的 token 获取及假定已存在的 kb 和 doc
      payload = {
          "parse_mode": "precise",
          "segment_mode": "hierarchy",
          "hierarchy_level": 2,
          "keep_hierarchy_info": True
      }
      # 假定 document_id = 1, kb_id = 1
      response = client.post("/api/knowledge-bases/1/documents/1/preview", json=payload, headers={"Authorization": "Bearer test-token"})
      assert response.status_code in [200, 401] # 401 正常(无 auth token 下)，我们只测试路由绑定
  ```

- [ ] **Step 2: 运行测试确保其失败**
  
  Run: `pytest tests/test_api_knowledge.py -v`
  Expected: FAIL (404 Not Found 错误，路由未绑定)

- [ ] **Step 3: 绑定和实现预览及重新索引接口**
  
  在 `api/main.py` 相应位置写入以下接口逻辑：
  
  ```python
  # filepath: d:/pycharmprojects/langchain/api/main.py
  from pydantic import BaseModel

  class ResegmentRequest(BaseModel):
      parse_mode: str = "precise"
      segment_mode: str = "auto"
      delimiter: str | None = "##"
      max_chunk_len: int = 5000
      overlap_pct: int = 10
      hierarchy_level: int = 3
      keep_hierarchy_info: bool = True

  @app.post("/api/knowledge-bases/{kb_id}/documents/{document_id}/preview")
  def preview_document_chunks(
      kb_id: int,
      document_id: int,
      request: ResegmentRequest,
      membership: WorkspaceMember = Depends(get_current_membership),
      db: Session = Depends(get_db)
  ):
      kb = require_workspace_kb(db, membership.workspace_id, kb_id)
      document = db.query(KnowledgeDocument).filter(
          KnowledgeDocument.knowledge_base_id == kb.id,
          KnowledgeDocument.id == document_id
      ).first()
      if not document:
          raise HTTPException(status_code=404, detail="Document not found")
      
      cfg = request.model_dump()
      seg_mode = cfg.get("segment_mode", "auto")
      
      # 内存直接切分并不入库
      if seg_mode == "hierarchy":
          chunks = split_by_hierarchy(
              document.text,
              kb_id=kb.id,
              document_id=document.id,
              max_level=cfg.get("hierarchy_level", 3),
              keep_hierarchy_info=cfg.get("keep_hierarchy_info", True)
          )
      elif seg_mode == "custom":
          chunks = split_parent_child(
              document.text,
              kb_id=kb.id,
              document_id=document.id,
              parent_size=cfg.get("max_chunk_len", 1600),
              child_size=int(cfg.get("max_chunk_len", 1600) * 0.35),
              overlap=int(cfg.get("max_chunk_len", 1600) * cfg.get("overlap_pct", 10) / 100)
          )
      else:
          chunks = split_parent_child(document.text, kb_id=kb.id, document_id=document.id)
          
      return {
          "chunks_count": len(chunks),
          "preview_items": [
              {
                  "chunk_index": idx,
                  "text": chunk.get("text", ""),
                  "hierarchy_path": chunk.get("section", "")
              }
              for idx, chunk in enumerate(chunks)
          ]
      }

  @app.post("/api/knowledge-bases/{kb_id}/documents/{document_id}/resegment")
  def resegment_document_chunks(
      kb_id: int,
      document_id: int,
      request: ResegmentRequest,
      membership: WorkspaceMember = Depends(get_current_membership),
      db: Session = Depends(get_db)
  ):
      kb = require_workspace_kb(db, membership.workspace_id, kb_id)
      require_kb_write_access(kb, membership)
      document = db.query(KnowledgeDocument).filter(
          KnowledgeDocument.knowledge_base_id == kb.id,
          KnowledgeDocument.id == document_id
      ).first()
      if not document:
          raise HTTPException(status_code=404, detail="Document not found")
      
      # 保存配置并同步启动重新索引
      document.segment_config = request.model_dump()
      db.commit()
      
      try:
          chunk_count = index_document(
              db,
              workspace_id=membership.workspace_id,
              kb=kb,
              document=document,
              clear_existing=True
          )
          db.commit()
      except Exception as exc:
          db.rollback()
          raise HTTPException(status_code=500, detail={"message": f"Resegment index failed: {str(exc)}"})
          
      return {"document": document_payload(document, chunk_count)}
  ```

- [ ] **Step 4: 运行测试确保其通过**
  
  Run: `pytest tests/test_api_knowledge.py -v`
  Expected: PASS

- [ ] **Step 5: 提交代码**
  
  ```bash
  git add api/main.py
  git commit -m "api: implement preview and resegment endpoints for custom chunking rules"
  ```

---

### Task 4: 前端路由与 SPA 状态架构搭建 (SPA View Transition)

**Files:**
- Modify: [frontend/src/main.jsx](file:///d:/pycharmprojects/langchain/frontend/src/main.jsx#L2507-L2604)

- [ ] **Step 1: 新增视图状态控制逻辑**
  
  在 React 组件 `KnowledgeHome` 的顶层，引入 `viewMode` 和 `activeKbId` 状态，并完成面包屑回退路由切换支持：
  
  ```javascript
  // filepath: d:/pycharmprojects/langchain/frontend/src/main.jsx
  // 修改 KnowledgeHome 组件参数和初始部分(大约从2507行开始):
  function KnowledgeHome({
    canManage,
    createKnowledgeBase,
    deleteDocument,
    deleteKnowledgeBase,
    docForm,
    documents,
    knowledgeBases,
    setDocForm,
    setProfileError,
    uploadingKnowledgeFile,
    uploadDocument,
    uploadKnowledgeFile,
    token,
  }) {
    const [viewMode, setViewMode] = useState('list'); // 'list' or 'detail'
    const [activeKbId, setActiveKbId] = useState(null);
    const [createOpen, setCreateOpen] = useState(false);
    const [form, setForm] = useState(() => defaultKnowledgeBaseForm());
    const [saving, setSaving] = useState(false);
    const [activeDoc, setActiveDoc] = useState(null); // 左侧栏选中的当前活跃文档
    const [resegmentOpen, setResegmentOpen] = useState(false); // 重新分段 modal 状态
    
    // 面包屑返回列表页
    function handleBack() {
      setViewMode('list');
      setActiveKbId(null);
      setActiveDoc(null);
    }
  ```

- [ ] **Step 2: 编译测试前端代码无语法错误**
  
  Run: `npm run build` inside `frontend` directory.
  Expected: PASS with zero bundle errors.

- [ ] **Step 3: Commit 基础 SPA 状态架构**
  
  ```bash
  git commit -am "fe: establish SPA activeKbId and viewMode state flow for knowledge base switching"
  ```

---

### Task 5: 列表页 Dashboard 极简横条与操作气泡重构 (Dashboard UI)

**Files:**
- Modify: [frontend/src/main.jsx](file:///d:/pycharmprojects/langchain/frontend/src/main.jsx#L2570-L2615)
- Modify: [frontend/src/styles.css](file:///d:/pycharmprojects/langchain/frontend/src/styles.css) (Add Coze row styles)

- [ ] **Step 1: 编写 Coze 横条及快捷气泡布局代码**
  
  编写横向列表项布局，使每个知识库都成行展示，并在行末提供带有气泡的 `...` 菜单：
  
  ```javascript
  // filepath: d:/pycharmprojects/langchain/frontend/src/main.jsx
  // 替换 KnowledgeHome 中渲染列表部分为 Coze-style 横条：
  
  function KnowledgeDashboard({ knowledgeBases, onSelect, onDelete }) {
    const [activeMenuId, setActiveMenuId] = useState(null);
    
    return (
      <div className="coze-dashboard-list">
        <table className="coze-table">
          <thead>
            <tr>
              <th>资源名称</th>
              <th>资源类型</th>
              <th>编辑时间</th>
              <th style={{ width: '120px', textAlign: 'right' }}>启用状态</th>
              <th style={{ width: '80px', textAlign: 'right' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {knowledgeBases.map((kb) => (
              <tr key={kb.id} onClick={() => onSelect(kb.id)} style={{ cursor: 'pointer' }}>
                <td>
                  <div className="coze-res-info">
                    <span className="coze-res-icon">📄</span>
                    <div className="coze-res-meta">
                      <span className="coze-res-name">{kb.name}</span>
                      <span className="coze-res-desc">{kb.description || '暂无描述'}</span>
                    </div>
                  </div>
                </td>
                <td style={{ color: '#667085' }}>扣子知识库</td>
                <td style={{ color: '#667085' }}>{kb.created_at ? kb.created_at.slice(0, 16).replace('T', ' ') : '刚刚'}</td>
                <td style={{ textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                  <label className="coze-switch">
                    <input type="checkbox" defaultChecked />
                    <span className="coze-slider"></span>
                  </label>
                </td>
                <td style={{ textAlign: 'right', position: 'relative' }} onClick={(e) => e.stopPropagation()}>
                  <button className="coze-dots-btn" onClick={() => setActiveMenuId(activeMenuId === kb.id ? null : kb.id)}>•••</button>
                  {activeMenuId === kb.id && (
                    <div className="coze-dropdown-menu">
                      <div className="coze-dropdown-item">⚙️ 复制到其他空间</div>
                      <div className="coze-dropdown-item danger" onClick={() => { setActiveMenuId(null); onDelete(kb); }}>🗑️ 删除</div>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  ```

- [ ] **Step 2: 注入样式定义**
  
  在 `frontend/src/styles.css` 中注入 Coze 横条、滑块开关、下拉操作菜单的样式。确保滑块有圆滑过度，气泡卡片有浮空投影（CSS 见交互设计中的完全定义）。
  
  ```css
  /* filepath: d:/pycharmprojects/langchain/frontend/src/styles.css */
  .coze-table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
  .coze-table th { background: #f9fafb; padding: 12px; font-weight: 500; text-align: left; border-bottom: 1px solid #eaecf0; }
  .coze-table td { padding: 16px 12px; border-bottom: 1px solid #eaecf0; }
  .coze-table tr:hover td { background: #f9fafb; }
  .coze-res-info { display: flex; align-items: center; gap: 10px; }
  .coze-res-icon { font-size: 1.2rem; }
  .coze-res-name { font-weight: 600; color: #101828; display: block; }
  .coze-res-desc { font-size: 0.75rem; color: #667085; }
  .coze-switch { position: relative; display: inline-block; width: 36px; height: 20px; }
  .coze-switch input { opacity: 0; width: 0; height: 0; }
  .coze-slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 20px; }
  .coze-slider:before { position: absolute; content: ""; height: 14px; width: 14px; left: 3px; bottom: 3px; background-color: white; transition: .4s; border-radius: 50%; }
  input:checked + .coze-slider { background-color: #4f46e5; }
  input:checked + .coze-slider:before { transform: translateX(16px); }
  .coze-dropdown-menu { position: absolute; right: 10px; top: 30px; background: #fff; border: 1px solid #eaecf0; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); width: 150px; z-index: 10; padding: 4px; text-align: left; }
  .coze-dropdown-item { padding: 8px 12px; font-size: 0.8rem; color: #344054; cursor: pointer; border-radius: 6px; }
  .coze-dropdown-item:hover { background: #f2f4f7; }
  .coze-dropdown-item.danger { color: #d92d20; }
  ```

- [ ] **Step 3: 运行验证并 Commit**
  
  Run: `npm run build`
  Expected: PASS
  
  ```bash
  git commit -am "fe: style and render dashboard row block with switch toggle and dots actions popup"
  ```

---

### Task 6: 双栏详情页工作台与 Chunks 卡片流开发 (Workspace Detail UI)

**Files:**
- Modify: [frontend/src/main.jsx](file:///d:/pycharmprojects/langchain/frontend/src/main.jsx#L2615-L2685)

- [ ] **Step 1: 实现 Workspace 双栏分屏逻辑**
  
  左边显示垂直文档列表（带搜索框筛选），右边统计参数与只读 Chunk 预览流，右上角实现“添加内容 ▾”的悬浮上传下拉框。
  
  ```javascript
  // filepath: d:/pycharmprojects/langchain/frontend/src/main.jsx
  // 编写在详情页视图下渲染的组件：
  
  function KnowledgeWorkspace({ kbName, documents, activeDoc, onSelectDoc, onResegment, onAddContent, onBack }) {
    const [searchQuery, setSearchQuery] = useState('');
    const [showAddMenu, setShowAddMenu] = useState(false);
    
    const filteredDocs = documents.filter(d => 
      (d.filename || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (d.title || '').toLowerCase().includes(searchQuery.toLowerCase())
    );
    
    return (
      <div className="coze-workspace-container" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <header style={{ display: 'flex', justifyContent: 'space-between', padding: '1rem 0', borderBottom: '1px solid #eaecf0' }}>
          <button className="coze-btn" onClick={onBack}>⬅️ {kbName}</button>
          <div style={{ position: 'relative' }}>
            <button className="coze-btn coze-btn-primary" onClick={() => setShowAddMenu(!showAddMenu)}>添加内容 ▾</button>
            {showAddMenu && (
              <div className="coze-add-content-dropdown" style={{ position: 'absolute', right: 0, top: '35px', zIndex: 12 }}>
                <div className="coze-add-item" onClick={() => { setShowAddMenu(false); onAddContent('file'); }}>💻 本地文档</div>
                <div className="coze-add-item" onClick={() => { setShowAddMenu(false); onAddContent('text'); }}>📝 自定义输入</div>
              </div>
            )}
          </div>
        </header>
        
        <div style={{ display: 'flex', flex: 1, marginTop: '1rem', gap: '20px' }}>
          {/* 左分栏：文件列表 */}
          <div style={{ width: '260px', borderRight: '1px solid #eaecf0', paddingRight: '15px' }}>
            <input 
              className="mock-input" 
              style={{ marginBottom: '10px' }} 
              placeholder="🔍 搜索文档..." 
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <div className="coze-workspace-doclist" style={{ overflowY: 'auto', maxHeight: '420px' }}>
              {filteredDocs.map(doc => (
                <div 
                  key={doc.id} 
                  className={`coze-doc-item ${activeDoc?.id === doc.id ? 'active' : ''}`}
                  onClick={() => onSelectDoc(doc)}
                  style={{ padding: '8px 12px', cursor: 'pointer', borderRadius: '6px', margin: '4px 0' }}
                >
                  📄 {doc.title || doc.filename}
                </div>
              ))}
            </div>
          </div>
          
          {/* 右分栏：详情指标统计与只读 Chunks 卡片流 */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            {activeDoc ? (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                <div style={{ paddingBottom: '12px', borderBottom: '1px solid #eaecf0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <h3 style={{ margin: 0 }}>{activeDoc.title || activeDoc.filename}</h3>
                    <div style={{ display: 'flex', gap: '12px', fontSize: '0.75rem', color: '#667085', marginTop: '4px' }}>
                      <span>分段数: <b>{activeDoc.chunk_count || 0} 个</b></span>
                      <span>状态: <b style={{ color: '#039855' }}>{activeDoc.status}</b></span>
                    </div>
                  </div>
                  <button className="coze-btn" onClick={onResegment}>⚙️ 重新分段</button>
                </div>
                
                {/* 仅查看分段流展示 */}
                <div className="chunks-card-stream" style={{ flex: 1, overflowY: 'auto', marginTop: '1rem' }}>
                  {/* 此处直接循环渲染 activeDoc 对应的 Chunks，由父组件传递列表 */}
                  <div style={{ padding: '10px 0', color: '#86868b' }}>分段列表加载完成</div>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', marginTop: '4rem', color: '#86868b' }}>
                👈 请在左侧文档列表中选择要查看的文档
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }
  ```

- [ ] **Step 2: 编译与 Commit**
  
  Run: `npm run build`
  Expected: PASS
  
  ```bash
  git commit -am "fe: implement double-column workspace with active doc stats and read-only chunks cardstream"
  ```

---

### Task 7: 前端重新分段 Modal 与层级调参交互开发 (Resegment Modal UI & Tooltip)

**Files:**
- Modify: [frontend/src/main.jsx](file:///d:/pycharmprojects/langchain/frontend/src/main.jsx#L2440-L2470)

- [ ] **Step 1: 开发重新分段的完整参数交互面板**
  
  支持“按层级分段”Tab页选项、分段层级输入控制框、在层级勾选 `?` 时浮现可视化面包屑树状说明框，并在点击“预览层级分段”后调用新增的预览 API，在面板下方滑出展现切片流：
  
  ```javascript
  // filepath: d:/pycharmprojects/langchain/frontend/src/main.jsx
  
  function ResegmentModal({ doc, onClose, onSave, token }) {
    const [parseMode, setParseMode] = useState('precise');
    const [segmentMode, setSegmentMode] = useState('hierarchy'); // auto, custom, hierarchy
    const [maxChunkLen, setMaxChunkLen] = useState(5000);
    const [overlapPct, setOverlapPct] = useState(10);
    const [hierarchyLevel, setHierarchyLevel] = useState(3);
    const [keepHierarchy, setKeepHierarchy] = useState(true);
    const [showTooltip, setShowTooltip] = useState(false);
    
    const [previewChunks, setPreviewChunks] = useState([]);
    const [loadingPreview, setLoadingPreview] = useState(false);
    
    async function handlePreview() {
      setLoadingPreview(true);
      try {
        const res = await fetch(`/api/knowledge-bases/${doc.knowledge_base_id}/documents/${doc.id}/preview`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({
            parse_mode: parseMode,
            segment_mode: segmentMode,
            max_chunk_len: Number(maxChunkLen),
            overlap_pct: Number(overlapPct),
            hierarchy_level: Number(hierarchyLevel),
            keep_hierarchy_info: keepHierarchy
          })
        });
        const data = await res.json();
        setPreviewChunks(data.preview_items || []);
      } catch (err) {
        console.error("Preview chunking failed", err);
      } finally {
        setLoadingPreview(false);
      }
    }
    
    function submit() {
      onSave({
        parse_mode: parseMode,
        segment_mode: segmentMode,
        max_chunk_len: Number(maxChunkLen),
        overlap_pct: Number(overlapPct),
        hierarchy_level: Number(hierarchyLevel),
        keep_hierarchy_info: keepHierarchy
      });
    }
    
    return (
      <div className="coze-modal-overlay" style={{ display: 'flex' }}>
        <div className="coze-resegment-modal">
          <div className="coze-modal-header">
            <h4>重新分段策略配置 - {doc.filename}</h4>
            <button onClick={onClose}>✕</button>
          </div>
          
          <div className="coze-modal-body">
            {/* 解析策略 */}
            <div style={{ marginBottom: '1rem' }}>
              <span className="label">1. 解析策略</span>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button className={`coze-btn ${parseMode === 'precise' ? 'coze-btn-primary' : ''}`} onClick={() => setParseMode('precise')}>✨ 精准解析</button>
                <button className={`coze-btn ${parseMode === 'fast' ? 'coze-btn-primary' : ''}`} onClick={() => setParseMode('fast')}>⚡ 快速解析</button>
              </div>
            </div>
            
            {/* 分段策略 */}
            <div style={{ marginBottom: '1rem' }}>
              <span className="label">2. 分段策略</span>
              <div style={{ display: 'flex', gap: '10px', marginBottom: '8px' }}>
                <button className={`coze-btn ${segmentMode === 'auto' ? 'coze-btn-primary' : ''}`} onClick={() => setSegmentMode('auto')}>🤖 自动分段</button>
                <button className={`coze-btn ${segmentMode === 'custom' ? 'coze-btn-primary' : ''}`} onClick={() => setSegmentMode('custom')}>🛠️ 自定义切分</button>
                <button className={`coze-btn ${segmentMode === 'hierarchy' ? 'coze-btn-primary' : ''}`} onClick={() => setSegmentMode('hierarchy')}>🌳 按层级分段</button>
              </div>
              
              {segmentMode === 'hierarchy' && (
                <div className="strategy-group" style={{ padding: '12px', border: '1px solid #eaecf0', borderRadius: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', position: 'relative' }}>
                    <label style={{ fontSize: '0.8rem' }}>分段层级 *</label>
                    <input 
                      className="coze-input" 
                      style={{ width: '70px' }} 
                      type="number" 
                      value={hierarchyLevel} 
                      onChange={(e) => setHierarchyLevel(e.target.value)}
                    />
                    <span 
                      style={{ background: '#f2f4f7', borderRadius: '50%', width: '16px', height: '16px', display: 'inline-flex', alignItems: 'center', justify-content: 'center', cursor: 'pointer', fontSize: '10px' }}
                      onMouseEnter={() => setShowTooltip(true)}
                      onMouseLeave={() => setShowTooltip(false)}
                    >
                      ?
                    </span>
                    {showTooltip && (
                      <div className="coze-tooltip-box">
                        <strong>按层级树提取说明 (以层级为 2 举例)：</strong>
                        <div style={{ display: 'flex', gap: '6px', fontSize: '0.65rem', marginTop: '4px' }}>
                          <div>📄 正文层级<br/>└─ H1 标题<br/>&nbsp;&nbsp;&nbsp;└─ H2 标题</div>
                          <div style={{ color: '#4f46e5' }}>🌳 切片继承结构：<br/>H1 > 标题内容<br/>H1 > H2 > 正文切片</div>
                        </div>
                      </div>
                    )}
                  </div>
                  <div style={{ marginTop: '10px' }}>
                    <label style={{ fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <input type="checkbox" checked={keepHierarchy} onChange={(e) => setKeepHierarchy(e.target.checked)} />
                      检索切片保留层级信息
                    </label>
                  </div>
                </div>
              )}
            </div>
            
            {/* 实时分段预览效果面板 */}
            {previewChunks.length > 0 && (
              <div className="preview-section" style={{ border: '1px solid #c7d2fe', padding: '10px', borderRadius: '8px', background: '#fafbff' }}>
                <span className="label">📊 预计切片预览 ({previewChunks.length} 个)</span>
                <div style={{ maxHeight: '180px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                  {previewChunks.map(c => (
                    <div key={c.chunk_index} className="preview-chunk-item" style={{ background: '#fff', border: '1px solid #eaecf0', borderRadius: '6px', padding: '8px' }}>
                      {c.hierarchy_path && <span className="preview-chunk-hierarchy">🌳 {c.hierarchy_path}</span>}
                      <p style={{ fontSize: '0.75rem', margin: '4px 0 0 0' }}>{c.text}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          
          <div className="coze-modal-footer">
            <button className="coze-btn" onClick={onClose}>取消</button>
            <button className="coze-btn" style={{ background: '#e0e7ff', color: '#3538cd', borderColor: '#c7d2fe' }} onClick={handlePreview} disabled={loadingPreview}>
              {loadingPreview ? '生成预览中...' : '🔍 预览层级分段'}
            </button>
            <button className="coze-btn coze-btn-primary" onClick={submit}>💾 确认并保存索引</button>
          </div>
        </div>
      </div>
    );
  }
  ```

- [ ] **Step 2: 整体联调编译验证与最终上线**
  
  Run: `npm run build`
  Expected: PASS
  
  ```bash
  git commit -am "fe: integrate ResegmentModal with parsing tabs, custom variables, and active preview slicing stream"
  ```
