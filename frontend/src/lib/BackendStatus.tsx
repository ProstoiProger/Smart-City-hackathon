import { useEffect, useState } from "react";
import { request } from "../api";
import { Icon } from "./Icon";
import { useT } from "./i18n";

const POLL_MS = 30000;

/** Banner shown while the API does not answer /api/health. */
export function BackendStatus() {
  const t = useT();
  const [down, setDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const check = () =>
      request<{ ok: boolean }>("health")
        .then((r) => alive && setDown(!r.ok))
        .catch(() => alive && setDown(true));
    check();
    const timer = window.setInterval(check, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!down) return null;
  return (
    <div className="backend-down" role="alert">
      <Icon name="wifi-off" />
      <span>{t("health.down")}</span>
    </div>
  );
}
