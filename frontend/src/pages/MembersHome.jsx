import React from 'react';
import { UserAvatar } from '../components/AgentAvatar.jsx';
import { roleLabel } from '../utils.js';

export function MembersHome({ members }) {
  return (
    <div className="content-page">
      <header className="page-heading">
        <div>
          <h1>成员</h1>
          <p>管理员只查看成员列表。最终版不提供邀请用户和邀请列表页面。</p>
        </div>
      </header>
      <div className="member-list">
        {members.map((member) => (
          <article className="member-card" key={member.id}>
            <UserAvatar user={member.user} className="account-avatar" />
            <div>
              <h3>{member.user?.name || member.user?.email}</h3>
              <p>{member.user?.email}</p>
            </div>
            <span className="status-pill">{roleLabel(member.role)}</span>
          </article>
        ))}
        {members.length === 0 && <p className="empty-state">暂无成员。</p>}
      </div>
    </div>
  );
}