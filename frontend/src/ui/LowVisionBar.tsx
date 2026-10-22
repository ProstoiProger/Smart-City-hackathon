import { useEffect, useState } from "react";
import { Icon } from "../lib/Icon";
import { useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { canSpeak, speak, stopSpeaking } from "../lib/voice";

/** Settings of the low-vision version, on top of the panel while it is on: one compact row
 * (text size, colours, read aloud) and the rest behind "Ещё". */
export function LowVisionBar() {
  const t = useT();
  const { lowVision: lv, setLowVision, lang } = usePrefs();
  const [reading, setReading] = useState(false);
  const [more, setMore] = useState(false);
  useEffect(() => () => stopSpeaking(), []);

  // Reads the open screen aloud: headings, places, times and notes as they are shown.
  const readScreen = () => {
    if (reading) {
      stopSpeaking();
      setReading(false);
      return;
    }
    const screen = document.querySelector<HTMLElement>(".panel-body .screen-anim");
    const text = (screen?.innerText ?? "")
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 1)
      .join(". ")
      .slice(0, 1500);
    if (!text) return;
    setReading(true);
    speak(text, lang, () => setReading(false));
  };

  return (
    <section className="lv-bar" role="region" aria-label={t("lv.settings")}>
      <div className="lv-row">
        <div className="lv-group" role="radiogroup" aria-label={t("lv.size")}>
          {([1, 2, 3] as const).map((n) => (
            <button key={n} role="radio" aria-checked={lv.size === n} className={"lv-size s" + n} onClick={() => setLowVision({ size: n })} aria-label={t("lv.size" + n)} title={t("lv.size" + n)}>
              A{"+".repeat(n - 1)}
            </button>
          ))}
        </div>
        <div className="lv-group" role="radiogroup" aria-label={t("lv.colors")}>
          <button role="radio" aria-checked={lv.scheme === "dark"} className="lv-swatch dark" onClick={() => setLowVision({ scheme: "dark" })} aria-label={t("lv.dark")} title={t("lv.dark")}>
            Aa
          </button>
          <button role="radio" aria-checked={lv.scheme === "light"} className="lv-swatch light" onClick={() => setLowVision({ scheme: "light" })} aria-label={t("lv.light")} title={t("lv.light")}>
            Aa
          </button>
        </div>
        {canSpeak() && (
          <button className="lv-toggle icon" aria-pressed={reading} onClick={readScreen} aria-label={t(reading ? "lv.stopReading" : "lv.read")} title={t(reading ? "lv.stopReading" : "lv.read")}>
            <Icon name={reading ? "square" : "volume-2"} />
          </button>
        )}
        <button className="lv-toggle icon" aria-expanded={more} aria-controls="lv-more" onClick={() => setMore(!more)} aria-label={t("lv.more")} title={t("lv.more")}>
          <Icon name="sliders-horizontal" />
        </button>
      </div>
      {more && (
        <div className="lv-row wrap" id="lv-more">
          <button className="lv-toggle" aria-pressed={!lv.images} onClick={() => setLowVision({ images: !lv.images })}>
            <Icon name="image" /> {t("lv.noImages")}
          </button>
          <button className="lv-toggle" aria-pressed={lv.spacing} onClick={() => setLowVision({ spacing: !lv.spacing })}>
            <Icon name="type" /> {t("lv.spacing")}
          </button>
          <button className="lv-toggle exit" onClick={() => setLowVision({ on: false })}>
            <Icon name="x" /> {t("lv.exit")}
          </button>
        </div>
      )}
    </section>
  );
}
