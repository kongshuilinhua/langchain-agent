import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ThumbsUp, ThumbsDown, FileText, Search } from 'lucide-react';

export function MessageList({ messages, feedbackByMessage = {}, submitFeedback = () => {}, avatar = 'AI' }) {
  return (
    <>
      {messages.map((message, index) => (
        <div key={`${message.role}-${index}-${message.id || ''}`} className={`message ${message.role}`}>
          <span>{message.role === 'user' ? '我' : avatar}</span>
          <div className="message-body">
            {message.role === 'assistant' ? (
              <div className={message.error ? 'message-error' : ''}>
                {message.pending && !message.content ? <p className="message-pending">思考中...</p> : <MarkdownContent content={message.content || ''} />}
              </div>
            ) : <p>{message.content}</p>}
            {message.role === 'assistant' && message.id && (
              <div className="feedback-actions">
                <button
                  type="button"
                  className={feedbackByMessage[message.id] === 'positive' ? 'selected' : ''}
                  title="回答有帮助"
                  onClick={() => submitFeedback(message.id, 'positive').catch((err) => console.error(err))}
                >
                  <ThumbsUp size={14} />
                </button>
                <button
                  type="button"
                  className={feedbackByMessage[message.id] === 'negative' ? 'selected' : ''}
                  title="回答不理想"
                  onClick={() => submitFeedback(message.id, 'negative').catch((err) => console.error(err))}
                >
                  <ThumbsDown size={14} />
                </button>
              </div>
            )}
            {message.role === 'assistant' && (message.sources || []).length > 0 && (
              <MessageSources sources={message.sources} />
            )}
          </div>
        </div>
      ))}
    </>
  );
}

export function MarkdownContent({ content }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ inline, className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '');
            const code = String(children || '').replace(/\n$/, '');
            if (inline) {
              return <code className={className} {...props}>{children}</code>;
            }
            return <CodeBlock language={match?.[1] || 'text'} code={code} />;
          },
          a({ children, href, ...props }) {
            return <a href={href} target="_blank" rel="noreferrer" {...props}>{children}</a>;
          },
        }}
      >
        {content || ''}
      </ReactMarkdown>
    </div>
  );
}

export function CodeBlock({ language, code }) {
  async function copyCode() {
    await navigator.clipboard?.writeText(code);
  }
  return (
    <div className="code-block">
      <div className="code-header">
        <span>{language || 'text'}</span>
        <button type="button" onClick={copyCode}>复制</button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

export function MessageSources({ sources }) {
  const visible = sources.slice(0, 4);
  const hiddenCount = Math.max(0, sources.length - visible.length);
  return (
    <details className="message-sources">
      <summary>引用来源 <span>{sources.length}</span></summary>
      <div className="message-source-list">
        {visible.map((source) => <SourceChip key={source.chunk_id || `${source.title}-${source.snippet}`} source={source} />)}
        {hiddenCount > 0 && <span className="source-more">还有 {hiddenCount} 个</span>}
      </div>
    </details>
  );
}

export function SourceChip({ source }) {
  const meta = [
    source.page ? `p.${source.page}` : '',
    source.section || '',
    source.retrieval_channel || '',
    Number.isFinite(Number(source.score)) ? Number(source.score).toFixed(2) : '',
  ].filter(Boolean).join(' · ');
  const content = (
    <>
      {source.url ? <Search size={14} /> : <FileText size={14} />}
      <strong>{source.title || source.source_id || 'source'}</strong>
      {meta && <small>{meta}</small>}
    </>
  );
  return source.url
    ? <a className="source-link" title={source.snippet || source.title} href={source.url} target="_blank" rel="noreferrer">{content}</a>
    : <span title={source.snippet || source.title}>{content}</span>;
}
