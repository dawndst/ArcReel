import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogBody } from "@/components/ui/dialog";
import { errMsg } from "@/utils/async";

export function SceneBatchSource({ projectName, basis, close }: { projectName: string; basis: string; close: () => void }) {
  const { t } = useTranslation("dashboard");
  const [value, setValue] = useState<Awaited<ReturnType<typeof API.getSceneBatchSource>> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void API.getSceneBatchSource(projectName, basis).then((v) => { if (active) setValue(v); }).catch((e: unknown) => { if (active) setError(errMsg(e)); });
    return () => { active = false; };
  }, [projectName, basis]);
  return <Dialog open onOpenChange={(open) => { if (!open) close(); }}><DialogContent>
    <DialogHeader><DialogTitle>{t("nw_batch_source_title")}{value && ` · ${value.note_title} · ${value.part}`}</DialogTitle><DialogDescription>{value ? `${value.source_file} · ${value.start}–${value.end}` : t("nw_batch_source")}</DialogDescription></DialogHeader>
    <DialogBody>{error ? <p role="alert" className="text-sm text-destructive">{error}</p> : value ? <p className="font-editorial text-base leading-8 whitespace-pre-wrap">{value.text}</p> : <p role="status">{t("nw_task_preparing")}</p>}</DialogBody>
  </DialogContent></Dialog>;
}
