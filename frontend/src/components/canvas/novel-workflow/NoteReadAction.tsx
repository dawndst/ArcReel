import { useState } from "react";
import { Button } from "@/components/ui/button";
import { LlmCallCancelled } from "@/lib/llm-confirmation";
import type { ChapterNote } from "@/types/novel-workflow";

export function NoteReadAction({ notes, disabled, run }: { notes: ChapterNote[]; disabled: boolean; run: (ids: string[]) => Promise<void> }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const existing = notes.filter((note) => !!note.reading || note.status === "read" || note.status === "outdated");
  async function submit() {
    if (disabled || submitting || !notes.length) return;
    setSubmitting(true); setError("");
    try { await run(notes.map((note) => note.id)); }
    catch (e) { if (!(e instanceof LlmCallCancelled)) setError(e instanceof Error ? e.message : String(e)); }
    finally { setSubmitting(false); }
  }
  return <><Button size="sm" disabled={disabled || submitting || !notes.length} onClick={() => void submit()}>{existing.length === notes.length && notes.length ? "Note 已生成 · 检查/续跑" : existing.length ? "生成缺失 Note / 续跑" : "AI 泛读并生成 Notes"} · 已选 {notes.length} 章</Button>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}</>;
}
