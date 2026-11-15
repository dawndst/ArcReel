import { createRoot } from "react-dom/client";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export class LlmCallCancelled extends Error { constructor() { super("已取消模型调用"); this.name = "LlmCallCancelled"; } }
const names: Record<string, string> = { read:"泛读生成 Note / 续跑", svt:"提炼 SVT 与爆点", review:"分析改编取舍", understand:"跨章精读与回查", conclusions:"更新问题与结论", questions:"整理相似问题", scenes:"生成场与镜头", condense:"生成精简稿", group_summary:"汇总资料组", speaker_attribution:"分析说话人", shot_draft:"修订镜头", craft_review:"检查内容与外观", selection_story:"检查组集叙事", conclusion_evidence:"定向回查当前疑点" };
const contexts = new Map<string, { notes: Record<string, string>; questions: Record<string, string> }>();
export function setLlmContext(project: string, notes: Record<string, string>, questions: Record<string, string>) { contexts.set(project, { notes, questions }); }
export function llmRequestSummary(endpoint: string, options: RequestInit): string | null {
  if (options.method?.toUpperCase() !== "POST") return null;
  let body: Record<string, unknown> = {};
  try { if (typeof options.body === "string") body = JSON.parse(options.body); } catch { /* request validation owns invalid JSON */ }
  if (/\/novel-workflow\/run$/.test(endpoint)) {
    if (body.action === "questions" && body.question_ai !== true) return null;
    const chapters = Array.isArray(body.note_ids) ? body.note_ids.length : 0;
    const shots = Array.isArray(body.shot_ids) ? body.shot_ids.length : 0;
    const project = decodeURIComponent(endpoint.split("/")[2] ?? "");
    const context = contexts.get(project);
    const titles = Array.isArray(body.note_ids) ? body.note_ids.slice(0, 8).map((id) => context?.notes[String(id)]).filter(Boolean) : [];
    const question = context?.questions[String(body.conclusion_id)];
    return `${names[String(body.action)] ?? "小说理解与制作"} · ${chapters} 章${shots ? ` · ${shots} 镜` : ""}${titles.length ? "\n"+titles.join("、") : ""}${question ? "\n本次疑点："+question : ""}`;
  }
  if (/\/(script-plan|prompt-authoring|ad-script|generate-overview|episode-guide|guide)$/.test(endpoint)) return "生成或更新创作内容";
  if (/\/(preview|precheck|duration-precheck)$/.test(endpoint)) return null;
  if (/\/(asset-sheets|storyboards|videos)\/batch$/.test(endpoint)) return "批量生成制作内容";
  if (/\/generate\//.test(endpoint) || /\/reference-videos\/.*\/(generate|generate-batch)$/.test(endpoint)) return "生成制作内容";
  if (/\/assistant\/.*\/(send|rewrite|resend|send-now)$/.test(endpoint)) return "发送给创作 Agent（可能继续调用模型与工具）";
  return null;
}
let queue = Promise.resolve();
export function confirmLlmCall(summary: string): Promise<void> {
  const show = () => new Promise<void>((resolve, reject) => {
    const origin = document.activeElement;
    const container = document.createElement("div"); document.body.append(container);
    const root = createRoot(container);
    let settled = false;
    const finish = (approved: boolean) => {
      if (settled) return; settled = true;
      queueMicrotask(() => { root.unmount(); container.remove(); setTimeout(() => { if (origin instanceof HTMLElement && origin.isConnected) origin.focus(); }, 0); });
      if (approved) resolve(); else reject(new LlmCallCancelled());
    };
    root.render(<Dialog open onOpenChange={(open) => { if (!open) finish(false); }}><DialogContent>
      <DialogTitle>确认调用 AI 模型？</DialogTitle>
      <DialogDescription>确认后才提交任务，可能产生 API 费用。一次任务可能包含多次模型调用与校验修复；有效缓存会复用，取消不会提交。</DialogDescription>
      <p className="max-h-48 overflow-y-auto whitespace-pre-line text-sm font-semibold">{summary}</p>
      {summary.includes("Note") && <p className="text-sm text-muted-foreground">已有有效 Note 和完成片段会保留；缺失或过期的资料、精简稿、理解层可能继续处理。</p>}
      <DialogFooter><Button variant="outline" onClick={() => finish(false)}>取消</Button><Button onClick={() => finish(true)}>确认调用 AI</Button></DialogFooter>
    </DialogContent></Dialog>);
  });
  const pending = queue.then(show);
  queue = pending.catch(() => undefined);
  return pending;
}
