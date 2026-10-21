// Fails the build when ru/kk/en keys drift apart, a t("key") has no entry,
// or Cyrillic UI text is hard-coded in JSX instead of going through useT().
import { readFileSync, readdirSync } from "node:fs";
import { extname, join } from "node:path";

const SRC = join(process.cwd(), "src");
const I18N = join(SRC, "lib", "i18n.ts");
const text = readFileSync(I18N, "utf8");

function keys(marker) {
  const start = text.indexOf(marker);
  if (start < 0) throw new Error(`marker not found: ${marker}`);
  const body = text.slice(start, text.indexOf("\n};", start));
  return new Set([...body.matchAll(/"([^"]+)"\s*:/g)].map((m) => m[1]));
}
const ru = keys("const ru: Record<string, string> = {");
const kk = keys("const kk: Record<string, string> = {");
const en = keys("const en: Record<string, string> = {");
const errors = [];
for (const [name, dict] of [["kk", kk], ["en", en]]) {
  for (const k of ru) if (!dict.has(k)) errors.push(`missing ${name} translation for "${k}"`);
  for (const k of dict) if (!ru.has(k)) errors.push(`missing ru translation for "${k}" (in ${name})`);
}

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(dir, e.name)) : [".ts", ".tsx"].includes(extname(e.name)) ? [join(dir, e.name)] : [],
  );
}
// Language names stay in their own language; place names come from data.
const ALLOWED = new Set(["РУС", "ҚАЗ"]);
const cyrillic = /[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]{2,}/;
for (const file of walk(SRC)) {
  if (file === I18N) continue;
  const src = readFileSync(file, "utf8");
  const where = (i) => `${file.replace(SRC, "src")}:${src.slice(0, i).split("\n").length}`;
  for (const m of src.matchAll(/\bt\(\s*"([^"]+)"/g)) {
    // t("cat." + code) is a dynamic key: the prefix must exist in the dictionary.
    const ok = m[1].endsWith(".") ? [...ru].some((k) => k.startsWith(m[1])) : ru.has(m[1]);
    if (!ok) errors.push(`${where(m.index)} t("${m[1]}") has no entry`);
  }
  if (!file.endsWith(".tsx")) continue;
  for (const m of src.matchAll(/>\s*([^<>{}\n]+?)\s*</g)) {
    const raw = m[1].trim();
    if (raw && cyrillic.test(raw) && !ALLOWED.has(raw)) errors.push(`${where(m.index)} raw Cyrillic JSX text "${raw}"`);
  }
}
if (errors.length) {
  console.error(`i18n validation failed (${errors.length}):`);
  for (const e of new Set(errors)) console.error("  " + e);
  process.exit(1);
}
console.log(`i18n ok: ru ${ru.size} / kk ${kk.size} / en ${en.size} keys, all t() keys and JSX text checked`);
