import { useTranslation } from "react-i18next";
import type { ExecutionCheck } from "@/types/novel-workflow";
function display(value: unknown): string { return typeof value === "string" ? value : JSON.stringify(value) ?? ""; }
export function ExecutionChecks({ checks, compact = false }: { checks: ExecutionCheck[]; compact?: boolean }) {
  const { t } = useTranslation("dashboard");
  function groups(values: ExecutionCheck[]) {
    return [...new Set(values.map((c) => c.code))].map((code) => {
      const items = values.filter((i) => i.code === code);
      return <details key={code} className={`rounded border p-2 text-sm ${items.some((i) => i.hard) ? "border-destructive/40 bg-destructive/5" : "border-border bg-muted/20"}`}><summary className="cursor-pointer font-medium">{t(`nw_exec_${code}`, { defaultValue: code })} · {items.length}</summary>
        {(code === "frame_states" || code === "background") && <p className="mt-2 text-xs leading-6 text-muted-foreground">{t(code === "frame_states" ? "nw_exec_frame_help" : "nw_exec_background_help")}</p>}
        <ul className="mt-2 space-y-2">{items.map((item) => <li key={item.id} className="text-xs leading-6">{item.segment != null && <span className="mr-2 font-medium">SEG{item.segment + 1}</span>}{item.details.name != null && display(item.details.name)}{item.details.text != null && display(item.details.text)}{Array.isArray(item.details.questions) && item.details.questions.map((q) => <p key={display(q)}>{display(q)}</p>)}{Array.isArray(item.details.reasons) && item.details.reasons.map((r) => <p key={display(r)}>{display(r)}</p>)}</li>)}</ul></details>;
    });
  }
  const errors = checks.filter((i) => i.hard);
  const suggestions = checks.filter((i) => !i.hard);
  return <div className="space-y-2">{groups(errors)}{compact && suggestions.length ? <details className="rounded border border-border bg-muted/10 p-2"><summary className="cursor-pointer text-xs text-muted-foreground">{t("nw_exec_optional", { count: suggestions.length })}</summary><div className="mt-2 space-y-2">{groups(suggestions)}</div></details> : groups(suggestions)}</div>;
}
