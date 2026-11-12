export interface SourceRange { start: number; end: number }
export function highlightedSource(text: string, start: number, context: SourceRange | undefined, focus: SourceRange[]) {
  // Source offsets are Unicode code points, while JavaScript string indices are UTF-16.
  const chars = Array.from(text);
  const ranges = [...(context ? [context] : []), ...focus];
  const cuts = [...new Set([0, chars.length, ...ranges.flatMap((r) => [r.start - start, r.end - start]).map((n) => Math.max(0, Math.min(chars.length, n)))])].sort((a, b) => a - b);
  return cuts.slice(0, -1).map((from, i) => {
    const to = cuts[i + 1];
    const inside = (r: SourceRange) => r.start < start + to && r.end > start + from;
    return { start: from, text: chars.slice(from, to).join(""), focus: focus.some(inside), context: !!context && inside(context) };
  });
}
