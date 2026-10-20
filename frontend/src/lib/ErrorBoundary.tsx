import { Component, type ErrorInfo, type ReactNode } from "react";
import { Icon } from "./Icon";
import { useT } from "./i18n";

function Fallback({ onReset }: { onReset: () => void }) {
  const t = useT();
  return (
    <div className="boundary" role="alert">
      <h2>
        <Icon name="triangle-alert" /> {t("boundary.title")}
      </h2>
      <p>{t("boundary.hint")}</p>
      <button className="icon-button" onClick={onReset}>
        <Icon name="rotate-ccw" />
        {t("boundary.retry")}
      </button>
    </div>
  );
}

/** Keeps one broken panel from blanking the whole workspace. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.error) return <Fallback onReset={() => this.setState({ error: null })} />;
    return this.props.children;
  }
}
