import { useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { useT } from "../lib/i18n";

// Folded: the handle and the title stay visible.
const MIN = 96;
const STEP = 48;
// Room for the labels at the top of the map.
const TOP_GAP = 72;

function load(key: string): number | null {
  try {
    const value = Number(localStorage.getItem("sheet:" + key));
    return value >= MIN ? value : null;
  } catch {
    return null; // storage blocked: the sheet keeps its default height
  }
}

function save(key: string, height: number | null) {
  try {
    if (height == null) localStorage.removeItem("sheet:" + key);
    else localStorage.setItem("sheet:" + key, String(Math.round(height)));
  } catch {
    // the height is kept for this page only
  }
}

/** A map sheet the user can resize like a phone bottom sheet: drag the handle, tap it to
 * fold or unfold, or use the arrow keys on it. The height is remembered per `key`. */
export function useSheetSize(key: string) {
  const t = useT();
  const ref = useRef<HTMLElement>(null);
  const [height, setHeight] = useState<number | null>(() => load(key));
  const latest = useRef(height);
  const drag = useRef<{ y: number; h: number; moved: boolean } | null>(null);
  const dragged = useRef(false);
  const unfolded = useRef<number | null>(null);

  const max = () => {
    const parent = ref.current?.offsetParent as HTMLElement | null;
    return Math.max(MIN, (parent?.clientHeight ?? window.innerHeight) - TOP_GAP);
  };
  const clamp = (h: number) => Math.round(Math.min(max(), Math.max(MIN, h)));
  const measured = () => ref.current?.getBoundingClientRect().height ?? MIN;
  const set = (h: number | null, persist = true) => {
    latest.current = h;
    setHeight(h);
    if (persist) save(key, h);
  };
  const folded = height != null && height <= MIN + 1;

  const handle = (
    <button
      type="button"
      className="sheet-handle"
      aria-label={t("sheet.resize")}
      aria-expanded={!folded}
      onPointerDown={(e: PointerEvent<HTMLButtonElement>) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        drag.current = { y: e.clientY, h: measured(), moved: false };
      }}
      onPointerMove={(e: PointerEvent<HTMLButtonElement>) => {
        const d = drag.current;
        if (!d) return;
        const dy = d.y - e.clientY;
        if (Math.abs(dy) > 3) d.moved = true;
        if (d.moved) set(clamp(d.h + dy), false);
      }}
      onPointerUp={() => {
        dragged.current = !!drag.current?.moved;
        if (dragged.current) save(key, latest.current);
        drag.current = null;
      }}
      onPointerCancel={() => {
        drag.current = null;
      }}
      onClick={() => {
        // The click that ends a drag is not a tap.
        if (dragged.current) {
          dragged.current = false;
          return;
        }
        if (folded) set(unfolded.current);
        else {
          unfolded.current = height;
          set(MIN);
        }
      }}
      onKeyDown={(e: KeyboardEvent<HTMLButtonElement>) => {
        const next =
          e.key === "ArrowUp" ? measured() + STEP
          : e.key === "ArrowDown" ? measured() - STEP
          : e.key === "Home" ? MIN
          : e.key === "End" ? max()
          : null;
        if (next == null) return;
        e.preventDefault();
        set(clamp(next));
      }}
    >
      <span aria-hidden="true" />
    </button>
  );
  const style: CSSProperties | undefined =
    height != null ? { height, maxHeight: `calc(100% - ${TOP_GAP}px)` } : undefined;
  return { ref, style, handle, folded };
}
