import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import type { ChapterNote } from "@/types/novel-workflow";

export function NoteReadAction({ notes, disabled, run }: { notes: ChapterNote[]; disabled: boolean; run: (ids: string[]) => Promise<void> }) {
  const [pending, setPending] = useState<ChapterNote[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const existing = notes.filter((note) => !!note.reading || note.status === "read" || note.status === "outdated");
  const sameSelection = pending?.map((note) => note.id).join("|") === notes.map((note) => note.id).join("|");
  async function submit(ids: string[]) {
    if (disabled || submitting) return;
    setSubmitting(true); setError("");
    try { await run(ids); setPending(null); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSubmitting(false); }
  }
  return <>
    <Button size="sm" disabled={disabled || submitting || !notes.length} onClick={() => { if (existing.length) setPending([...notes]); else void submit(notes.map((note) => note.id)); }}>{existing.length === notes.length && notes.length ? "Note 已生成 · 检查/续跑" : existing.length ? "生成缺失 Note / 续跑" : "AI 泛读并生成 Notes"} · 已选 {notes.length} 章</Button>
    {!pending && error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Dialog open={pending !== null} onOpenChange={(open) => { if (!open && !submitting) { setPending(null); setError(""); } }}><DialogContent>
      <DialogTitle>这些章节已有 Note，是否检查并续跑？</DialogTitle>
      <DialogDescription>将复用当前有效的 Note 和已完成片段；过期资料或未完成的审查、精简稿、理解层可能继续处理并调用模型。此操作不是强制重新生成整章。</DialogDescription>
      <ul className="space-y-2 text-sm">{pending?.map((note) => <li key={note.id}>{note.title} · {note.status === "read" ? "已生成" : note.reading ? "已有资料" : "尚未生成"}</li>)}</ul>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <DialogFooter><Button variant="outline" disabled={submitting} onClick={() => { setPending(null); setError(""); }}>取消</Button><Button disabled={disabled || submitting || !sameSelection} onClick={() => { if (pending && sameSelection) void submit(pending.map((note) => note.id)); }}>确认检查并续跑</Button></DialogFooter>
    </DialogContent></Dialog>
  </>;
}
