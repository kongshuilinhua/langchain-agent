# Coze 风格配置面板改版 (Coze Style Orchestration Panel Redesign) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构智能体编辑页面的编排面板为 Coze 风格的可折叠分区，并将工具和知识库的全量展示升级为精致的“添加”弹窗和已绑定项的高级卡片展示。

**Architecture:** 
1. 在 `BuilderView.jsx` 中使用 React 状态驱动面板折叠和弹窗的显示/隐藏；
2. 工具和知识库在主面板仅渲染“已绑定”状态，并提供极简、高端的带删除图标的卡片；
3. 点击 `+ 添加` 会调起覆盖全局的遮罩弹窗（自带模糊搜索及滚动列表）；
4. 配套编写 CSS 样式，自适应适配深色/浅色模式，提升整体视觉质感。

**Tech Stack:** React 18.3.1, Lucide React, CSS Transitions.

---

### Task 1: 编写 CSS 样式表 (Aesthetic Styling in styles.css)

**Files:**
- Modify: `d:\pycharmprojects\langchain\frontend\src\styles.css` (在文件末尾追加改版所需的全部样式)

- [ ] **Step 1: 追加样式表以支持手风琴式折叠、精致绑定卡片与全局遮罩弹窗**

追加至 `frontend/src/styles.css` 末尾：
```css
/* ==========================================
 * Coze Style Orchestration Panel Redesign
 * ========================================== */

/* Accordion Categories Group */
.coze-group-title {
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  padding: 16px 20px 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: transparent;
  border-top: 1px solid rgba(229, 231, 239, 0.5);
  margin-top: 8px;
}
.coze-group-title:first-of-type {
  border-top: none;
  margin-top: 0;
}

/* Accordion Item Wrapper */
.coze-accordion-item {
  border-bottom: 1px solid rgba(229, 231, 239, 0.7);
  background: #ffffff;
  transition: all 0.2s ease;
}
body.dark .coze-accordion-item {
  background: #1d1d1f;
  border-bottom-color: #424245;
}

/* Accordion Header */
.coze-accordion-header {
  padding: 12px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease;
}
.coze-accordion-header:hover {
  background: rgba(244, 246, 251, 0.6);
}

.coze-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 13.5px;
  color: #1f2937;
}

.coze-caret-icon {
  color: #667085;
  transition: transform 0.2s ease;
}
.coze-accordion-item.expanded .coze-caret-icon {
  transform: rotate(90deg);
}

.coze-header-count {
  color: #4d43e6;
  font-weight: normal;
  font-size: 11px;
  margin-left: 2px;
  background: rgba(77, 67, 230, 0.1);
  padding: 2px 6px;
  border-radius: 10px;
}

/* Redesigned Text Add Button */
.coze-add-button {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #4d43e6;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba(77, 67, 230, 0.06);
  border: 1px solid rgba(77, 67, 230, 0.15);
  cursor: pointer;
  transition: all 0.2s ease;
}
.coze-add-button:hover {
  background: #4d43e6;
  color: #ffffff;
  border-color: #4d43e6;
}

/* Accordion Body */
.coze-accordion-body {
  display: none;
  padding: 12px 20px 16px;
  background: #ffffff;
  border-top: 1px solid rgba(229, 231, 239, 0.5);
}
.coze-accordion-item.expanded .coze-accordion-body {
  display: block;
}

/* Premium cards for bound items */
.coze-bound-card {
  border: 1px solid #dfe4ef;
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all 0.2s ease;
  margin-bottom: 8px;
}
.coze-bound-card:last-child {
  margin-bottom: 0;
}
.coze-bound-card:hover {
  border-color: #4d43e6;
  background: #fcfcfe;
  box-shadow: 0 4px 12px rgba(77, 67, 230, 0.04);
}

.coze-bound-card-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.coze-bound-card-icon {
  font-size: 16px;
  width: 28px;
  height: 28px;
  background: rgba(77, 67, 230, 0.08);
  color: #4d43e6;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.coze-bound-card-icon.kb {
  background: rgba(16, 185, 129, 0.08);
  color: #10b981;
}

.coze-bound-card-title {
  font-weight: 600;
  font-size: 13px;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.coze-bound-card-meta {
  font-size: 11px;
  color: #667085;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.coze-bound-card-remove {
  color: #94a3b8;
  font-size: 14px;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
}
.coze-bound-card-remove:hover {
  color: #ef4444;
  background: #fee2e2;
}

/* Modern Modals styling (Portal Overlay) */
.coze-modal-backdrop {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.coze-modal-container {
  background: #ffffff;
  border-radius: 16px;
  width: 90%;
  max-width: 580px;
  max-height: 80vh;
  box-shadow: 0 24px 38px 3px rgba(0, 0, 0, 0.08), 0 9px 46px 8px rgba(0, 0, 0, 0.06);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: cozeModalScale 0.2s ease-out;
}

@keyframes cozeModalScale {
  from { transform: scale(0.96); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.coze-modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #eef0f5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f8fafc;
}
.coze-modal-header h3 {
  font-size: 15px;
  font-weight: 700;
  margin: 0;
  color: #111827;
}
.coze-modal-close-btn {
  font-size: 18px;
  color: #667085;
  cursor: pointer;
  border: none;
  background: none;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.2s;
}
.coze-modal-close-btn:hover {
  color: #111827;
}

.coze-modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.coze-modal-search {
  position: relative;
  margin-bottom: 16px;
}
.coze-modal-search input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #dfe4ef;
  border-radius: 8px;
  font-size: 13px;
  background: #ffffff;
  color: #111827;
  transition: all 0.2s;
}
.coze-modal-search input:focus {
  outline: none;
  border-color: #4d43e6;
  box-shadow: 0 0 0 3px rgba(77, 67, 230, 0.1);
}

.coze-modal-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.coze-modal-row {
  border: 1px solid #eef0f5;
  border-radius: 8px;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all 0.2s;
  background: #ffffff;
  gap: 12px;
}
.coze-modal-row:hover {
  border-color: #dfe4ef;
  background: #f8fafc;
}

.coze-modal-row-info {
  min-width: 0;
  flex: 1;
}
.coze-modal-row-title {
  font-weight: 600;
  font-size: 13.5px;
  color: #111827;
}
.coze-modal-row-desc {
  font-size: 11.5px;
  color: #667085;
  margin-top: 3px;
  line-height: 1.4;
}

.coze-modal-row-btn {
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid #4d43e6;
  background: #4d43e6;
  color: #ffffff;
  transition: all 0.2s;
  flex-shrink: 0;
}
.coze-modal-row-btn:hover {
  background: #3b31c4;
}
.coze-modal-row-btn.added {
  background: #f4f6fb;
  color: #94a3b8;
  border-color: #dfe4ef;
  cursor: default;
}
```

