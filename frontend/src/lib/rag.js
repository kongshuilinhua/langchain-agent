/**
 * RAG / Runtime 状态工具函数。
 * 从 utils.js 提取 —— 运行时状态解析、RAG/WebSearch 状态文本。
 */

function defaultRuntimeStatus() {
  return {
    status: 'offline',
    issues: ['Backend health check is unavailable.'],
    dependencies: {
      embedding: { configured: false, available: false, model: '', base_url: '', mock: true, reason: 'health_unavailable' },
      vector_store: { available: false, active_backend: 'unknown', fallback: false },
      web_search: { configured: false, enabled: false, provider: 'duckduckgo_html', requires_api_key: false },
    },
  };
}

function getRagRuntime(status) {
  const embedding = status?.dependencies?.embedding || {};
  const vector = status?.dependencies?.vector_store || {};
  const model = String(embedding.model || '').trim();
  const reason = embedding.reason || vector.error || (status?.status === 'offline' ? 'health_unavailable' : '');
  const available = Boolean((embedding.available ?? embedding.configured) && !embedding.mock && (vector.available || vector.fallback));
  return { available, model: model || '后端默认 Embedding', baseUrl: embedding.base_url || '', mock: Boolean(embedding.mock), degraded: status?.status === 'degraded' || Boolean(vector.fallback), reason, vectorBackend: vector.active_backend || vector.backend || '', issues: status?.issues || [] };
}

function ragStatusText(runtime, enabled) {
  if (!runtime?.available) return runtime?.reason ? `后端默认 RAG 检索能力不可用：${runtime.reason}` : '后端默认 RAG 检索能力不可用，本轮不会检索知识库';
  if (runtime.degraded) return `RAG 可用但处于降级状态：${runtime.issues?.[0] || '部分依赖不可用'}`;
  return enabled ? `RAG 开启，使用后端默认 ${runtime.model} 检索知识库` : `RAG 关闭，后端默认 ${runtime.model} 本轮不检索知识库`;
}

function getWebSearchRuntime(status) {
  const search = status?.dependencies?.web_search || {};
  return { available: Boolean(search.enabled && search.configured), provider: search.provider || 'duckduckgo_html', requiresApiKey: Boolean(search.requires_api_key), topK: Number(search.top_k || 5) };
}

function webSearchStatusText(runtime, enabled) {
  if (!runtime?.available) return 'Web search unavailable: backend search is disabled';
  return enabled ? `Web search on: ${runtime.provider}, up to ${runtime.topK || 5} results` : 'Web search off: this turn will not call the search service';
}

function runtimeStatusMessage(ragRuntime, webSearchRuntime) {
  if (ragRuntime?.reason === 'health_unavailable') return '后端健康检查不可用，聊天和检索能力可能无法正常工作。';
  if (!ragRuntime?.available) return ragStatusText(ragRuntime, false);
  if (ragRuntime?.degraded) return ragStatusText(ragRuntime, false);
  return '';
}

export {
  defaultRuntimeStatus,
  getRagRuntime,
  ragStatusText,
  getWebSearchRuntime,
  webSearchStatusText,
  runtimeStatusMessage,
};
