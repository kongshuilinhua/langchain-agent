/**
 * 记忆档案工具函数。
 * 从 utils.js 提取 —— 记忆档案的标准化、序列化与校验。
 */

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isJsonCompatiblePreference(value) {
  if (value == null) return true;
  if (['string', 'number', 'boolean'].includes(typeof value)) return true;
  if (Array.isArray(value)) return value.every((item) => item == null || ['string', 'number', 'boolean'].includes(typeof item));
  return false;
}

function parsePreferences(value) {
  const text = String(value || '').trim();
  if (!text) return {};
  let parsed;
  try { parsed = JSON.parse(text); } catch { throw new Error('偏好必须是合法 JSON 对象。'); }
  if (!isPlainObject(parsed)) throw new Error('偏好必须是 JSON 对象。');
  for (const [key, item] of Object.entries(parsed)) {
    if (!isJsonCompatiblePreference(item)) throw new Error(`偏好 ${key} 只支持字符串、数字、布尔值、null 或数组。`);
  }
  return parsed;
}

function defaultMemoryProfile(agentId = null) {
  return { agent_id: agentId, enabled: false, summary: '', facts: [], preferences: {}, updated_at: null };
}

function normalizeMemoryProfile(profile, agentId = null) {
  return {
    ...defaultMemoryProfile(agentId), ...(profile || {}),
    agent_id: profile?.agent_id ?? agentId,
    enabled: Boolean(profile?.enabled),
    summary: String(profile?.summary || ''),
    facts: Array.isArray(profile?.facts) ? profile.facts.map((item) => {
      if (item && typeof item === 'object' && 'text' in item) {
        return String(item.text);
      }
      return String(item);
    }).filter(Boolean) : [],
    preferences: isPlainObject(profile?.preferences) ? profile.preferences : {},
    updated_at: profile?.updated_at || null,
  };
}

function profileToDraft(profile) {
  const normalized = normalizeMemoryProfile(profile, profile?.agent_id ?? null);
  return { enabled: normalized.enabled, summary: normalized.summary, factsText: normalized.facts.join('\n'), preferencesText: JSON.stringify(normalized.preferences || {}, null, 2) };
}

function draftFacts(value) {
  return String(value || '').split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function memoryProfilePayload(draft) {
  const facts = draftFacts(draft.factsText);
  if (facts.length > 50) throw new Error('用户记忆事实最多 50 条。');
  const summary = String(draft.summary || '');
  if (summary.length > 4000) throw new Error('用户记忆摘要最多 4000 字符。');
  return { enabled: Boolean(draft.enabled), summary, facts, preferences: parsePreferences(draft.preferencesText) };
}

function safeJsonPreview(value) {
  try { return parsePreferences(value); } catch { return null; }
}

export {
  isPlainObject,
  isJsonCompatiblePreference,
  parsePreferences,
  safeJsonPreview,
  defaultMemoryProfile,
  normalizeMemoryProfile,
  profileToDraft,
  draftFacts,
  memoryProfilePayload,
};
