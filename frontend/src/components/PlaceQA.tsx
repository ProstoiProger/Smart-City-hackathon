import { useEffect, useRef, useState } from "react";
import { request, type PlaceAnswer, type Poi } from "../api";
import { useT } from "../lib/i18n";

const SUGGESTIONS = ["hours", "price", "power_outlets", "wifi", "quiet", "accessibility", "kids", "events"];

/** Questions about one place; answers come from its data and reviews, each with its evidence. */
export function PlaceQA({ p, when }: { p: Poi; when: string }) {
  const t = useT();
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const [result, setResult] = useState<PlaceAnswer | null>(null);
  const latest = useRef(0);

  useEffect(() => {
    latest.current++;
    setText("");
    setResult(null);
    setState("idle");
  }, [p.poi_id]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (q.length < 2 || state === "busy") return;
    const mine = ++latest.current;
    setState("busy");
    try {
      const data = await request<PlaceAnswer>(`pois/${encodeURIComponent(p.poi_id)}/ask`, {
        question: q,
        when: when || null,
      });
      if (mine !== latest.current) return;
      setResult(data);
      setState("idle");
    } catch {
      if (mine === latest.current) setState("error");
    }
  };

  return (
    <details open className="place-qa">
      <summary>{t("qa.title")}</summary>
      <ul className="qa-suggestions">
        {SUGGESTIONS.map((key) => (
          <li key={key}>
            <button
              type="button"
              disabled={state === "busy"}
              onClick={() => {
                setText(t("qa.s." + key));
                ask(t("qa.s." + key));
              }}
            >
              {t("qa.s." + key)}
            </button>
          </li>
        ))}
      </ul>
      <form
        className="qa-form"
        onSubmit={(e) => {
          e.preventDefault();
          ask(text);
        }}
      >
        <label className="sr-only" htmlFor="qa-input">
          {t("qa.title")}
        </label>
        <input
          id="qa-input"
          value={text}
          maxLength={300}
          placeholder={t("qa.placeholder")}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="primary" disabled={state === "busy" || text.trim().length < 2}>
          {t("qa.ask")}
        </button>
      </form>
      <div aria-live="polite">
        {state === "busy" && <small role="status">{t("qa.asking")}</small>}
        {state === "error" && (
          <p className="warning" role="alert">
            {t("qa.error")}
          </p>
        )}
        {result && state !== "error" && (
          <ul className="qa-answers">
            {result.answers.map((a) => (
              <li key={a.topic} className={"qa-answer " + a.certainty}>
                <span className={"pill cert-" + a.certainty}>{t("qa.cert." + a.certainty)}</span>
                <p>{a.answer}</p>
                {!!a.evidence.length && (
                  <small>
                    {t("qa.evidence")}: {a.evidence.join(" · ")}
                  </small>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      <small>{t("qa.hint")}</small>
    </details>
  );
}
