import React from 'react';

export function AgentAvatar({ value, className = 'agent-avatar' }) {
  const avatar = String(value || 'AI').trim() || 'AI';
  if (avatar.startsWith('data:image/')) {
    return (
      <span className={`${className} has-image`}>
        <img src={avatar} alt="智能体图标" />
      </span>
    );
  }
  return <span className={className}>{avatar.slice(0, 4)}</span>;
}

export function UserAvatar({ user, className = 'account-avatar' }) {
  if (user?.avatar_url) {
    return (
      <span className={`${className} has-image`}>
        <img src={user.avatar_url} alt={`${user.name || user.email || '用户'}头像`} />
      </span>
    );
  }
  const initial = String(user?.name || user?.email || 'U').trim().slice(0, 1).toUpperCase();
  return <span className={className}>{initial}</span>;
}
