import React from 'react';

/**
 * React Error Boundary —— 防止子组件渲染崩溃导致整个应用白屏。
 *
 * 🎯 用法：
 *   <ErrorBoundary>
 *     <ChatPage />
 *   </ErrorBoundary>
 *
 * 当 ChatPage 内部任何组件抛出未捕获的渲染异常时，
 * ErrorBoundary 会捕获并显示友好的错误提示，而非白屏。
 */
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '200px',
          padding: '40px 20px',
          textAlign: 'center',
          color: '#666',
        }}>
          <h2 style={{ margin: '0 0 12px', fontSize: '18px' }}>页面加载异常</h2>
          <p style={{ margin: '0 0 20px', fontSize: '14px', maxWidth: '400px' }}>
            {this.state.error?.message || '发生了未知错误，请尝试刷新页面。'}
          </p>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={this.handleReset}
              style={{
                padding: '8px 20px',
                borderRadius: '6px',
                border: '1px solid #ddd',
                background: '#fff',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              重试
            </button>
            <button
              onClick={this.handleReload}
              style={{
                padding: '8px 20px',
                borderRadius: '6px',
                border: 'none',
                background: '#4f46e5',
                color: '#fff',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              刷新页面
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
