/**
 * 聊天状态 Store — 管理 messages, sessions, SSE streaming, RAG/search/thinking 开关。
 * 替代 main.jsx 中的 15+ 聊天相关的 useState。
 */
import { create } from 'zustand';
import { ApiError, API_BASE, isAuthError, notifyAuthExpired, errorMessage } from '../lib/api.js';

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

  sendMessage: async ({
    text,
    activeAgentId,
    token,
    sessionId,
    mode = 'published',
    isDebug = false,
    ragEnabled,
    ragOptions,
    thinkingEnabled,
    searchEnabled,
    variables = {},
    chatAttachments = [],
  }) => {
    const outgoingAttachments = [...chatAttachments];
    set({ busy: true, error: '', draft: '', homePrompt: '', sources: [], toolDebugEvents: [], chatAttachments: [] });
    get().addMessage({ role: 'user', content: text, attachments: outgoingAttachments });
    get().addMessage({ role: 'assistant', content: '', pending: true });

    try {
      const response = await fetch(`${API_BASE}/api/agents/${activeAgentId}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          message: text || '请分析附件内容。',
          session_id: sessionId ?? get().activeSessionId ?? null,
          mode,
          is_debug: isDebug,
          rag_enabled: ragEnabled,
          rag_options: ragOptions || undefined,
          thinking_enabled: thinkingEnabled,
          search_enabled: searchEnabled,
          variables,
          attachments: outgoingAttachments.map((item) => ({ id: item.id, type: item.type, mime_type: item.content_type })),
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const err = new ApiError(errorMessage(data.detail || data.message || `HTTP ${response.status}`), response.status, data);
        if (isAuthError(err)) notifyAuthExpired();
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
      const message = isAuthError(err) ? '登录已失效，请重新登录。' : errorMessage(err);
      set({ error: message });
      get().updateLastMessage((last) => ({ ...last, pending: false, error: true, content: message }));
      if (isAuthError(err)) throw err;
    } finally {
      set({ busy: false, chatAttachments: [] });
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
  if (event === 'sources') {
    const sources = data.items || [];
    set({ sources });
    get().updateLastMessage((last) => (last?.role === 'assistant' ? { ...last, sources } : last));
  }
  if (['rag_status', 'tool_call', 'memory_used', 'memory_compaction', 'search_status', 'thinking_status'].includes(event)) {
    set((state) => ({
      toolDebugEvents: [
        ...state.toolDebugEvents,
        {
          event,
          received_at: new Date().toLocaleTimeString(),
          ...data,
        },
      ].slice(-30),
    }));
  }
  if (event === 'done') {
    set({ activeSessionId: data.session_id || null });
    get().updateLastMessage((last) => ({
      ...last, id: data.message_id, run_id: data.run_id, pending: false, content: data.content || last.content,
    }));
  }
  if (event === 'error') {
    const detail = errorMessage(data.detail || data.message || '智能体运行失败');
    set({ error: detail });
    get().updateLastMessage((last) => ({ ...last, pending: false, error: true, content: detail }));
  }
}
