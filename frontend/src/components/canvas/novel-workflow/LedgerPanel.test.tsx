import { expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { LedgerPanel } from "./UnderstandingPanels";
import type { NovelLedger } from "@/types/novel-workflow";

it("separates character cards and foreshadowing within the same ledger and keeps source selection", () => {
  const evidence = { note_id: "n1", source_file: "book.txt", start: 0, end: 2, quote: "原文" };
  const ledger: NovelLedger = { characters: ["阳子", "景麒", "杉本"].map((name, i) => ({ id: `c${i}`, name, identity_scope: "", aliases: [], appear: ["n1"], mentions: [], changes: [], relations: [] })), aliases: [], relations: [], changes: [], threads: [{ id: "seed", kind: "seed", description: "神秘追兵的来历", seed_id: null, evidence }], unmatched_resolutions: [] };
  const select = vi.fn();
  render(<LedgerPanel ledger={ledger} notes={[]} select={select} />);
  expect(screen.getByRole("tab", { name: "人物" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getAllByRole("article")).toHaveLength(3);
  expect(screen.queryByText("神秘追兵的来历")).not.toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "选择来源 Note" })[0]!);
  expect(select).toHaveBeenCalledWith(["n1"]);
  fireEvent.click(screen.getByRole("tab", { name: "伏笔与回收" }));
  expect(screen.getByText("神秘追兵的来历")).toBeVisible();
  expect(screen.queryByRole("heading", { name: "阳子" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "人物" }));
  expect(screen.getByRole("heading", { name: "阳子" })).toBeVisible();
});
