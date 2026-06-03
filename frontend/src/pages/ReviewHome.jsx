import React from 'react';
import { AgentAvatar } from '../components/AgentAvatar.jsx';

export function ReviewHome({ approveReview, items, rejectReview }) {
  return (
    <div className="content-page">
      <header className="page-heading">
        <div>
          <h1>发布审核</h1>
          <p>普通用户提交发布后，管理员在这里审核；通过后会进入市场。</p>
        </div>
      </header>
      <div className="review-list">
        {items.map((agent) => (
          <article className="review-card" key={agent.id}>
            <AgentAvatar value={agent.avatar} className="agent-avatar" />
            <div>
              <h3>{agent.name}</h3>
              <p>{agent.description || '暂无简介'}</p>
              <small>提交版本 {agent.submitted_version || '-'} · {agent.submitted_at || '刚刚'}</small>
            </div>
            <div className="review-actions">
              <button type="button" onClick={() => rejectReview(agent.id).catch((err) => console.error(err))}>驳回</button>
              <button className="primary" type="button" onClick={() => approveReview(agent.id).catch((err) => console.error(err))}>通过</button>
            </div>
          </article>
        ))}
        {items.length === 0 && <p className="empty-state">暂无待审核智能体。</p>}
      </div>
    </div>
  );
}