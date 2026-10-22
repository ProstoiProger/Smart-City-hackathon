import { useState } from "react";
import manifest from "./emoji-manifest.json";

type Entry = { file: string; animated: boolean };
const FILES = manifest as Record<string, Entry>;
const BASE = "/emoji/";

/** Noto emoji files of one emoji: a static SVG and, where Google drew one, an animation. */
export function emojiFiles(e: string): { still: string; anim?: string } | null {
  const m = FILES[e];
  if (!m) return null;
  return { still: BASE + m.file + ".svg", anim: m.animated ? BASE + m.file + ".webp" : undefined };
}

/** A Noto emoji (Google, CC BY 4.0 / Apache 2.0): still until its button or card is hovered,
 * then animated. The animation is fetched on the first hover only. Decorative: the text
 * next to it carries the meaning. */
export function Emo({ e, className }: { e: string; className?: string }) {
  const files = emojiFiles(e);
  const [ready, setReady] = useState(false);
  if (!files)
    return (
      <span className={"emo emo-text" + (className ? " " + className : "")} aria-hidden="true">
        {e}
      </span>
    );
  return (
    <span className={"emo" + (ready ? " ready" : "") + (className ? " " + className : "")} aria-hidden="true">
      <img className="emo-still" src={files.still} alt="" draggable={false} />
      {files.anim && <img className="emo-anim" src={files.anim} alt="" loading="lazy" draggable={false} onLoad={() => setReady(true)} />}
    </span>
  );
}