- [ ] **Step 2: 验证样式文件可保存**
运行：`git diff frontend/src/styles.css` 确保无冲突。

---

### Task 2: BuilderView 折叠逻辑与状态初始化 (React State & Imports)

**Files:**
- Modify: `d:\pycharmprojects\langchain\frontend\src\views\BuilderView.jsx:1-40` (添加 Lucide 图标导入，初始化展开/折叠状态)

- [ ] **Step 1: 在 Lucide 图标导入中添加 `ChevronRight`**
```javascript
import {
  ChevronLeft,
  Plus,
  Check,
  Rocket,
  Brain,
  Boxes,
  Wand2,
  Search,
  Database,
  KeyRound,
  Sparkles,
  ServerCog,
  FileText,
  X,
  SquarePen,
  Layers,
  ChevronRight // 添加导入
} from 'lucide-react';
```

- [ ] **Step 2: 在 BuilderView 组件中初始化 React 状态**
在 `BuilderView` 的顶部（例如在 `selectedModel` 声明之后，第 192 行）声明折叠状态和弹窗状态：
```javascript
  // Coze Redesign Collapsible panel states
  const [expandedSections, setExpandedSections] = useState({
    tools: true,
    kb: true,
    memorySession: true,
    memoryUser: false,
    onboarding: false,
  });

  // Modal open states
  const [toolsModalOpen, setToolsModalOpen] = useState(false);
  const [kbModalOpen, setKbModalOpen] = useState(false);
  
  // Search filter states
  const [toolsSearch, setToolsSearch] = useState('');
  const [kbSearch, setKbSearch] = useState('');

  const toggleSection = (key) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };
```

- [ ] **Step 3: 运行 git diff 确认代码行无误**

---

### Task 3: 技能与工具部分重构 (Refactoring Tools & Accordion)

**Files:**
- Modify: `d:\pycharmprojects\langchain\frontend\src\views\BuilderView.jsx:374-396` (替换原本平铺的所有可用工具列表，改用手风琴和已绑定工具卡片)

