import React, { useRef, useState, useEffect } from 'react';
import { SquarePen, ImagePlus, FileText, X, Search, Sparkles } from 'lucide-react';
import { MessageList } from '../components/MessageList.jsx';
import {
  reasoningCapabilityForModel,
  thinkingStatusText,
  ragStatusText,
  webSearchStatusText,
  attachmentAcceptForModel,
  attachmentHintForModel,
  uploadTypeFromContentType,
  modelCapabilityWarning,
  handleAttachmentInput,
  handleAttachmentPaste,
  handleAttachmentDrop,
} from '../utils.js';

const CHAT_COPY = {
  noAgentTitle: '暂无可对话的智能体',
  noAgentDesc: '主对话页只开放已审核并上架的智能体。请先发布，普通用户发布后需要管理员审核。',
  welcomeTitle: '今天想让哪个智能体帮你？',
  welcomeDesc: '选择智能体后可以直接聊天，也可以进入配置页调整能力。',
  promptIntro: '介绍一下你的能力',
  promptPlan: '帮我整理一个方案',
  promptKb: '基于知识库回答一个问题',
  fallbackAgent: '智能体',
  sendPrefix: '给',
  sendSuffix: '发送消息',
  sendMessage: '发送消息...',
  uploading: '附件上传中...',
  pendingAttachment: '个附件待发送',
  newChat: '新建会话',
  thinking: '深度思考',
  search: '联网搜索',
  rag: '知识库',
  unavailable: '不可用',
  on: '开启',
  off: '关闭',
};

// Simple utility function to determine check status
function hasTransferFiles(dt) {
  if (!dt) return false;
  if (dt.files && dt.files.length) return true;
  if (dt.items && dt.items.length) {
    for (let i = 0; i < dt.items.length; i++) {
      if (dt.items[i].kind === 'file') return true;
    }
  }
  return false;
}

