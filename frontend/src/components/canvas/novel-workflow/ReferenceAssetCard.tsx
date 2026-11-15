import { useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useLeaveGuard } from "@/components/shared/edit-unit/LeaveGuard";
import type { DeliveryAsset, ReferencePolicy } from "@/types/novel-workflow";
import { errMsg } from "@/utils/async";

export function ReferenceAssetCard({ asset, projectName, disabled, canApprove, manage, approve }: {
  asset: DeliveryAsset; projectName: string; disabled: boolean; canApprove: boolean;
  manage: () => void; approve: (policy: ReferencePolicy) => Promise<void>;
}) {
  const { t } = useTranslation(["dashboard", "common"]);
  const initial: ReferencePolicy = asset.reference_policy ?? { controls: asset.kind === "scene" ? ["environment", "lighting"] : ["identity", "appearance"], excludes: "" };
  const [policy, setPolicy] = useState(initial);
  const [baseline, setBaseline] = useState(JSON.stringify(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const dirty = JSON.stringify(policy) !== baseline;
  async function submit() {
    if (disabled || saving || !canApprove || !asset.image_hash) return false;
    if (!policy.controls.length) { setError(t("dashboard:nw_reference_choose")); return false; }
    setSaving(true); setError("");
    try { await approve(policy); setBaseline(JSON.stringify(policy)); return true; }
    catch (e) { setError(errMsg(e)); return false; }
    finally { setSaving(false); }
  }
  useLeaveGuard({ dirty, saving, save: submit, discard: () => { setPolicy(initial); setBaseline(JSON.stringify(initial)); } });
  const status = asset.reference_status ?? (!asset.visible ? "voice_only" : !asset.image_hash ? "missing" : asset.image_approved ? "approved" : "pending");
  return <article className="flex flex-col gap-3 rounded-xl border bg-card p-4">
    <header className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-mono text-xs text-muted-foreground">{asset.asset_code}</p><h4 className="font-semibold">{asset.name}</h4></div><span className="rounded border bg-muted px-2 py-1 text-xs font-medium">{t(`dashboard:nw_reference_${status}`)}</span></header>
    {asset.visible && asset.image && <img src={API.getFileUrl(projectName, asset.image, asset.image_hash, { width: 640 })} alt={asset.name} className="h-48 w-full rounded-lg bg-muted/30 object-contain" />}
    {asset.visible && !asset.image && <p className="rounded border border-dashed p-4 text-sm text-muted-foreground">{t("dashboard:nw_delivery_no_image")}</p>}
    {asset.voice && <p className="text-sm">{t("dashboard:nw_delivery_voice")}：{asset.voice_style || t("dashboard:nw_delivery_voice_missing")}</p>}
    {asset.visible && <form aria-label={`${asset.name} · ${t("dashboard:nw_reference_scope")}`} className="space-y-3" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <fieldset disabled={disabled || saving} className="space-y-2"><legend className="mb-2 text-sm font-semibold">{t("dashboard:nw_reference_scope")}</legend><div className="flex flex-wrap gap-x-4 gap-y-2">{(["identity", "appearance", "environment", "lighting", "composition"] as const).map((control) => <label key={control} className="flex min-h-9 items-center gap-2 text-sm"><input type="checkbox" name="controls" value={control} checked={policy.controls.includes(control)} onChange={(e) => setPolicy({ ...policy, controls: e.target.checked ? [...policy.controls, control] : policy.controls.filter((v) => v !== control) })} />{t(`dashboard:nw_reference_${control}`)}</label>)}</div><p className="text-xs text-muted-foreground">{t("dashboard:nw_reference_scope_hint")}</p></fieldset>
      <label className="block space-y-1 text-sm"><span className="font-medium">{t("dashboard:nw_reference_excludes")}</span><Textarea name="excludes" maxLength={1500} value={policy.excludes} disabled={disabled || saving} onChange={(e) => setPolicy({ ...policy, excludes: e.target.value })} /></label>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {!canApprove && <p className="text-xs text-muted-foreground">{t("dashboard:nw_reference_confirm_text")}</p>}
      <Button type="submit" size="sm" disabled={disabled || saving || !canApprove || !asset.image_hash || (!!asset.image_approved && !dirty)}>{t(asset.image_approved && !dirty ? "dashboard:nw_delivery_image_approved" : "dashboard:nw_reference_save")}</Button>
    </form>}
    <Button type="button" size="sm" variant="outline" className="mt-auto" disabled={disabled || saving} onClick={manage}>{t("dashboard:nw_delivery_manage_asset")}</Button>
  </article>;
}
