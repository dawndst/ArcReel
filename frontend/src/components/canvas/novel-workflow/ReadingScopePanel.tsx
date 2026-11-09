import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { NovelWorkflow } from "@/types/novel-workflow";

export function ReadingScopePanel({ scope, selected, disabled, save }: {
  scope: NovelWorkflow["scope"]; selected: string[]; disabled: boolean; save: () => void;
}) {
  const { t } = useTranslation("dashboard");
  return <details className="shrink-0 border-b px-5 py-2 text-sm">
    <summary className="cursor-pointer text-muted-foreground">{t("nw_scope_title")} · {scope?.configured ? t("nw_scope_progress", { available: scope.available_count, read: scope.read_count, total: scope.total_count }) : t("nw_scope_unset")}</summary>
    <div className="space-y-2 py-3">
      <p className="text-xs leading-relaxed text-muted-foreground">{t("nw_scope_hint")}</p>
      <Button variant="outline" size="sm" disabled={disabled || !selected.length} onClick={save}>{t("nw_scope_set")}</Button>
    </div>
  </details>;
}