export function ChatView({
  activeAgent,
  activeAgentId,
  activeSummary,
  chatAgents,
  canEditActive,
  openBuilder,
  setActiveAgentId,
  // ChatHomeV2 props
  activeSessionId,
  agentForm,
  busy,
  chatAttachments,
  chatVariables,
  error,
  feedbackByMessage,
  homePrompt,
  messages,
  sendMessage,
  sendSuggestedQuestion,
  setChatAttachments,
  setHomePrompt,
  ragEnabled,
  setRagEnabled,
  searchEnabled,
  setSearchEnabled,
  sources,
  submitFeedback,
  ragRuntime,
  webSearchRuntime,
  thinkingEnabled,
  setThinkingEnabled,
  uploadChatAttachment,
  uploadingAttachment,
  updateChatVariable,
}) {
  const hasChatAgent = chatAgents.length > 0;

  return (
    <>
      <header className="chat-topbar">
        <div className="agent-select">
          <span className="agent-avatar">{activeSummary?.avatar || activeAgent?.avatar || 'AI'}</span>
          <select
            value={chatAgents.some((agent) => agent.id === activeAgentId) ? activeAgentId : ''}
            onChange={(e) => setActiveAgentId(Number(e.target.value))}
          >
            <option value="" disabled>
              {chatAgents.length ? '选择已上架智能体' : '暂无已上架智能体'}
            </option>
            {chatAgents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
          <button
            className="agent-edit-button"
            type="button"
            disabled={!canEditActive}
            title="编辑智能体"
            aria-label="编辑智能体"
            onClick={() => openBuilder(activeAgentId)}
          >
            <SquarePen size={16} />
          </button>
        </div>
      </header>

      <ChatHomeV2
        activeAgent={activeAgent}
        activeSessionId={activeSessionId}
        agentForm={agentForm}
        busy={busy}
        chatAgents={chatAgents}
        chatAttachments={chatAttachments}
        chatVariables={chatVariables}
        error={error}
        feedbackByMessage={feedbackByMessage}
        homePrompt={homePrompt}
        messages={messages}
        sendMessage={sendMessage}
        sendSuggestedQuestion={sendSuggestedQuestion}
        setChatAttachments={setChatAttachments}
        setHomePrompt={setHomePrompt}
        ragEnabled={ragEnabled}
        setRagEnabled={setRagEnabled}
        searchEnabled={searchEnabled}
        setSearchEnabled={setSearchEnabled}
        sources={sources}
        submitFeedback={submitFeedback}
        ragRuntime={ragRuntime}
        webSearchRuntime={webSearchRuntime}
        thinkingEnabled={thinkingEnabled}
        setThinkingEnabled={setThinkingEnabled}
        uploadChatAttachment={uploadChatAttachment}
        uploadingAttachment={uploadingAttachment}
        updateChatVariable={updateChatVariable}
      />
    </>
  );
}

function ChatHomeV2({
  activeAgent,
  activeSessionId,
  agentForm,
  busy,
  chatAgents,
  chatAttachments,
  chatVariables,
  error,
  feedbackByMessage,
  homePrompt,
  messages,
  sendMessage,
  sendSuggestedQuestion,
  setChatAttachments,
  setHomePrompt,
  ragEnabled,
  setRagEnabled,
  ragRuntime,
  searchEnabled,
  setSearchEnabled,
  webSearchRuntime,
  thinkingEnabled,
  setThinkingEnabled,
  sources,
  submitFeedback,
  uploadChatAttachment,
  uploadingAttachment,
  updateChatVariable,
}) {
  const currentModel = activeAgent?.user_model_config || activeAgent?.model_config || null;
  const ragAvailable = ragRuntime.available;
  const effectiveRagEnabled = ragAvailable && ragEnabled;
  const ragStatus = ragStatusText(ragRuntime, effectiveRagEnabled);
  const searchAvailable = webSearchRuntime.available;
  const effectiveSearchEnabled = searchAvailable && searchEnabled;
  const searchStatus = webSearchStatusText(webSearchRuntime, effectiveSearchEnabled);
  const thinkingCapability = reasoningCapabilityForModel(currentModel);
  const effectiveThinkingEnabled = thinkingEnabled && thinkingCapability.supported;
  const modelWarning = modelCapabilityWarning(currentModel, chatAttachments);
  const attachmentAccept = attachmentAcceptForModel(currentModel);
  const attachmentDisabled = uploadingAttachment || !attachmentAccept;
  const attachmentHint = chatAttachments.length ? `${chatAttachments.length} file ready` : attachmentHintForModel(currentModel);
  const conversationStarted = Boolean(activeSessionId) || messages.some((message) => message.role === 'user');
  const runtimeWarning = modelWarning || { text: '' }; // Fallback since runtimeStatusMessage might be handled or simple
  const hasChatAgent = chatAgents.length > 0;

  return (
    <div className={`chat-home ${conversationStarted ? 'has-conversation' : 'is-empty'}`}>
      <div className="conversation">
        {!hasChatAgent ? (
          <section className="welcome-panel">
            <span className="welcome-avatar">AI</span>
            <h1>{CHAT_COPY.noAgentTitle}</h1>
            <p>{CHAT_COPY.noAgentDesc}</p>
          </section>
        ) : !conversationStarted ? (
          <section className="welcome-panel">
            <span className="welcome-avatar">{activeAgent?.avatar || agentForm.avatar || 'AI'}</span>
            <h1>{CHAT_COPY.welcomeTitle}</h1>
            <p>{activeAgent?.description || agentForm.description || CHAT_COPY.welcomeDesc}</p>
            <div className="quick-prompts">
              {(agentForm.suggested_questions?.length ? agentForm.suggested_questions : [CHAT_COPY.promptIntro, CHAT_COPY.promptPlan, CHAT_COPY.promptKb]).map((question, index) => (
                <button type="button" key={`${question}-${index}`} onClick={() => sendSuggestedQuestion(question)}>
                  {question}
                </button>
              ))}
            </div>
          </section>
        ) : (
          <MessageList
            messages={messages}
            feedbackByMessage={feedbackByMessage}
            submitFeedback={submitFeedback}
            avatar={activeAgent?.avatar || agentForm.avatar || 'AI'}
          />
        )}
      </div>
      {(agentForm.variables || []).length > 0 && (
        <VariableBar variables={agentForm.variables} values={chatVariables} onChange={updateChatVariable} />
      )}
      {hasChatAgent && (
        <div className="composer-dock">
          <ChatComposer
            className="home-composer"
            value={homePrompt}
            onChange={setHomePrompt}
            placeholder={`${CHAT_COPY.sendPrefix} ${activeAgent?.name || agentForm.name || CHAT_COPY.fallbackAgent} ${CHAT_COPY.sendSuffix}`}
            onSubmit={(event) => sendMessage(event, homePrompt)}
            submitDisabled={busy || uploadingAttachment || !!modelWarning || (!homePrompt.trim() && !chatAttachments.length)}
            attachmentAccept={attachmentAccept}
            attachmentDisabled={attachmentDisabled}
            attachmentHint={attachmentHint}
            currentModel={currentModel}
            onAttachmentInput={(event) => handleAttachmentInput(event, uploadChatAttachment)}
            onAttachmentPaste={(event) => handleAttachmentPaste(event, uploadChatAttachment)}
            attachments={chatAttachments}
            removeAttachment={(id) => setChatAttachments((items) => items.filter((item) => item.id !== id))}
            onFileDrop={(files) => handleAttachmentDrop(files, uploadChatAttachment)}
            runtimeWarning={runtimeWarning?.text || runtimeWarning}
            searchAvailable={searchAvailable}
            searchEnabled={effectiveSearchEnabled}
            searchStatus={searchStatus}
            onToggleSearch={() => setSearchEnabled(!searchEnabled)}
            thinkingCapability={thinkingCapability}
            thinkingEnabled={effectiveThinkingEnabled}
            onToggleThinking={() => {
              if (!thinkingCapability.supported) return;
              setThinkingEnabled(!thinkingEnabled);
            }}
            ragAvailable={ragAvailable}
            ragEnabled={effectiveRagEnabled}
            ragStatus={ragStatus}
            onToggleRag={() => setRagEnabled(!ragEnabled)}
          />
        </div>
      )}
      {error && <p className="error inline">{error}</p>}
    </div>
  );
}

function ChatComposer({
  attachmentAccept,
  attachmentDisabled,
  attachmentHint,
  attachments = [],
  className,
  currentModel,
  includeNewChat = false,
  onAttachmentInput,
  onAttachmentPaste,
  onChange,
  onFileDrop,
  onNewChat,
  onSubmit,
  onToggleRag,
  onToggleSearch,
  onToggleThinking,
  placeholder,
  removeAttachment,
  ragAvailable,
  ragEnabled,
  ragStatus,
  searchAvailable,
  searchEnabled,
  searchStatus,
  submitDisabled,
  thinkingCapability,
  thinkingEnabled,
  value,
  runtimeWarning,
}) {
  const textareaRef = useRef(null);
  const [dragActive, setDragActive] = useState(false);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }, [value]);

  function handleKeyDown(event) {
    if (event.key !== 'Enter' || event.shiftKey) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function handleDragOver(event) {
    if (attachmentDisabled || !hasTransferFiles(event.dataTransfer)) return;
    event.preventDefault();
    setDragActive(true);
  }

  function handleDragLeave(event) {
    if (!event.currentTarget.contains(event.relatedTarget)) {
      setDragActive(false);
    }
  }

  async function handleDrop(event) {
    if (attachmentDisabled || !hasTransferFiles(event.dataTransfer)) return;
    event.preventDefault();
    setDragActive(false);
    await onFileDrop?.(event.dataTransfer.files);
  }

  return (
    <form
      className={`composer ${className || ''} ${dragActive ? 'drag-active' : ''}`}
      onSubmit={onSubmit}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(event) => handleDrop(event).catch((err) => console.error(err))}
    >
      {attachments.length > 0 && (
        <AttachmentPreviewTray attachments={attachments} removeAttachment={removeAttachment} />
      )}
      <div className="composer-row-main">
        {includeNewChat && (
          <button className="new-chat-in-composer" type="button" title="新建会话" onClick={onNewChat}>
            <Sparkles size={16} />
          </button>
        )}
        <div className="composer-input-wrapper">
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={onAttachmentPaste}
            placeholder={placeholder}
          />
        </div>
        <button className="send-btn" type="submit" disabled={submitDisabled}>
          发送
        </button>
      </div>

      <div className="composer-toolbar">
        <div className="toolbar-caps">
          {attachmentAccept && (
            <label className={`tool-cap-btn attach-btn ${attachmentDisabled ? 'disabled' : ''}`}>
              <input
                type="file"
                multiple
                accept={attachmentAccept}
                disabled={attachmentDisabled}
                onChange={onAttachmentInput}
              />
              <ImagePlus size={15} />
              <span>{attachmentHint || '上传附件'}</span>
            </label>
          )}

          <button
            type="button"
            className={`tool-cap-btn ${searchEnabled ? 'on' : ''} ${!searchAvailable ? 'disabled' : ''}`}
            disabled={!searchAvailable}
            onClick={onToggleSearch}
          >
            <span>{CHAT_COPY.search}</span>
            <small>{searchStatus}</small>
          </button>

          <button
            type="button"
            className={`tool-cap-btn ${thinkingEnabled ? 'on' : ''} ${!thinkingCapability.supported ? 'disabled' : ''}`}
            disabled={!thinkingCapability.supported}
            onClick={onToggleThinking}
          >
            <span>{CHAT_COPY.thinking}</span>
            <small>{thinkingStatusText(thinkingCapability, thinkingEnabled)}</small>
          </button>

          <button
            type="button"
            className={`tool-cap-btn ${ragEnabled ? 'on' : ''} ${!ragAvailable ? 'disabled' : ''}`}
            disabled={!ragAvailable}
            onClick={onToggleRag}
          >
            <span>{CHAT_COPY.rag}</span>
            <small>{ragStatus}</small>
          </button>
        </div>
      </div>
      {runtimeWarning && <p className="runtime-warning">{runtimeWarning}</p>}
    </form>
  );
}

