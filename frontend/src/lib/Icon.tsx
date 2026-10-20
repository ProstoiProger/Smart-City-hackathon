import sprite from "../assets/icons.svg";

/** Lucide icon from the bundled sprite; decorative, so the text next to it carries the meaning. */
export function Icon({ name, className }: { name: string; className?: string }) {
  return (
    <svg className={"ic" + (className ? " " + className : "")} aria-hidden="true" focusable="false">
      <use href={`${sprite}#i-${name}`} />
    </svg>
  );
}