- [ ] **Step 1: 编写已绑定工具卡片列表和“选择工具”弹窗组件**

替换原本的整个工具 `<Panel>` 组件：
```jsx
          {/* ==================== 技能/工具 ==================== */}
          <div className="coze-group-title">技能</div>
          <div className={`coze-accordion-item ${expandedSections.tools ? 'expanded' : ''}`}>
            <div className="coze-accordion-header" onClick={() => toggleSection('tools')}>
              <div className="coze-header-left">
                <ChevronRight size={14} className="coze-caret-icon" />
                <span>工具 <span className="coze-header-count">({agentForm.tool_ids.length})</span></span>
              </div>
              <button 
                type="button" 
                className="coze-add-button" 
                onClick={(e) => { e.stopPropagation(); setToolsModalOpen(true); }}
              >
                + 添加
              </button>
            </div>
            <div className="coze-accordion-body">
              {tools.filter(t => agentForm.tool_ids.includes(t.id)).map((tool) => (
                <div className="coze-bound-card" key={tool.id}>
                  <div className="coze-bound-card-info">
                    <span className="coze-bound-card-icon">
                      {toolType(tool) === 'builtin_search' ? <Search size={14} /> : <Wand2 size={14} />}
                    </span>
                    <div style={{ minWidth: 0 }}>
                      <div className="coze-bound-card-title">{tool.label}</div>
                      <div className="coze-bound-card-meta">{tool.description}</div>
                    </div>
                  </div>
                  <button 
                    type="button" 
                    className="coze-bound-card-remove" 
                    title="移除绑定"
                    onClick={() => toggleTool(tool.id, agentForm, setAgentForm)}
                  >
                    ✕
                  </button>
                </div>
              ))}
              {agentForm.tool_ids.length === 0 && (
                <p className="muted" style={{ fontSize: '12px', textAlign: 'center', margin: '10px 0 0' }}>
                  暂未绑定任何工具，点击“+ 添加”引入能力。
                </p>
              )}
            </div>
          </div>
```

---

### Task 4: 知识与文本部分重构 (Refactoring Knowledge & Accordion)

**Files:**
- Modify: `d:\pycharmprojects\langchain\frontend\src\views\BuilderView.jsx:398-425` (替换原本知识部分，仅在折叠栏显示绑定卡片，且文件上传区仅在选中绑定卡片时才展开)

- [ ] **Step 1: 替换知识文本库部分**

替换原本的知识 `<Panel>` 组件：
```jsx
          {/* ==================== 知识/文本 ==================== */}
          <div className="coze-group-title">知识</div>
          <div className={`coze-accordion-item ${expandedSections.kb ? 'expanded' : ''}`}>
            <div className="coze-accordion-header" onClick={() => toggleSection('kb')}>
              <div className="coze-header-left">
                <ChevronRight size={14} className="coze-caret-icon" />
                <span>文本 <span className="coze-header-count">({agentForm.knowledge_base_ids.length})</span></span>
              </div>
              <button 
                type="button" 
                className="coze-add-button" 
                onClick={(e) => { e.stopPropagation(); setKbModalOpen(true); }}
              >
                + 添加
              </button>
            </div>
            <div className="coze-accordion-body">
              {knowledgeBases.filter(kb => agentForm.knowledge_base_ids.includes(kb.id)).map((kb) => {
                const isSelectedForUpload = String(docForm.kb_id) === String(kb.id);
                return (
                  <div key={kb.id} style={{ marginBottom: '8px' }}>
                    <div 
                      className="coze-bound-card" 
                      style={{ 
                        cursor: 'pointer', 
                        borderColor: isSelectedForUpload ? '#4d43e6' : '#dfe4ef',
                        background: isSelectedForUpload ? 'rgba(77, 67, 230, 0.02)' : '#f8fafc'
                      }}
                      onClick={() => setDocForm((current) => ({ ...current, kb_id: String(kb.id) }))}
                    >
                      <div className="coze-bound-card-info">
                        <span className="coze-bound-card-icon kb">
                          <Database size={14} />
                        </span>
                        <div style={{ minWidth: 0 }}>
                          <div className="coze-bound-card-title">{kb.name}</div>
                          <div className="coze-bound-card-meta">{kb.description || '无描述'}</div>
                        </div>
                      </div>
                      <button 
                        type="button" 
                        className="coze-bound-card-remove" 
                        title="移除绑定"
                        onClick={(e) => { e.stopPropagation(); toggleKb(kb.id, agentForm, setAgentForm); }}
                      >
                        ✕
                      </button>
                    </div>
                    
                    {/* Only show upload documents list if this KB card is selected */}
                    {isSelectedForUpload && (
                      <div style={{ marginTop: '8px', padding: '10px', background: '#ffffff', border: '1px dashed #dfe4ef', borderRadius: '8px' }}>
                        <div style={{ fontSize: '11px', fontWeight: 'bold', color: '#4d43e6', marginBottom: '8px' }}>
                          📂 知识文档管理 (仅对当前选中的“{kb.name}”操作)
                        </div>
                        <KnowledgeDocumentList 
                          documents={documents.filter(doc => String(doc.knowledge_base_id) === String(kb.id))} 
                          deleteDocument={deleteDocument} 
                        />
                        <div style={{ marginTop: '10px' }}>
                          <KnowledgeUploadBox
                            docForm={docForm}
                            setDocForm={setDocForm}
                            uploadDocument={uploadDocument}
                            uploadKnowledgeFile={uploadKnowledgeFile}
                            uploadingKnowledgeFile={uploadingKnowledgeFile}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
              {agentForm.knowledge_base_ids.length === 0 && (
                <p className="muted" style={{ fontSize: '12px', textAlign: 'center', margin: '10px 0 0' }}>
                  暂未绑定任何知识库，点击“+ 添加”引入检索数据。
                </p>
              )}
            </div>
          </div>
```

