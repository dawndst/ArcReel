// Brand configuration — single source of truth for product naming.
// Override at build time via Vite env vars
// (VITE_BRAND_NAME / VITE_BRAND_TAGLINE / VITE_BRAND_DESCRIPTION).
//
// Source code references BRAND.name (or the [[brand]] placeholder in i18n
// resources) so the displayed product name is not hardcoded across files.
// Defaults name this novel-adaptation workbench; deployments can override them.

const env = import.meta.env as Record<string, string | undefined>;

function fallback(value: string | undefined, defaultValue: string): string {
  // Trim + empty check so VITE_BRAND_NAME="" (or whitespace) falls back to the
  // default for this distribution.
  if (typeof value !== "string") return defaultValue;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : defaultValue;
}

export const BRAND = {
  name: fallback(env.VITE_BRAND_NAME, "拆书工作台"),
  tagline: fallback(env.VITE_BRAND_TAGLINE, "小说理解与漫剧改编"),
  description: fallback(
    env.VITE_BRAND_DESCRIPTION,
    "小说阅读、章节笔记、主线事件与漫剧改编工作台。",
  ),
} as const;

export const BRAND_DOCUMENT_TITLE = BRAND.name;

export function brandedText(value: string): string {
  // Keep functional URLs, filesystem paths and tool IDs intact.
  return value
    .replace(/(?<![\w/.-])arcreel(?![\w/.-])/gi, () => BRAND.name)
    .replace(/\[\[\s*brand\s*\]\]/g, () => BRAND.name);
}

