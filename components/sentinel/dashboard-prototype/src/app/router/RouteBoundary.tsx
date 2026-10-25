import {
  Component,
  lazy,
  Suspense,
  useMemo,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { ActionButton } from "../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../shared/ui/FeedbackPanel";

/** Loader contract owned by routing, not by feature state or the HTTP gateway. */
export type RouteLoader<Props extends object> = () => Promise<{
  readonly default: ComponentType<Props>;
}>;

interface ErrorBoundaryProps {
  readonly children: ReactNode;
  readonly fallback: ReactNode;
}

/** React's imperative error-capture boundary; no business rules or raw error details. */
class PageErrorBoundary extends Component<ErrorBoundaryProps, { readonly failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * Isolate page render/chunk failures without unmounting shell or providers.
 * Retry creates a new React.lazy identity (a rejected lazy is otherwise cached).
 * A new route/resetKey also clears the error boundary. No mutation is replayed.
 */
export function RouteBoundary<Props extends object>({
  loader,
  pageProps,
  resetKey,
  onHome,
  onReload = () => window.location.reload(),
}: {
  readonly loader: RouteLoader<Props>;
  readonly pageProps: Props;
  readonly resetKey: string;
  readonly onHome: () => void;
  /** Explicit full navigation for native module-cache/network failures; never automatic. */
  readonly onReload?: () => void;
}) {
  const { t } = useTranslation();
  const [attempt, setAttempt] = useState(0);
  // This owner is OUTSIDE Suspense: React discards memo state when an initial
  // mount suspends. Creating lazy inside the suspended child causes an endless
  // fresh-promise loop even after the chunk has been downloaded.
  const entry = useMemo(
    () => ({ Page: lazy(loader), key: `${resetKey}:${attempt}` }),
    [loader, resetKey, attempt],
  );
  const { Page } = entry;
  const fallback = (
    <section data-route-state="failed">
      <FeedbackPanel
        tone="error"
        copy={{ title: t("shell.route.failed"), description: t("shell.route.failureHelp") }}
        actions={
          <>
            <ActionButton onClick={() => setAttempt((value) => value + 1)}>
              {t("shell.route.retry")}
            </ActionButton>
            <ActionButton
              onClick={() => {
                setAttempt((value) => value + 1);
                onHome();
              }}
            >
              {t("shell.route.home")}
            </ActionButton>
            <ActionButton onClick={onReload}>{t("shell.route.reload")}</ActionButton>
          </>
        }
      />
    </section>
  );
  return (
    <PageErrorBoundary key={entry.key} fallback={fallback}>
      <Suspense
        fallback={
          <section data-route-state="loading">
            <FeedbackPanel isBusy copy={{ title: t("shell.route.loading"), description: "" }} />
          </section>
        }
      >
        <Page {...pageProps} />
      </Suspense>
    </PageErrorBoundary>
  );
}