---

### Task 5: 记忆与对话体验大类折叠改版 (Refactoring Memory & Onboarding)

**Files:**
- Modify: `d:\pycharmprojects\langchain\frontend\src\views\BuilderView.jsx:427-503` (将原本记忆、用户记忆、对话体验三个 Panel 修改为优雅的折叠子项)

- [ ] **Step 1: 替换记忆与会话管理面板为折叠样式**
```jsx
          {/* ==================== 记忆大类 ==================== */}
          <div className="coze-group-title">记忆</div>
          
          {/* 会话记忆 */}
          <div className={`coze-accordion-item ${expandedSections.memorySession ? 'expanded' : ''}`}>
            <div className="coze-accordion-header" onClick={() => toggleSection('memorySession')}>
              <div className="coze-header-left">
                <ChevronRight size={14} className="coze-caret-icon" />
                <span>会话记忆</span>
              </div>
            </div>
            <div className="coze-accordion-body">
              <ConfigRow label="会话记忆">
                <Toggle
                  checked={!!agentForm.memory?.enabled}
                  label={agentForm.memory?.enabled ? '开启' : '关闭'}
                  onChange={(value) => setAgentForm({ ...agentForm, memory: { ...(agentForm.memory || {}), enabled: value, strategy: 'session_summary' } })}
                />
              </ConfigRow>
              {!!agentForm.memory?.enabled && (
                <ConfigRow label="记忆消息上限">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', width: '100%' }}>
                    <input
                      type="range"
                      min="1"
                      max="100"
                      step="1"
                      style={{ flex: 1, accentColor: '#4d43e6', height: '6px', background: '#dfe4ef', borderRadius: '4px', cursor: 'pointer' }}
                      value={agentForm.memory?.max_messages ?? 12}
                      onChange={(e) => setAgentForm({ ...agentForm, memory: { ...(agentForm.memory || {}), max_messages: Number(e.target.value), strategy: 'session_summary' } })}
                    />
                    <span style={{ minWidth: '24px', fontWeight: 'bold', color: '#4d43e6', fontSize: '13px', textAlign: 'right' }}>
                      {agentForm.memory?.max_messages ?? 12}
                    </span>
                  </div>
                </ConfigRow>
              )}
            </div>
          </div>

          {/* 用户长期记忆 */}
          <div className={`coze-accordion-item ${expandedSections.memoryUser ? 'expanded' : ''}`}>
            <div className="coze-accordion-header" onClick={() => toggleSection('memoryUser')}>
              <div className="coze-header-left">
                <ChevronRight size={14} className="coze-caret-icon" />
                <span>长期记忆 / 用户画像</span>
              </div>
            </div>
            <div className="coze-accordion-body">
              <AgentMemoryProfilePanel
                activeAgentId={activeAgentId}
                canEditActive={canEditActive}
                deleteMemoryProfile={deleteMemoryProfile}
                memoryProfile={memoryProfile}
                memoryProfileDraft={memoryProfileDraft}
                memoryProfileError={memoryProfileError}
                memoryProfileLoading={memoryProfileLoading}
                memoryProfileSaving={memoryProfileSaving}
                saveMemoryProfile={saveMemoryProfile}
                setMemoryProfileDraft={setMemoryProfileDraft}
              />
            </div>
          </div>
```

