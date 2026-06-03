import React, { useEffect } from 'react';
import { Trash2 } from 'lucide-react';

/**
 * 确认对话框组件。
 * 从 main.jsx 内联提取 —— 支持 Enter/Escape 键盘快捷操作。
 */
export function ConfirmDialog({
  cancelLabel = '取消',
  confirmLabel = '删除',
  detail = '',
  message,
  onCancel,
  onConfirm,
  title,
  tone = 'danger',
}) {
  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onCancel();
      if (event.key === 'Enter') onConfirm();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onCancel, onConfirm]);

  return (
    <div className="confirm-dialog-backdrop" role="presentation">
      <section
        className={`confirm-dialog ${tone}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <span className="confirm-dialog-icon"><Trash2 size={18} /></span>
          <div>
            <h2 id="confirm-dialog-title">{title || '确认删除'}</h2>
            <p>{message}</p>
          </div>
        </header>
        {detail && <p className="confirm-dialog-detail">{detail}</p>}
        <footer>
          <button type="button" onClick={onCancel}>{cancelLabel}</button>
          <button className="danger" type="button" autoFocus onClick={onConfirm}>{confirmLabel}</button>
        </footer>
      </section>
    </div>
  );
}
