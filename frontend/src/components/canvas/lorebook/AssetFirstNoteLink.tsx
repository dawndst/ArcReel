import { Link } from "wouter";
import { useTranslation } from "react-i18next";
import type { AssetFirstNote } from "@/types/project";

export function AssetFirstNoteLink({ projectName, first }: { projectName: string; first?: AssetFirstNote }) {
  const { t } = useTranslation("dashboard");
  if (!first) return null;
  const label = t("nw_first_note", { number: String(first.order).padStart(3, "0"), title: first.title });
  return <Link
    href={`~/app/projects/${encodeURIComponent(projectName)}/episodes?note=${encodeURIComponent(first.id)}`}
    className="relative block truncate text-xs text-primary underline decoration-dotted underline-offset-4"
    title={`${label}\n${t("nw_first_note_hint")}`}
    onClick={(event) => event.stopPropagation()}
  >{label}</Link>;
}
