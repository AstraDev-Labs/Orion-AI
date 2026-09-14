import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Orion UI crashed:', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="w-screen h-screen flex items-center justify-center bg-bg text-text">
        <div className="max-w-md text-center px-6">
          <div className="text-danger text-sm font-medium mb-2">Something went wrong</div>
          <p className="text-text-muted text-sm mb-6">
            {this.state.error.message || 'The interface hit an unexpected error.'}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-hover transition-colors"
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
