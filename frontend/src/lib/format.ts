/**
 * 格式化与标签工具函数。
 * 从 utils.js 提取 —— 角色标签、状态标签、日期格式化。
 * Phase 5: TypeScript 迁移示例。
 */

interface User {
  name?: string;
  email?: string;
}

type Role = string | null | undefined;
type AgentStatus = string;

export function roleLabel(role: Role): string {
  return isAdminRole(role) ? '管理员' : '普通用户';
}

export function avatarInitial(user?: User): string {
  const value = user?.name || user?.email || 'U';
  return value.trim().slice(0, 2).toUpperCase();
}

export function isAdminRole(role: Role): boolean {
  return role === 'admin' || role === 'owner';
}

export function statusLabel(status: AgentStatus): string {
  const labels: Record<string, string> = {
    draft: '草稿',
    pending_review: '待审核',
    published: '已上架',
    rejected: '已驳回',
  };
  return labels[status] || status || '草稿';
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

export function capabilityCheckLabel(name: string): string {
  const labels: Record<string, string> = { chat: 'chat', image: 'image' };
  return labels[name] || name;
}
