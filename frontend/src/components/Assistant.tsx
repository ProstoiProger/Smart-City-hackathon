import { useEffect, useRef, useState } from "react";
import { Icon } from "../lib/Icon";
import { useT } from "../lib/i18n";
import type { Walk } from "../useWalk";
import { Explanation } from "./Explanation";

const SUGGESTIONS = ["chat.s1", "chat.s2", "chat.s3"];

export function Assistant({ walk }: { walk: Walk }) {
  const t = useT();
  const { messages, miniRoute, setMiniRoute, ask } = walk.chat;
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [messages]);

  const send = (value: string) => {
    if (!value.trim() || walk.busy) return;
    setText("");
    ask(value);
  };

  return (
    <aside className="assistant" aria-label={t("nav.chat")}>
      <div className="assistant-head">
        <div className="assistant-title">
          <span aria-hidden="true">
            <Icon name="sparkles" />
          </span>
          <div>
            <h2>{t("nav.chat")}</h2>
            <p>{t("chat.subtitle")}</p>
          </div>
        </div>
      </div>
      <div className="conversation" aria-live="polite">
        {!messages.length && (
          <div className="chat-welcome">
            <h3>
              {t("chat.welcome1")}
              <br />
              {t("chat.welcome2")}
            </h3>
            <p>{t("chat.welcomeHint")}</p>
            <div className="suggestions">
              {SUGGESTIONS.map((key) => (
                <button key={key} onClick={() => send(t(key))}>
                  {t(key)}
                  <span aria-hidden="true">
                    <Icon name="arrow-up-right" />
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <article key={m.id} className={"message " + m.role}>
            <small>
              {m.role === "user" ? t("chat.you") : t("chat.assistant", { p: m.data?.provider_used || t("chat.searchProvider") })}
            </small>
            <p>{m.text}</p>
            {m.data?.warnings.map((w) => (
              <p className="warning" key={w}>
                {w}
              </p>
            ))}
            {m.data?.mini_route && (
              <div className="mini-route">
                <strong>
                  <Icon name="route" />{" "}
                  {t("route.title", {
                    n: m.data.mini_route.stops.length,
                    total: Math.round(m.data.mini_route.total_duration_min),
                    budget: m.data.mini_route.budget_minutes ?? m.data.minutes,
                  })}
                </strong>
                <small>{t("route.walk", { n: Math.round(m.data.mini_route.walk_duration_min ?? 0) })}</small>
                <button className="icon-button" onClick={() => walk.showPlan(m.data!.mini_route!)}>
                  <Icon name="map" />
                  {t("route.show")}
                </button>
              </div>
            )}
            {m.data?.items.map((p, i) => (
              <button key={p.poi_id} className="chat-place" onClick={() => walk.selectPlace(p)}>
                {m.data?.mini_route && (
                  <span className="route-meta">
                    {t("route.stop", {
                      order: i + 1,
                      at: m.data.mini_route.stops[i]?.arrival_offset_min ?? 0,
                      walk: Math.round(m.data.mini_route.legs[i]?.duration_min ?? 0),
                      visit: m.data.mini_route.stops[i]?.suggested_visit_duration_min ?? p.suggested_visit_duration_min,
                    })}
                  </span>
                )}
                <strong>{p.display_name}</strong>
                <Explanation p={p} />
                {p.warnings?.map((w) => (
                  <small key={w}>{w}</small>
                ))}
              </button>
            ))}
            {m.data && (
              <details className="trace">
                <summary>{t("chat.trace")}</summary>
                <ol>
                  {m.data.steps.map((s) => (
                    <li key={s.action}>
                      <strong>{s.action}</strong>
                      <span>{s.result}</span>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </article>
        ))}
        {walk.busy && (
          <p className="thinking" role="status">
            {t("chat.thinking")}
          </p>
        )}
        <div ref={end} />
      </div>
      <label className="check route-toggle" title={t("chat.miniRouteHint")}>
        <input type="checkbox" checked={miniRoute} onChange={(e) => setMiniRoute(e.target.checked)} />
        <Icon name="route" />
        {t("chat.miniRoute")}
      </label>
      <form
        className="chat-compose"
        onSubmit={(e) => {
          e.preventDefault();
          send(text);
        }}
      >
        <label className="sr-only" htmlFor="chat-input">
          {t("chat.ask")}
        </label>
        <textarea
          id="chat-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends, Shift+Enter keeps a new line.
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(text);
            }
          }}
          placeholder={t("chat.ask")}
          maxLength={1500}
          rows={2}
        />
        <button className="primary icon-button" disabled={walk.busy || !text.trim()} aria-label={t("chat.send")}>
          <Icon name="send-horizontal" />
        </button>
      </form>
      <p className="privacy">{t("chat.privacy")}</p>
    </aside>
  );
}
