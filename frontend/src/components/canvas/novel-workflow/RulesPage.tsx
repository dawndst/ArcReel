import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errMsg } from "@/utils/async";
import type { PromptRule } from "@/types/novel-workflow";

export function RulesPage({ projectName }: { projectName: string }) {
  const { t } = useTranslation("dashboard");
  const [entries, setEntries] = useState<PromptRule[]>([]);
  const [category, setCategory] = useState("novel");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("novel/svt");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => { const controller = new AbortController(); void API.getWorkbenchRules(projectName, controller.signal).then((value) => { if (!controller.signal.aborted) { setEntries(value.entries); setLoading(false); } }).catch((reason) => { if (!controller.signal.aborted) { setError(errMsg(reason)); setLoading(false); } }); return () => controller.abort(); }, [projectName]);
  const matches = entries.filter((entry) => (category === "all" || entry.category === category) && [entry.title, entry.purpose, entry.content, entry.location].some((value) => value.toLowerCase().includes(query.toLowerCase())));
  const active = matches.find((e) => e.id === selected) ?? matches[0];
  return <div className="@container/rules flex h-full min-h-0 flex-col">
    <header className="space-y-2 border-b p-5"><h1 className="text-lg font-semibold">{t("nw_rules_title")}</h1><p className="text-sm text-muted-foreground">{t("nw_rules_hint")}</p><Input aria-label={t("nw_rules_search")} placeholder={t("nw_rules_search")} value={query} onChange={(e) => setQuery(e.target.value)} /><nav className="flex flex-wrap gap-1" aria-label={t("nw_rules_categories")}>{["novel", "production", "partial", "agent", "other", "all"].map((key) => <Button key={key} size="sm" variant={category === key ? "default" : "ghost"} onClick={() => setCategory(key)}>{t(`nw_rules_${key}`)}</Button>)}</nav></header>
    {error && <p role="alert" className="p-5 text-destructive">{error}</p>}
    {loading && <p className="p-5">{t("nw_rules_loading")}</p>}
    {!loading && !error && <div className="grid min-h-0 flex-1 grid-cols-[10rem_minmax(0,1fr)] @min-[800px]/rules:grid-cols-[17rem_minmax(0,1fr)]">
      <aside className="relative min-h-0 overflow-y-auto border-r p-2"><ul className="space-y-1">{matches.map((entry) => <li key={entry.id}><button className={`focus-ring w-full rounded p-3 text-left text-sm ${active?.id === entry.id ? "bg-primary/10 font-semibold" : "hover:bg-muted"}`} onClick={() => setSelected(entry.id)}>{entry.title}<span className="mt-1 block text-xs font-normal text-muted-foreground">{t(entry.source === "project" ? "nw_rules_project" : "nw_rules_default")}</span></button></li>)}</ul></aside>
      <article className="relative min-w-0 space-y-4 overflow-y-auto p-5" aria-label={t("nw_rules_content")}>
        {active ? <><h2 className="text-xl font-semibold">{active.title}</h2><p className="text-sm text-muted-foreground">{active.purpose}</p><div className="space-y-1 rounded bg-muted p-3 text-xs"><p>{t(active.source === "project" ? "nw_rules_project" : "nw_rules_default")}</p><p className="break-all">{active.location}</p><p>{t("nw_rules_version")}：{active.version}</p></div><pre className="whitespace-pre-wrap break-words font-sans text-sm leading-7">{active.content}</pre></> : <p className="text-sm text-muted-foreground">{t("nw_rules_empty")}</p>}
      </article>
    </div>}
  </div>;
}
