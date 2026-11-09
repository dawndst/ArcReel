import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import type { EpisodeGuide, EpisodeGuideResponse } from "@/types/episode-guide";

export function EpisodeGuideDetails({ projectName, episode, initial, revision, fallback, prepare }: {
  projectName: string; episode: number; initial?: EpisodeGuide | null; revision: number; fallback?: ReactNode; prepare?: () => Promise<boolean>;
}) {
  const { t } = useTranslation("dashboard");
  const [result, setResult] = useState<EpisodeGuideResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void API.getEpisodeGuide(projectName, episode, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) { setResult(value); setLoaded(true); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) { setError(String(reason)); setLoaded(true); } });
    return () => controller.abort();
  }, [projectName, episode, revision]);
  useEffect(() => {
    if (!result?.running || busy) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      void API.getEpisodeGuide(projectName, episode, { signal: controller.signal })
        .then((value) => { if (!controller.signal.aborted) setResult(value); })
        .catch((reason: unknown) => { if (!controller.signal.aborted) setError(String(reason)); });
    }, 3000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [projectName, episode, result?.running, busy]);
  const working = busy || result?.running;
  const guide = result?.stale ? null : result?.guide ?? initial;
  async function generate() {
    setBusy(true);
    setError("");
    try {
      if (prepare && !(await prepare())) return;
      setResult(await API.generateEpisodeGuide(projectName, episode));
    }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  return <div className="flex flex-col gap-4 wrap-break-word">
    <div className="flex flex-col gap-2">
      <Button size="sm" variant="outline" disabled={!loaded || working} onClick={() => void generate()}>
        {working && <Loader2 data-icon="inline-start" className="animate-spin" />}
        {working ? t("guide_generating") : guide ? t("guide_regenerate") : t("guide_generate")}
      </Button>
      <p className="text-xs text-muted-foreground">{t(result?.stale ? "guide_stale" : "guide_scope")}</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {working && <p role="status" className="text-sm text-primary">{t("guide_generating")}</p>}
    </div>
    {!guide && fallback}
    {guide && <>
      <section><h3 className="mb-1 text-sm font-semibold">{t("guide_summary")}</h3><p className="text-sm leading-relaxed text-subtle-foreground">{guide.summary}</p></section>
      <section><h3 className="mb-1 text-sm font-semibold">{t("guide_events")}</h3><ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed text-subtle-foreground">{guide.story_beats.map((value) => <li key={value}>{value}</li>)}</ol></section>
      <section><h3 className="mb-1 text-sm font-semibold">{t("guide_changes")}</h3><ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed text-subtle-foreground">{guide.character_changes.map((value) => <li key={value}>{value}</li>)}</ul></section>
      <section className="rounded-lg bg-primary/10 p-3"><h3 className="mb-1 text-sm font-semibold">{t("guide_value")}</h3><p className="text-sm leading-relaxed">{guide.adaptation_value}</p><p className="mt-2 text-sm font-semibold">{t(`guide_${guide.recommendation}`)}</p><p className="text-sm leading-relaxed">{guide.recommendation_reason}</p></section>
      <section><h3 className="mb-1 text-sm font-semibold">{t("episode_workspace_guide_hook")}</h3><p className="text-sm leading-relaxed text-subtle-foreground">{guide.ending_hook}</p></section>
    </>}
  </div>;
}
