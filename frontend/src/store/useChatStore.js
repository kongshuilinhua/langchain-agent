/**
 * 聊天状态 Store — 管理 messages, sessions, SSE streaming, RAG/search/thinking 开关。
 * 替代 main.jsx 中的 15+ 聊天相关的 useState。
 */
import { create } from 'zustand';
import { api, API_BASE, isAuthError, notifyAuthExpired, errorMessage } from '../lib/api.js';

export const useChatStore = create((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: [],
  sources: [],
  busy: false,
  error: '',
  draft: '',
  homePrompt: '',
  chatMode: 'published',
  ragEnabled: true,
  thinkingEnabled: false,
  searchEnabled: false,
  chatVariables: {},
  chatAttachments: [],
  uploadingAttachment: false,
  sessionTitleDraft: '',
  toolDebugEvents: [],
  feedbackByMessage: {},

  setBusy: (busy) => set({ busy }),
  setError: (error) => set({ error }),
  setDraft: (draft) => set({ draft }),
  setHomePrompt: (homePrompt) => set({ homePrompt }),
  setRagEnabled: (ragEnabled) => set({ ragEnabled }),
  setThinkingEnabled: (thinkingEnabled) => set({ thinkingEnabled }),
  setSearchEnabled: (searchEnabled) => set({ searchEnabled }),
  setChatMode: (chatMode) => set({ chatMode }),
  setActiveSessionId: (activeSessionId) => set({ activeSessionId }),
  setSessions: (sessions) => set((s) => ({
    sessions: typeof sessions === 'function' ? sessions(s.sessions) : sessions
  })),
  setMessages: (messages) => set((s) => ({
    messages: typeof messages === 'function' ? messages(s.messages) : messages
  })),
  updateChatVariable: (key, value) => set((s) => ({ chatVariables: { ...s.chatVariables, [key]: value } })),
  setChatAttachments: (chatAttachments) => set((s) => ({
    chatAttachments: typeof chatAttachments === 'function' ? chatAttachments(s.chatAttachments) : chatAttachments
  })),
  setSources: (sources) => set({ sources }),
  setUploadingAttachment: (uploadingAttachment) => set({ uploadingAttachment }),
  setSessionTitleDraft: (sessionTitleDraft) => set({ sessionTitleDraft }),
  setToolDebugEvents: (toolDebugEvents) => set((s) => ({
    toolDebugEvents: typeof toolDebugEvents === 'function' ? toolDebugEvents(s.toolDebugEvents) : toolDebugEvents
  })),
  setFeedbackByMessage: (feedbackByMessage) => set((s) => ({
    feedbackByMessage: typeof feedbackByMessage === 'function' ? feedbackByMessage(s.feedbackByMessage) : feedbackByMessage
  })),
  setChatVariables: (chatVariables) => set((s) => ({
    chatVariables: typeof chatVariables === 'function' ? chatVariables(s.chatVariables) : chatVariables
  })),
  addMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),
  updateLastMessage: (updater) => set((s) => {
    const msgs = [...s.messages];
    if (msgs.length) msgs[msgs.length - 1] = updater(msgs[msgs.length - 1]);
    return { messages: msgs };
  }),

  startNewChat: (openingMessage) => {
    set({
      activeSessionId: null,
      messages: openingMessage ? [{ role: 'assistant', content: openingMessage }] : [],
      sources: [],
      draft: '',
      homePrompt: '',
      error: '',
      chatAttachments: [],
      thinkingEnabled: false,
      searchEnabled: false,
    });
  },

  sendMessage: async ({ text, activeAgentId, token, ragEnabled, thinkingEnabled, searchEnabled, chatVariables, agentForm, chatAttachments }) => {
    set({ busy: true, error: '', draft: '', homePrompt: '' });
    get().addMessage({ role: 'user', content: text, attachments: chatAttachments });
    get().addMessage({ role: 'assistant', content: '', pending: true });

    try {
      const response = await fetch(`${API_BASE}/api/agents/${activeAgentId}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          message: text || '请分析附件内容。',
          session_id: get().activeSessionId || null,
          mode: 'published',
          rag_enabled: ragEnabled,
          rag_options: agentForm?.rag || undefined,
          thinking_enabled: thinkingEnabled,
          search_enabled: searchEnabled,
          variables: chatVariables,
          attachments: chatAttachments.map((item) => ({ id: item.id, type: item.type, mime_type: item.content_type })),
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const err = new Error(errorMessage(data.detail || data.message || `HTTP ${response.status}`));
        if (isAuthError({ status: response.status })) notifyAuthExpired();
        throw err;
      }
      if (!response.body) throw new Error('当前浏览器不支持流式响应。');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';
        for (const part of parts) _handleSseEvent(part, get, set);
      }
    } catch (err) {
      if (isAuthError(err)) throw err;
      set({ error: errorMessage(err) });
      get().updateLastMessage((last) => ({ ...last, pending: false, error: true, content: errorMessage(err) }));
    } finally {
      set({ busy: false });
    }
  },
}));

function _handleSseEvent(raw, get, set) {
  const event = raw.match(/^event: (.+)$/m)?.[1];
  const dataLine = raw.match(/^data: (.+)$/m)?.[1];
  const data = dataLine ? JSON.parse(dataLine) : {};

  if (event === 'token') {
    get().updateLastMessage((last) => ({ ...last, pending: false, content: (last.content || '') + data.content }));
  }
  if (event === 'thinking_token') {
    // 思考轨迹独立累加到 thinking 字段，绝不拼入 content（content 是最终落库正文）
    get().updateLastMessage((last) => ({ ...last, thinking: (last.thinking || '') + data.content }));
  }
  if (event === 'sources') {
    set({ sources: data.items || [] });
  }
  if (event === 'done') {
    set({ activeSessionId: data.session_id || null });
    get().updateLastMessage((last) => ({
      ...last, id: data.message_id, pending: false, content: data.content || last.content,
    }));
  }
  if (event === 'error') {
    const detail = errorMessage(data.detail || data.message || '智能体运行失败');
    set({ error: detail });
    get().updateLastMessage((last) => ({ ...last, pending: false, error: true, content: detail }));
  }
}