- [ ] **Step 2: 替换对话体验开场白与问题面板为折叠样式**
```jsx
          {/* ==================== 对话体验 ==================== */}
          <div className="coze-group-title">对话体验</div>
          <div className={`coze-accordion-item ${expandedSections.onboarding ? 'expanded' : ''}`}>
            <div className="coze-accordion-header" onClick={() => toggleSection('onboarding')}>
              <div className="coze-header-left">
                <ChevronRight size={14} className="coze-caret-icon" />
                <span>开场白与引导问题</span>
              </div>
            </div>
            <div className="coze-accordion-body">
              <label className="field-label">开场白文案</label>
              <textarea 
                value={agentForm.opening_message} 
                onChange={(e) => setAgentForm({ ...agentForm, opening_message: e.target.value })} 
                placeholder="例如：你好！我是智能助理，今天有什么可以帮您的？" 
                style={{ width: '100%', minHeight: '80px', padding: '10px', borderRadius: '8px', border: '1px solid #dfe4ef' }}
              />
              <small className="counter" style={{ display: 'block', textAlign: 'right', margin: '4px 0 10px', color: '#94a3b8' }}>
                {agentForm.opening_message?.length ?? 0}/1000
              </small>
              
              <div style={{ borderTop: '1px solid #eef0f5', paddingTop: '10px', marginTop: '10px' }}>
                <ConfigRow label="开场引导问题"><span className="muted">前台展示</span></ConfigRow>
                <div className="dynamic-list">
                  {(agentForm.suggested_questions || []).map((question, index) => (
                    <div className="list-row" key={index} style={{ display: 'flex', gap: '8px', marginBottom: '6px' }}>
                      <input 
                        style={{ flex: 1, padding: '6px 10px', border: '1px solid #dfe4ef', borderRadius: '6px' }}
                        value={question} 
                        onChange={(e) => updateSuggestedQuestion(index, e.target.value)} 
                      />
                      <button 
                        type="button" 
                        className="danger text"
                        style={{ padding: '0 8px', color: '#ef4444' }}
                        onClick={() => removeSuggestedQuestion(index)}
                      >
                        删除
                      </button>
                    </div>
                  ))}
                </div>
                <button 
                  type="button" 
                  style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '8px', color: '#4d43e6', fontWeight: 600, background: 'none', border: 'none', cursor: 'pointer' }}
                  onClick={addSuggestedQuestion}
                >
                  <Plus size={12} /> 输入引导问题
                </button>
              </div>
            </div>
          </div>
```

---

### Task 6: 编写“选择工具”与“选择知识库”弹窗组件 (React Portal Modals)

**Files:**
- Modify: `d:\pycharmprojects\langchain\frontend\src\views\BuilderView.jsx:504-505` (在组件末尾渲染弹窗组件)

- [ ] **Step 1: 追加 Modal 弹窗渲染代码**

