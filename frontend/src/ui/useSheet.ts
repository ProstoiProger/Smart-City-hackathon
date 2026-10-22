import { useEffect, useRef, useState, type PointerEvent, type RefObject } from "react";

export type Snap = "peek" | "half" | "full";

// Phones in portrait get a bottom sheet; phones in landscape and desktops a side panel
// (the same breakpoints as ui.css).
const NARROW = "(max-width: 859px)";
const SIDEWAYS = "(max-width: 1000px) and (orientation: landscape) and (max-height: 520px)";
const ORDER: Snap[] = ["peek", "half", "full"];
// A flick faster than this (px/ms) goes to the next snap whatever the distance.
const FLICK = 0.45;

const isSheet = () => matchMedia(NARROW).matches && !matchMedia(SIDEWAYS).matches;

/** The phone bottom sheet: three heights (peek shows the header and the tabs, half the
 * content next to the map, full the whole screen), dragged by the grip or the header,
 * and opened in full while the keyboard is up. */
export function useSheet(panel: RefObject<HTMLElement | null>) {
  const [snap, setSnap] = useState<Snap>("half");
  const [sheet, setSheet] = useState(isSheet);
  const drag = useRef<{ y: number; h: number; t: number; lastY: number; lastT: number; moved: boolean; grip: boolean } | null>(null);
  // A tap on the grip handled here; the click that may follow it is ignored.
  const tapped = useRef(0);

  const heights = (): Record<Snap, number> => {
    const el = panel.current;
    const vh = window.visualViewport?.height ?? window.innerHeight;
    const head = el?.querySelector<HTMLElement>(".panel-head")?.offsetHeight ?? 64;
    const tabs = el?.querySelector<HTMLElement>(".tabbar")?.offsetHeight ?? 72;
    const peek = head + tabs;
    return { peek, half: Math.max(peek + 120, Math.min(vh * 0.58, 600)), full: Math.max(peek + 200, vh - 48) };
  };

  // The sheet's height follows the snap, the screen size and the on-screen keyboard.
  useEffect(() => {
    const apply = () => {
      const now = isSheet();
      setSheet(now);
      const el = panel.current;
      if (!el || drag.current) return;
      el.style.height = now ? `${Math.round(heights()[snap])}px` : "";
    };
    apply();
    const queries = [matchMedia(NARROW), matchMedia(SIDEWAYS)];
    queries.forEach((q) => q.addEventListener("change", apply));
    window.addEventListener("resize", apply);
    window.visualViewport?.addEventListener("resize", apply);
    return () => {
      queries.forEach((q) => q.removeEventListener("change", apply));
      window.removeEventListener("resize", apply);
      window.visualViewport?.removeEventListener("resize", apply);
    };
    // heights() reads the DOM at the time of the event.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap]);

  const onPointerDown = (e: PointerEvent<HTMLElement>) => {
    if (!sheet || !panel.current) return;
    const target = e.target as HTMLElement;
    // Language buttons and the logo link keep their taps; the grip and the bare header drag.
    if (target.closest("a, input, select, textarea, button:not(.sheet-grip)")) return;
    const now = performance.now();
    drag.current = {
      y: e.clientY,
      h: panel.current.getBoundingClientRect().height,
      t: now,
      lastY: e.clientY,
      lastT: now,
      moved: false,
      grip: !!target.closest(".sheet-grip"),
    };
    // The grip sits at the very top: the first move upwards already leaves it, so the
    // header keeps the pointer from the start.
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: PointerEvent<HTMLElement>) => {
    const d = drag.current;
    const el = panel.current;
    if (!d || !el) return;
    const dy = d.y - e.clientY;
    if (!d.moved && Math.abs(dy) < 6) return;
    d.moved = true;
    const h = heights();
    el.classList.add("dragging");
    el.style.height = `${Math.round(Math.min(h.full, Math.max(h.peek, d.h + dy)))}px`;
    d.lastY = e.clientY;
    d.lastT = performance.now();
  };

  const finish = (e: PointerEvent<HTMLElement>) => {
    const d = drag.current;
    const el = panel.current;
    drag.current = null;
    if (!d || !el) return;
    el.classList.remove("dragging");
    if (!d.moved) {
      el.style.height = `${Math.round(heights()[snap])}px`;
      if (d.grip) {
        tapped.current = performance.now();
        setSnap(snap === "peek" ? "half" : "peek");
      }
      return;
    }
    // Speed of the last stretch of the drag decides a flick; otherwise the nearest height wins.
    const v = (d.lastY - e.clientY) / Math.max(1, performance.now() - d.lastT) || (d.y - e.clientY) / Math.max(1, performance.now() - d.t);
    const h = heights();
    const current = el.getBoundingClientRect().height;
    let next: Snap = ORDER.reduce((best, s) => (Math.abs(h[s] - current) < Math.abs(h[best] - current) ? s : best), "half" as Snap);
    if (Math.abs(v) > FLICK) {
      // A flick moves at least one step its way, and as far as the finger went.
      const from = ORDER.indexOf(snap);
      const near = ORDER.indexOf(next);
      next = v > 0 ? ORDER[Math.min(2, Math.max(near, from + 1))] : ORDER[Math.max(0, Math.min(near, from - 1))];
    }
    el.style.height = `${Math.round(h[next])}px`;
    setSnap(next);
  };

  return {
    snap,
    setSnap,
    sheet,
    /** The grip's click: keyboard (Enter, Space) or a pointer the drag handler did not take. */
    gripClick: () => {
      if (performance.now() - tapped.current < 600) return;
      setSnap(snap === "peek" ? "half" : "peek");
    },
    /** Opens the sheet if it is folded, leaving a full one as it is. */
    reveal: () => setSnap((s) => (s === "peek" ? "half" : s)),
    handlers: { onPointerDown, onPointerMove, onPointerUp: finish, onPointerCancel: finish },
  };
}
