import { useEffect, useRef, useState } from "react";
import type { Provider } from "../api";
import { Icon } from "../lib/Icon";
import { useT } from "../lib/i18n";
import type { Walk } from "../useWalk";
import { Explanation } from "./Explanation";

const SUGGESTIONS = ["chat.s1", "chat.s2", "chat.s3"];

export function Assistant({ walk }: { walk: Walk }) {
  const t = useT();
  const { messages, provider, setProvider, ask } = walk.chat;
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
        <label className="sr-only" htmlFor="provider">
          {t("chat.model")}
        </label>
        <select id="provider" value={provider} onChange={(e) => setProvider(e.target.value as Provider)}>
          <option value="offline">{t("chat.offline")}</option>
          <option value="gemini">Gemini</option>
        </select>
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
            {m.data?.items.map((p) => (
              <button key={p.poi_id} className="chat-place" onClick={() => walk.selectPlace(p)}>
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
