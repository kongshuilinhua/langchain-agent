import React, { useState } from 'react';
import { X } from 'lucide-react';
import { api } from '../utils.js';

export function ResegmentModal({
  isOpen,
  onClose,
  kbId,
  doc,
  token,
  onResegmentSuccess,
  notify,
}) {
  const [parserMode, setParserMode] = useState('precise'); // 'precise' | 'fast'
  const [chunkStrategy, setChunkStrategy] = useState('hierarchy'); // 'auto' | 'custom' | 'hierarchy'
  const [hierarchyLevel, setHierarchyLevel] = useState(3);
  const [keepHierarchyInfo, setKeepHierarchyInfo] = useState(true);

  // Advanced settings (with defaults to match ResegmentRequest schema)
  const [delimiter, setDelimiter] = useState('##');
  const [maxChunkLen, setMaxChunkLen] = useState(1600);
  const [overlapPct, setOverlapPct] = useState(10);

  // States for preview & save
  const [previewing, setPreviewing] = useState(false);
  const [previewChunks, setPreviewChunks] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  // Trigger real-time chunks preview from backend
  async function handlePreview() {
    setPreviewing(true);
    setPreviewChunks([]);
    try {
      const payload = {
        parse_mode: parserMode,
        segment_mode: chunkStrategy, // 'auto' | 'custom' | 'hierarchy'
        delimiter: delimiter,
        max_chunk_len: Number(maxChunkLen),
        overlap_pct: Number(overlapPct),
        hierarchy_level: Number(hierarchyLevel),
        keep_hierarchy_info: keepHierarchyInfo,
      };

      const data = await api(`/api/knowledge-bases/${kbId}/documents/${doc.id}/preview`, {
        token,
        method: 'POST',
        body: payload,
      });

      setPreviewChunks(data.preview_items || []);
      notify?.(`生成了 ${data.chunks_count || 0} 个切片预览`);
    } catch (err) {
      console.error(err);
      notify?.('生成预览失败，请检查配置参数');
    } finally {
      setPreviewing(false);
    }
  }

  // Trigger confirming and saving
  async function handleConfirmSave() {
    setSubmitting(true);
    try {
      const payload = {
        parse_mode: parserMode,
        segment_mode: chunkStrategy, // 'auto' | 'custom' | 'hierarchy'
        delimiter: delimiter,
        max_chunk_len: Number(maxChunkLen),
        overlap_pct: Number(overlapPct),
        hierarchy_level: Number(hierarchyLevel),
        keep_hierarchy_info: keepHierarchyInfo,
      };

      await api(`/api/knowledge-bases/${kbId}/documents/${doc.id}/resegment`, {
        token,
        method: 'POST',
        body: payload,
      });

      notify?.('切片规则保存成功，已同步触发重新索引');
      onResegmentSuccess?.();
    } catch (err) {
      console.error(err);
      notify?.('重新切片失败，请重试');
    } finally {
      setSubmitting(false);
    }
  }

  if (!isOpen) return null;

  return (
    <div className="profile-dialog-backdrop resegment-modal-backdrop">
      <section
        className="resegment-sliding-panel"
        role="dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <button className="profile-dialog-close" type="button" title="关闭" onClick={onClose}>
          <X size={18} />
        </button>

        <header className="resegment-panel-heading">
          <h3>精准解析与层级调参</h3>
          <p>
            文档名称: <strong>{doc.title || doc.filename}</strong>
          </p>
        </header>

        <div className="resegment-panel-body">
          {/* Section 1: Parsing accuracy */}
          <div className="config-group">
            <label className="config-group-label">解析精度 (Parsing Accuracy)</label>
            <div className="segmented-switch">
              <button
                type="button"
                className={parserMode === 'precise' ? 'active' : ''}
                onClick={() => setParserMode('precise')}
              >
                精准解析
              </button>
              <button
                type="button"
                className={parserMode === 'fast' ? 'active' : ''}
                onClick={() => setParserMode('fast')}
              >
                快速解析
              </button>
            </div>
            <p className="config-help-text">
              {parserMode === 'precise'
                ? '使用高级文档排版解析器，支持深度抓取复杂的 PDF/Word 表格与标题层级。'
                : '使用经典的高速流式解析器，适用于简单、纯文本的超大型资料包。'}
            </p>
          </div>

          {/* Section 2: Segment Strategy */}
          <div className="config-group">
            <label className="config-group-label">分段策略 (Chunking Strategy)</label>
            <div className="strategy-cards-grid">
              <div
                className={`strategy-card ${chunkStrategy === 'auto' ? 'active' : ''}`}
                onClick={() => setChunkStrategy('auto')}
              >
                <strong>自动分段 (Auto)</strong>
                <small>智能推荐的滑动窗口大小进行快速提取，简便高效。</small>
              </div>
              <div
                className={`strategy-card ${chunkStrategy === 'custom' ? 'active' : ''}`}
                onClick={() => setChunkStrategy('custom')}
              >
                <strong>自定义 (Custom)</strong>
                <small>手动指定单分块字数上限与重合度，精细化管理。</small>
              </div>
              <div
                className={`strategy-card ${chunkStrategy === 'hierarchy' ? 'active' : ''}`}
                onClick={() => setChunkStrategy('hierarchy')}
              >
                <strong>🌳 层级分段 (Hierarchy)</strong>
                <small>精准遵循 Markdown/PDF 的多级标题，维护上下文血统树。</small>
              </div>
            </div>
          </div>

          {/* Conditional settings for Hierarchy Strategy */}
          {chunkStrategy === 'hierarchy' && (
            <div className="conditional-group animate-slide-down">
              <div className="config-group inline-flex">
                <label className="config-group-label">
                  分段层级
                  <div className="tooltip-trigger">
                    <span className="tooltip-icon">?</span>
                    <div className="tooltip-box">
                      <strong>🌳 层级标题匹配示意图:</strong>
                      <pre>
{`├── H1: 一级标题 (例如: 1. 介绍)
│   ├── H2: 二级标题 (例如: 1.1 背景)
│   └── H2: 二级标题 (例如: 1.2 目标)
└── H1: 一级标题 (例如: 2. 架构)`}
                      </pre>
                      <small>根据 H1 到 H5 的标签自动切片，保持结构连贯。</small>
                    </div>
                  </div>
                </label>
                <input
                  type="number"
                  min="1"
                  max="5"
                  value={hierarchyLevel}
                  onChange={(e) => setHierarchyLevel(Math.max(1, Math.min(5, Number(e.target.value))))}
                  style={{ width: '80px', display: 'inline-block' }}
                />
              </div>

              <div className="config-group">
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={keepHierarchyInfo}
                    onChange={(e) => setKeepHierarchyInfo(e.target.checked)}
                  />
                  <span>检索切片保留层级信息</span>
                </label>
                <p className="config-help-text">
                  开启后，切片将带有类似 {`🌳 1.介绍 > 1.1背景`} 的上下文导航路径，极大提高召回准确率。
                </p>
              </div>
            </div>
          )}

          {/* Conditional settings for Custom Strategy */}
          {chunkStrategy === 'custom' && (
            <div className="conditional-group animate-slide-down">
              <div className="config-row-two-col">
                <div className="config-group">
                  <label className="config-group-label">分块长度上限</label>
                  <input
                    type="number"
                    min="100"
                    max="10000"
                    value={maxChunkLen}
                    onChange={(e) => setMaxChunkLen(Number(e.target.value))}
                  />
                </div>
                <div className="config-group">
                  <label className="config-group-label">重合度百分比 (%)</label>
                  <input
                    type="number"
                    min="0"
                    max="50"
                    value={overlapPct}
                    onChange={(e) => setOverlapPct(Number(e.target.value))}
                  />
                </div>
              </div>
              <div className="config-group">
                <label className="config-group-label">分隔标识符</label>
                <input
                  type="text"
                  value={delimiter}
                  onChange={(e) => setDelimiter(e.target.value)}
                  placeholder="##"
                />
              </div>
            </div>
          )}

          {/* Section 3: Action & Real-time Preview Area */}
          <div className="resegment-actions">
            <button
              className="btn-preview-chunks"
              type="button"
              disabled={previewing}
              onClick={handlePreview}
            >
              {previewing ? '生成预览中...' : (
                chunkStrategy === 'hierarchy' ? '🔍 预览层级分段' :
                chunkStrategy === 'custom' ? '🔍 预览自定义分段' :
                '🔍 预览自动分段'
              )}
            </button>
          </div>

          <div className="preview-results-area">
            <h5>预览分片流 ({previewChunks.length} 个)</h5>
            <div className="preview-chunks-scroll">
              {previewing ? (
                <div className="loading-preview">
                  <span className="spinner"></span>分析文档结构并计算层级路径中...
                </div>
              ) : (
                previewChunks.map((chunk, idx) => (
                  <div key={idx} className="preview-chunk-item-card">
                    <div className="preview-chunk-header">
                      <span className="idx-badge"># {chunk.chunk_index ?? idx}</span>
                      {chunk.hierarchy_path && (
                        <span className="path-badge">🌳 {chunk.hierarchy_path}</span>
                      )}
                    </div>
                    <div className="preview-chunk-text">{chunk.text}</div>
                  </div>
                ))
              )}
              {!previewing && previewChunks.length === 0 && (
                <p className="muted empty-preview-placeholder">
                  暂无预览。点击上方按钮可根据当前策略在内存中模拟切片结果。
                </p>
              )}
            </div>
          </div>
        </div>

        <footer className="resegment-panel-footer">
          <button type="button" onClick={onClose} disabled={submitting}>
            取消
          </button>
          <button
            className="primary-model-action btn-confirm-save"
            type="button"
            disabled={submitting}
            onClick={handleConfirmSave}
          >
            {submitting ? '同步提交并构建向量中...' : '💾 确认并保存索引'}
          </button>
        </footer>
      </section>
    </div>
  );
}
