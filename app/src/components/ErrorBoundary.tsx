import { Component, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw, RotateCcw } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error('[ErrorBoundary]', error.message, info.componentStack);
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-[var(--bg-base)]">
        <div className="max-w-md w-full text-center space-y-5">
          <div className="w-16 h-16 bg-[var(--accent-rose)]/10 rounded-full flex items-center justify-center mx-auto">
            <AlertTriangle className="w-8 h-8 text-[var(--accent-rose)]" />
          </div>

          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)] mb-2">
              Something went wrong
            </h1>
            <p className="text-sm text-[var(--text-secondary)]">
              An unexpected error occurred. Reload the page or try again — your data is safe.
            </p>
          </div>

          {this.state.error && (
            <pre className="text-xs font-mono text-left text-[var(--text-tertiary)] bg-[var(--bg-elevated)] border border-[var(--border-custom)] px-4 py-3 rounded-xl overflow-auto max-h-32 whitespace-pre-wrap break-all">
              {this.state.error.message}
            </pre>
          )}

          <div className="flex gap-3 justify-center">
            <button
              onClick={() => window.location.reload()}
              className="flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-blue)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity"
            >
              <RefreshCw className="w-4 h-4" />
              Reload Page
            </button>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="flex items-center gap-2 px-5 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-primary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors"
            >
              <RotateCcw className="w-4 h-4" />
              Try Again
            </button>
          </div>
        </div>
      </div>
    );
  }
}
