import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { ThumbsUp, ThumbsDown, FileText, Search, ImagePlus } from 'lucide-react';
import { AgentAvatar } from './AgentAvatar.jsx';

export function MessageList({ messages, feedbackByMessage = {}, submitFeedback = () => {}, avatar = 'AI' }) {
  return (
    <>
      {messages.map((message, index) => (
        <div key={`${message.role}-${index}-${message.id || ''}`} className={`message ${message.role}`}>
          {message.role === 'user' ? (
            <span>我</span>
          ) : (
            <AgentAvatar value={avatar} />
          )}
          <div className="message-body">
            {message.role === 'assistant' ? (
              <div className={message.error ? 'message-error' : ''}>
                {message.pending && !message.content ? <p className="message-pending">思考中...</p> : <MarkdownContent content={message.content || ''} />}
              </div>
            ) : <>
              <p>{message.content}</p>
              {message.attachments?.length > 0 && (
                <div className="message-attachments">
                  {message.attachments.map((att) => (
                    <div key={att.id} className={att.kind === 'image' || att.type === 'image' ? 'message-attachment-image' : 'message-attachment-document'}>
                      {att.kind === 'image' || att.type === 'image' ? (
                        <img src={att.data_url || att.preview_url} alt={att.filename} />
                      ) : (
                        <span className="message-attachment-file"><FileText size={14} />{att.filename}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>}
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
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
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
  // 根据文档ID或标题进行去重，避免对同一文档的多个分片重复渲染完全相同的卡片
  const uniqueSources = [];
  const seenDocs = new Set();
  
  for (const src of sources) {
    const docKey = src.document_id || src.title || src.source_id;
    if (docKey) {
      if (!seenDocs.has(docKey)) {
        seenDocs.add(docKey);
        uniqueSources.push(src);
      }
    } else {
      uniqueSources.push(src);
    }
  }

  const visible = uniqueSources.slice(0, 4);
  const hiddenCount = Math.max(0, uniqueSources.length - visible.length);
  
  return (
    <details className="message-sources">
      <summary>引用来源 <span>{uniqueSources.length}</span></summary>
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
