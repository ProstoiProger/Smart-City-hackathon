import { useCallback, useEffect, useRef, useState } from "react";
import type { Lang } from "./prefs";

// Web Speech API: not in lib.dom for every browser, so only what is used is declared.
interface RecognitionResult {
  readonly isFinal: boolean;
  readonly 0: { readonly transcript: string };
}
interface RecognitionEvent {
  readonly resultIndex: number;
  readonly results: ArrayLike<RecognitionResult>;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

const SPEECH_LANG: Record<Lang, string> = { ru: "ru-RU", kk: "kk-KZ" };

function recognitionCtor(): RecognitionCtor | undefined {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

export const canListen = () => typeof window !== "undefined" && !!recognitionCtor();
export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window;

export type VoiceError = "denied" | "no-speech" | "failed";

/** One-shot dictation: interim text streams to onInterim, the final phrase goes to onFinal. */
export function useDictation(lang: Lang, onInterim: (text: string) => void, onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<VoiceError | null>(null);
  const rec = useRef<Recognition | null>(null);
  const heard = useRef("");
  const handlers = useRef({ onInterim, onFinal });
  handlers.current = { onInterim, onFinal };

  const stop = useCallback(() => rec.current?.stop(), []);

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor || rec.current) return;
    const r = new Ctor();
    r.lang = SPEECH_LANG[lang];
    r.continuous = false;
    r.interimResults = true;
    heard.current = "";
    setError(null);
    r.onresult = (e) => {
      let text = "";
      for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      heard.current = text.trim();
      handlers.current.onInterim(heard.current);
    };
    r.onerror = (e) => {
      if (e.error === "aborted") return;
      if (e.error === "not-allowed" || e.error === "service-not-allowed") setError("denied");
      else if (e.error === "no-speech") setError("no-speech");
      else setError("failed");
    };
    r.onend = () => {
      rec.current = null;
      setListening(false);
      const text = heard.current;
      heard.current = "";
      if (text) handlers.current.onFinal(text);
    };
    rec.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      rec.current = null;
      setError("failed");
    }
  }, [lang]);

  useEffect(() => () => rec.current?.abort(), []);

  return { listening, error, start, stop };
}

function pickVoice(lang: Lang): { voice?: SpeechSynthesisVoice; tag: string } {
  const voices = window.speechSynthesis.getVoices();
  const find = (tag: string) =>
    voices.find((v) => v.lang.replace("_", "-").toLowerCase() === tag.toLowerCase()) ??
    voices.find((v) => v.lang.toLowerCase().startsWith(tag.slice(0, 2).toLowerCase()));
  const own = find(SPEECH_LANG[lang]);
  if (own) return { voice: own, tag: SPEECH_LANG[lang] };
  // Few systems ship a Kazakh voice; Russian is the closest readable fallback for Cyrillic text.
  const ru = lang === "kk" ? find(SPEECH_LANG.ru) : undefined;
  return ru ? { voice: ru, tag: SPEECH_LANG.ru } : { tag: SPEECH_LANG[lang] };
}

export function stopSpeaking() {
  if (canSpeak()) window.speechSynthesis.cancel();
}

export function speak(text: string, lang: Lang, onEnd?: () => void) {
  if (!canSpeak()) return;
  const clean = text.replace(/[*_#`>]+/g, "").replace(/\s+/g, " ").trim();
  if (!clean) return;
  const synth = window.speechSynthesis;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(clean);
  const { voice, tag } = pickVoice(lang);
  u.lang = tag;
  if (voice) u.voice = voice;
  u.onend = () => onEnd?.();
  u.onerror = () => onEnd?.();
  synth.speak(u);
}

/** Voices load asynchronously in Chromium; touching the list early lets the first reply find one. */
export function warmUpVoices() {
  if (canSpeak()) window.speechSynthesis.getVoices();
}