追加到 `BuilderView.jsx` 原有的 `knowledgeDialogOpen` 弹窗判断下方（约 483 行左右）：
```jsx
          {/* ==================== 选择工具弹窗 ==================== */}
          {toolsModalOpen && (
            <div className="coze-modal-backdrop" onClick={() => setToolsModalOpen(false)}>
              <div className="coze-modal-container" onClick={(e) => e.stopPropagation()}>
                <div className="coze-modal-header">
                  <h3>选择工具 (Select Tool)</h3>
                  <button className="coze-modal-close-btn" onClick={() => setToolsModalOpen(false)}>✕</button>
                </div>
                <div className="coze-modal-body">
                  <div className="coze-modal-search">
                    <input 
                      type="text" 
                      placeholder="搜索可用工具名称或描述..." 
                      value={toolsSearch}
                      onChange={(e) => setToolsSearch(e.target.value)}
                      autoFocus
                    />
                  </div>
                  <div className="coze-modal-list">
                    {tools
                      .filter(t => 
                        t.label.toLowerCase().includes(toolsSearch.toLowerCase()) || 
                        t.description.toLowerCase().includes(toolsSearch.toLowerCase())
                      )
                      .map((tool) => {
                        const isAdded = agentForm.tool_ids.includes(tool.id);
                        return (
                          <div className="coze-modal-row" key={tool.id}>
                            <div className="coze-modal-row-info">
                              <span style={{ fontSize: '16px', marginRight: '8px' }}>
                                {toolType(tool) === 'builtin_search' ? '🔍' : '🛠️'}
                              </span>
                              <strong className="coze-modal-row-title">{tool.label}</strong>
                              <div className="coze-modal-row-desc">{tool.description}</div>
                            </div>
                            <button
                              type="button"
                              className={`coze-modal-row-btn ${isAdded ? 'added' : ''}`}
                              disabled={isAdded}
                              onClick={() => {
                                if (isAdded) return;
                                toggleTool(tool.id, agentForm, setAgentForm);
                              }}
                            >
                              {isAdded ? '已添加' : '添加'}
                            </button>
                          </div>
                        );
                      })
                    }
                    {tools.length === 0 && <p className="muted" style={{ textAlign: 'center' }}>无可用工具。</p>}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ==================== 选择知识库弹窗 ==================== */}
          {kbModalOpen && (
            <div className="coze-modal-backdrop" onClick={() => setKbModalOpen(false)}>
              <div className="coze-modal-container" onClick={(e) => e.stopPropagation()}>
                <div className="coze-modal-header">
                  <h3>选择知识库 (Select Knowledge Base)</h3>
                  <button className="coze-modal-close-btn" onClick={() => setKbModalOpen(false)}>✕</button>
                </div>
                <div className="coze-modal-body">
                  <div style={{ display: 'flex', gap: '10px', marginBottom: '16px' }}>
                    <div className="coze-modal-search" style={{ flex: 1, marginBottom: 0 }}>
                      <input 
                        type="text" 
                        placeholder="搜索我的知识库..." 
                        value={kbSearch}
                        onChange={(e) => setKbSearch(e.target.value)}
                        autoFocus
                      />
                    </div>
                    <button 
                      type="button"
                      className="coze-modal-row-btn"
                      style={{ background: '#10b981', borderColor: '#10b981', padding: '0 16px', height: '38px', borderRadius: '8px' }}
                      onClick={() => {
                        setKbModalOpen(false);
                        openKnowledgeDialog();
                      }}
                    >
                      + 新建知识库
                    </button>
                  </div>
                  <div className="coze-modal-list">
                    {knowledgeBases
                      .filter(kb => kb.name.toLowerCase().includes(kbSearch.toLowerCase()))
                      .map((kb) => {
                        const isAdded = agentForm.knowledge_base_ids.includes(kb.id);
                        return (
                          <div className="coze-modal-row" key={kb.id}>
                            <div className="coze-modal-row-info">
                              <span style={{ fontSize: '16px', marginRight: '8px' }}>📄</span>
                              <strong className="coze-modal-row-title">{kb.name}</strong>
                              <div className="coze-modal-row-desc">{kb.description || '暂无描述信息'}</div>
                            </div>
                            <button
                              type="button"
                              className={`coze-modal-row-btn ${isAdded ? 'added' : ''}`}
                              disabled={isAdded}
                              onClick={() => {
                                if (isAdded) return;
                                toggleKb(kb.id, agentForm, setAgentForm);
                              }}
                            >
                              {isAdded ? '已添加' : '添加'}
                            </button>
                          </div>
                        );
                      })
                    }
                    {knowledgeBases.length === 0 && <p className="muted" style={{ textAlign: 'center' }}>无可用知识库，点击右上角新建。</p>}
                  </div>
                </div>
              </div>
            </div>
          )}
```

---

### Task 7: 运行 Vite 编译与打包验证 (Build Validation)

- [ ] **Step 1: 运行 Vite 生产编译**
在 `frontend` 目录运行 `npm run build` 确保无任何语法、引入或语法检查错误。
Command: `npm run build`
Expected: `vite build` completed successfully without errors.

- [ ] **Step 2: 创建 Walkthrough 演示报告并提交 Git**
将改动提交并同步：
```bash
git add frontend/src/styles.css frontend/src/views/BuilderView.jsx
git commit -m "feat: redesign builder config panel to Coze collapsible list with premium card modals"
```