function AttachmentPreviewTray({ attachments, removeAttachment }) {
  return (
    <div className="attachment-preview-tray">
      {attachments.map((item) => {
        const isImage = item.type === 'image' || uploadTypeFromContentType(item.content_type) === 'image';
        return (
          <div className={isImage ? 'attachment-preview image' : 'attachment-preview document'} key={item.id}>
            {isImage ? (
              item.preview_url ? <img src={item.preview_url} alt={item.filename} /> : <ImagePlus size={22} />
            ) : (
              <FileText size={18} />
            )}
            {!isImage && <span>{item.filename}</span>}
            {!isImage && <small>{item.type || uploadTypeFromContentType(item.content_type)}</small>}
            <button type="button" aria-label={`移除 ${item.filename}`} onClick={() => removeAttachment(item.id)}>
              <X size={13} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function VariableBar({ variables, values, onChange }) {
  return (
    <div className="chat-variable-bar">
      {variables.map((variable) => (
        <label key={variable.key}>
          {variable.label || variable.key}
          {variable.type === 'boolean' ? (
            <select
              value={String(values[variable.key] ?? variable.default_value ?? false)}
              onChange={(e) => onChange(variable.key, e.target.value === 'true')}
            >
              <option value="false">false</option>
              <option value="true">true</option>
            </select>
          ) : (
            <input
              type={variable.type === 'number' ? 'number' : 'text'}
              value={values[variable.key] ?? variable.default_value ?? ''}
              onChange={(e) => onChange(variable.key, e.target.value)}
            />
          )}
        </label>
      ))}
    </div>
  );
}
