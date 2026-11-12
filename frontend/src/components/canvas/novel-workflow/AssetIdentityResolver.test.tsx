import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { NoteAsset } from "@/types/novel-workflow";
import { AssetIdentityResolver } from "./AssetIdentityResolver";

it("links the selected entity and records voice performance without a visual variant", async () => {
  const asset: NoteAsset = { id: "m", kind: "character", name: "苍猿", identity_scope: "未知妖魔", description: "笑声", asset_issue: "identity_ambiguous", asset_issue_blocking: true, source_variant: "幻听/笑声", identity_candidates: [{ entity_id: "entity", name: "苍猿", asset_code: "CHR-068" }], evidence: { note_id: "n", source_file: "book", start: 0, end: 2, quote: "原文" } };
  const save = vi.fn().mockResolvedValue(undefined);
  render(<AssetIdentityResolver asset={asset} disabled={false} save={save} />);
  fireEvent.change(screen.getByRole("combobox", { name: "选择关联的本体资产" }), { target: { value: "entity" } });
  fireEvent.change(screen.getByRole("combobox", { name: "变体用途" }), { target: { value: "performance" } });
  fireEvent.click(screen.getByRole("button", { name: "确认资产关联" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith({ entity_id: "entity", create_new: false, variant_kind: "performance", variant_name: "幻听/笑声", appearance_context: "current" }));
});
