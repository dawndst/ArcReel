import { useState } from "react";
import { Link, useLocation } from "wouter";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useProjectsStore } from "@/stores/projects-store";
import { NovelWorkbench } from "../novel-workflow/NovelWorkbench";
import { CreateEpisodeDialog } from "./CreateEpisodeDialog";
import { SourceUploadDialog } from "./SourceUploadDialog";

export function EpisodesView({ projectName }: { projectName: string }) {
  const { t } = useTranslation("dashboard");
  const [, navigate] = useLocation();
  const project = useProjectsStore((state) => state.currentProjectData);
  const [production, setProduction] = useState(false);
  const [creating, setCreating] = useState(false);
  const [upload, setUpload] = useState(false);
  const novel = project?.content_mode === "drama";
  if (novel && !production) return <NovelWorkbench key={projectName} projectName={projectName} onProduction={() => setProduction(true)} />;
  return <section className="relative flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
    <header className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-lg font-semibold">{t("nw_production")}</h1>
      {novel ? <Button variant="outline" onClick={() => setProduction(false)}>{t("nw_back")}</Button> : <div className="flex gap-2"><Button variant="outline" onClick={() => setUpload(true)}>{t("nw_upload")}</Button><Button onClick={() => setCreating(true)}>{t("episode_create_title")}</Button></div>}
    </header>
    {novel && <p className="text-sm text-muted-foreground">{t("nw_arrange_hint")}</p>}
    <ol className="space-y-2">{(project?.episodes ?? []).map((episode, index) => <li key={episode.episode}><Link href={`/episodes/${episode.episode}`} className="focus-ring flex items-center gap-3 rounded border p-4 hover:bg-muted"><strong>EP{String(index + 1).padStart(2, "0")}</strong><span>{episode.title}</span></Link></li>)}</ol>
    {creating && <CreateEpisodeDialog projectName={projectName} onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); if (id !== null) navigate(`/episodes/${id}`); }} />}
    {upload && <SourceUploadDialog projectName={projectName} onClose={() => setUpload(false)} />}
  </section>;
}
