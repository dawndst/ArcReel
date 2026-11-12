/** Display-only cleanup of EPUB spacing. Never use this string to save or re-anchor source evidence. */
export function sourceExcerptDisplay(text: string): string {
  return text.replace(/\r\n?/g, "\n").split("\n").map((line) => line.trim()).join("\n").replace(/\n{3,}/g, "\n\n").trim();
}
