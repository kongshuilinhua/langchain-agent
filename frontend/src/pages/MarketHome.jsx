import React from 'react';
import { AgentAvatar } from '../components/AgentAvatar.jsx';

export function MarketHome({ agents, copyMarketAgent }) {
  return (
    <div className="content-page">
      <header className="page-heading">
        <div>
          <h1>智能体市场</h1>
          <p>审核通过的智能体会显示在这里，其他用户可以复制成自己的草稿后继续配置。</p>
        </div>
      </header>
      <div className="agent-grid">
        {agents.map((agent) => (
          <article className="agent-card" key={agent.id}>
            <AgentAvatar value={agent.avatar} />
            <h3>{agent.name}</h3>
            <p>{agent.description || '暂无简介'}</p>
            <small className="status-pill published">版本 {agent.version || '-'}</small>
            <div>
              <button type="button" onClick={() => copyMarketAgent(agent.id).catch((err) => console.error(err))}>复制使用</button>
            </div>
          </article>
        ))}
        {agents.length === 0 && <p className="empty-state">市场里还没有审核通过的智能体。</p>}
      </div>
    </div>
  );
}