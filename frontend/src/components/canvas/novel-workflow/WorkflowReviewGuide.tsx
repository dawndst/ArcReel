import { useTranslation } from "react-i18next";

const checks = [
  { key: "note", level: "scoped" },
  { key: "questions", level: "continue" },
  { key: "understanding", level: "scoped" },
  { key: "svt", level: "scoped" },
  { key: "scenes", level: "scoped" },
  { key: "review", level: "final" },
  { key: "assets", level: "final" },
  { key: "speakers", level: "final" },
  { key: "optional", level: "continue" },
  { key: "timing", level: "continue" },
  { key: "images", level: "final" },
  { key: "delivery", level: "final" }
] as const;

export function WorkflowReviewGuide() {
  const { t } = useTranslation("dashboard");
  return <section aria-labelledby="workflow-review-title" className="space-y-4">
    <header><h2 id="workflow-review-title" className="text-xl font-bold">{t("nw_gate_title")}</h2><p className="mt-2 text-sm leading-7 text-muted-foreground">{t("nw_gate_intro")}</p></header>
    <div className="grid gap-3 md:grid-cols-3">{(["continue", "scoped", "final"] as const).map((level) => <article key={level} className={`rounded-xl border p-4 ${level === "continue" ? "border-primary/25 bg-primary/5" : level === "scoped" ? "border-warn/30 bg-warn/5" : "border-border bg-muted/30"}`}><h3 className="text-base font-bold">{t(`nw_gate_${level}`)}</h3><p className="mt-2 text-sm leading-7">{t(`nw_gate_${level}_help`)}</p></article>)}</div>
    <div role="region" aria-labelledby="workflow-review-title" tabIndex={0} className="focus-ring max-w-full overflow-x-auto rounded-xl border bg-card">
      <table className="w-full min-w-[900px] border-separate border-spacing-0 text-left text-sm"><caption className="sr-only">{t("nw_gate_title")}</caption><thead className="bg-muted"><tr>{(["name", "who", "effect", "action"] as const).map((key) => <th key={key} scope="col" className="border-b px-4 py-3 font-bold">{t(`nw_gate_${key}`)}</th>)}</tr></thead><tbody>{checks.map(({ key, level }) => <tr key={key} className="align-top"><th scope="row" className="w-40 border-b p-4 font-bold">{t(`nw_gate_${key}_name`)}</th><td className="w-52 border-b p-4 leading-7 text-muted-foreground">{t(`nw_gate_${key}_who`)}</td><td className="border-b p-4 leading-7"><span className={`mb-2 inline-block rounded border px-2 py-0.5 text-xs font-bold ${level === "continue" ? "border-primary/30 text-primary" : level === "scoped" ? "border-warn/40" : "border-border"}`}>{t(`nw_gate_${level}`)}</span><p>{t(`nw_gate_${key}_effect`)}</p></td><td className="border-b p-4 leading-7">{t(`nw_gate_${key}_action`)}</td></tr>)}</tbody></table>
    </div>
    <p className="rounded-lg border border-dashed p-3 text-xs leading-6 text-muted-foreground">{t("nw_gate_limits")}</p>
  </section>;
}
