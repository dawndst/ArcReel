import { useTranslation } from "react-i18next";
import type { ClaimStatus } from "@/types/novel-workflow";

export function ClaimBadge({ value }: { value: ClaimStatus }) {
  const { t } = useTranslation("dashboard");
  const kind = value.claim_type ?? "unverified";
  return <span title={value.uncertainty_reason || (kind === "unverified" ? t("nw_claim_unverified_hint") : undefined)} className={`mx-1 inline-flex rounded px-2 py-0.5 text-xs ${(kind === "fact" || kind === "unverified") && value.source_kind !== "annotation" ? "bg-muted text-muted-foreground" : "bg-warn/15 text-foreground"}`}>
    {t(value.source_kind === "annotation" ? "nw_claim_annotation" : value.claim_type === "unverified" ? "nw_claim_pending" : `nw_claim_${kind}`)}{value.perspective && ` · ${value.perspective}`}
  </span>;
}
