import { useTranslation } from "react-i18next";
import type { ExecutionCheck } from "@/types/novel-workflow";
function display(value: unknown): string { return typeof value === "string" ? value : JSON.stringify(value) ?? ""; }
export function ExecutionChecks({ checks }: { checks: ExecutionCheck[] }) {
  const { t } = useTranslation("dashboard");
  const groups = [...new Set(checks.map((c) => c.code))];
  return <div className="space-y-2">{groups.map((code) => {
    const items = checks.filter((i) => i.code === code);
    return <details key={code} className={`rounded border p-2 text-sm ${items.some((i) => i.hard) ? "border-destructive/40 bg-destructive/5" : "border-warn/40 bg-warn/5"}`}><summary className="cursor-pointer font-semibold">{t(`nw_exec_${code}`, { defaultValue: code })} · {items.length}</summary><ul className="mt-2 space-y-2">{items.map((item) => <li key={item.id} className="text-xs leading-6">{item.segment != null && `SEG${item.segment + 1} · `}{item.details.name != null && `${display(item.details.name)} · `}{item.details.text != null && display(item.details.text)}{Array.isArray(item.details.questions) && item.details.questions.map((q) => <p key={display(q)}>{display(q)}</p>)}{Array.isArray(item.details.reasons) && item.details.reasons.map((r) => <p key={display(r)}>{display(r)}</p>)}</li>)}</ul></details>;
  })}</div>;
}
