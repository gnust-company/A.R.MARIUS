import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * Catch render-time exceptions so a single page's crash doesn't blank the whole app.
 *
 * Without this, any uncaught throw in a route component (e.g. accessing a field on a
 * not-yet-hydrated entity) unmounts the root and leaves a blank screen — the symptom in
 * #56 (Roster crashed on `project.seats.find` before `hydrateProject` landed). Pages
 * should still guard their own loading states; this is the safety net for the cases they
 * miss. Renders an inline "something went wrong" panel with a reload action.
 */
interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface the stack in the console so a developer reproducing the blank screen has
    // the same trail they'd get without the boundary.
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  handleReload = () => {
    this.setState({ error: null });
    // A hard reload is the simplest reliable reset: it re-runs boot + hydration and
    // clears any transient bad state that contributed to the crash.
    window.location.reload();
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return <ErrorFallback message={error.message} onReload={this.handleReload} />;
  }
}

/** Stateless fallback so it can be reused (e.g. by a route-level errorElement). */
export function ErrorFallback({ message, onReload }: { message: string; onReload: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] px-6 text-center">
      <AlertTriangle className="w-12 h-12 text-[#B84A32] mb-4" />
      <h2 className="font-display text-display-md text-ink mb-2">
        {t('common.somethingWentWrong')}
      </h2>
      <p className="font-body text-body-md text-ink-light mb-1 max-w-md">
        {t('common.errorBoundaryHint')}
      </p>
      {message && (
        <p className="font-mono text-mono-sm text-ink-muted mb-6 max-w-xl break-words">
          {message}
        </p>
      )}
      <button
        onClick={onReload}
        className="inline-flex items-center gap-2 bg-[#C25E3A] hover:bg-[#D97B5A] text-white font-body font-medium text-body-md px-4 py-2.5 rounded-md transition-colors"
      >
        <RotateCcw className="w-4 h-4" />
        {t('common.reload')}
      </button>
    </div>
  );
}
