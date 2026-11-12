import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { NoteAsset } from "@/types/novel-workflow";

export interface IdentityDecision { entity_id: string; create_new: boolean; variant_kind: "visual" | "performance" | "none"; variant_name: string }
export function AssetIdentityResolver({ asset, disabled, save }: { asset: NoteAsset; disabled: boolean; save: (value: IdentityDecision) => Promise<void> }) {
  const { t } = useTranslation("dashboard");
  const candidates = [...(asset.identity_candidates ?? [])];
  if (asset.entity_id && asset.asset_name && !candidates.some((c) => c.entity_id === asset.entity_id)) candidates.push({ entity_id: asset.entity_id, name: asset.asset_name, asset_code: asset.asset_code ?? "" });
  const [target, setTarget] = useState(asset.entity_id ?? "");
  const [kind, setKind] = useState<IdentityDecision["variant_kind"]>(asset.source_variant ? "visual" : "none");
  const [variant, setVariant] = useState(asset.source_variant ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit() {
    if (disabled || saving || !target || (kind === "visual" && !variant.trim())) return;
    setSaving(true); setError("");
    try { await save({ entity_id: target === "new" ? "" : target, create_new: target === "new", variant_kind: kind, variant_name: variant }); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  }
  return <details open={asset.asset_issue_blocking ? true : undefined} className="mt-3 rounded border border-warn/40 bg-warn/5 p-3">
    <summary className="cursor-pointer text-sm font-semibold">{t(asset.asset_issue?.startsWith("identity_") ? "nw_identity_pending" : "nw_variant_pending")}</summary>
    <div className="mt-3 space-y-3"><p className="text-xs text-muted-foreground">{t("nw_identity_resolve_hint")}</p>
    <select className="w-full rounded border bg-background p-2 text-sm" aria-label={t("nw_identity_target")} value={target} disabled={disabled || saving} onChange={(e) => setTarget(e.target.value)}><option value="">{t("nw_identity_target")}</option>{candidates.map((c) => <option key={c.entity_id} value={c.entity_id}>{c.asset_code} · {c.name}</option>)}<option value="new">{t("nw_identity_new")}</option></select>
    <select className="w-full rounded border bg-background p-2 text-sm" aria-label={t("nw_variant_kind")} value={kind} disabled={disabled || saving} onChange={(e) => setKind(e.target.value as IdentityDecision["variant_kind"])}>{(["visual", "performance", "none"] as const).map((k) => <option key={k} value={k}>{t(`nw_variant_kind_${k}`)}</option>)}</select>
    {kind !== "none" && <Input aria-label={t("nw_variant_name")} placeholder={t("nw_variant_name")} value={variant} disabled={disabled || saving} onChange={(e) => setVariant(e.target.value)} />}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    <Button size="sm" disabled={disabled || saving || !target || (kind === "visual" && !variant.trim())} onClick={() => void submit()}>{t("nw_identity_save")}</Button>
    </div></details>;
}
