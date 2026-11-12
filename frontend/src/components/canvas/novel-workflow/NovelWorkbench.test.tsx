import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { API } from "@/api";
import { useTasksStore } from "@/stores/tasks-store";
import type { NovelWorkflow } from "@/types/novel-workflow";
import { NovelWorkbench } from "./NovelWorkbench";

const data: NovelWorkflow = {
  initialized: true, source_basis: "source-version", stale: false, groups: [], svts: [], progress: null,
  notes: [1, 2].map((i) => ({ id: `note-${i}`, order: i, title: `卷一 · 第${i}章`, volume: "卷一", chapter: `第${i}章`, chars: 100, basis: `basis-${i}`, status: "unread", sections: [{ title: `第${i}章`, source_file: "source/book.txt", start: i * 100, end: (i + 1) * 100 }] })),
};
beforeEach(() => {
  window.history.replaceState({}, "", "/");
  vi.restoreAllMocks();
  useTasksStore.setState(useTasksStore.getInitialState(), true);
  vi.spyOn(useTasksStore.getState(), "refreshTasks").mockResolvedValue(undefined);
  vi.spyOn(API, "getNovelWorkflow").mockResolvedValue(data);
});
it("opens chapter Notes without starting reading or merging and shows unread state", async () => {
  const run = vi.spyOn(API, "runNoteWorkflow");
  const merge = vi.spyOn(API, "createNoteGroup");
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  expect(await screen.findByRole("heading", { name: "卷一 · 第1章" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "从所选 Note 提炼 SVT" })).toBeDisabled();
  expect(screen.getByText(/尚未生成本章 Note/)).toBeInTheDocument();
  expect(run).not.toHaveBeenCalled();
  expect(merge).not.toHaveBeenCalled();
});
it("requires human confirmation to group selected Notes and preserves source Notes", async () => {
  const merged = { id: "group-1", title: "改编组合", note_ids: ["note-1", "note-2"], source_basis: data.source_basis!, created_by: "human" };
  const merge = vi.spyOn(API, "createNoteGroup").mockImplementation(async () => {
    vi.mocked(API.getNovelWorkflow).mockResolvedValue({ ...data, groups: [merged] });
    return merged;
  });
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "选择 卷一 · 第1章" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "选择 卷一 · 第2章" }));
  fireEvent.click(screen.getByRole("button", { name: "人工合并 Note" }));
  expect(merge).not.toHaveBeenCalled();
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("卷一 · 第1章")).toBeInTheDocument();
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "改编组合" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "确认创建组合" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(await screen.findByRole("heading", { name: "改编组合" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "章节 Note (2)" })).toBeInTheDocument();
});
it("shows a consolidated chapter summary and lets review suggestions select sources without merging", async () => {
  const evidence = { source_file: "source/book.txt", start: 100, end: 106, quote: "甲拿起古剑。", note_id: "note-1" };
  const enriched: NovelWorkflow = { ...data, notes: [{ ...data.notes[0]!, status: "read", reading: {
    basis: "read-basis", summaries: ["分块内部摘要，不应冒充整章概况"], assets: [], changes: [], events: [], questions: [],
    overview: { summary: "为了脱身，甲取剑应对阻力，最终找到出路。", cause: "脱身", conflict: "阻力", action: "取剑", outcome: "找到出路", hook: "前路未明", evidence_ids: ["fact"], questions: [] },
  } }], reviews: [{ id: "review", note_ids: ["note-1"], stale: false, created_at: "2026-11-09T10:00:00Z", scope_kind: "selected", evidence: { fact: { id: "fact", evidence } }, sections: [], overview: [{ theme: "求生", mainline: "寻找出路", questions: [], advice: [{ action: "keep", note_ids: ["note-1"], evidence_ids: ["fact"], reason: "保留因果", character_impact: "建立主动性", thread_impact: "保留剑的来历", dialogue_impact: "无对白", preserve: "取剑行动" }] }] }] };
  vi.mocked(API.getNovelWorkflow).mockResolvedValue(enriched);
  const merge = vi.spyOn(API, "createNoteGroup");
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  expect(await screen.findByText("为了脱身，甲取剑应对阻力，最终找到出路。")).toBeInTheDocument();
  expect(screen.queryByText("分块内部摘要，不应冒充整章概况")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "改编收敛建议 (1)" }));
  expect(screen.getByText("建立主动性")).toBeInTheDocument();
  expect(screen.getByText("保留剑的来历")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "选择来源 Note" }));
  expect(screen.getByRole("checkbox", { name: "选择 卷一 · 第1章" })).toBeChecked();
  expect(merge).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("saves independent summary and understanding settings without starting a model task", async () => {
  const save = vi.spyOn(API, "updateNoteSettings").mockResolvedValue({ summary_max_chars: 2400, understanding_enabled: false });
  const run = vi.spyOn(API, "runNoteWorkflow");
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: "阅读设置" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByRole("spinbutton"), { target: { value: "2400" } });
  fireEvent.click(within(dialog).getByRole("checkbox", { name: "启用跨章理解（默认开启）" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "保存" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(save).toHaveBeenCalledWith("demo", { summary_max_chars: 2400, understanding_enabled: false, delivery_checks_enabled: true });
  expect(run).not.toHaveBeenCalled();
});

it("shows one primary SVT and several alternatives and replaces only on explicit selection", async () => {
  const enriched = { ...data, notes: [{ ...data.notes[0]!, svt_id: "primary", svt_title: "主线目标", svt_status: "needs_details", svt_candidates: [1, 2].map((i) => ({ candidate_id: `c${i}`, existing_id: null, title: `备选${i}`, summary: "当前章节的另一种解读", reason: "强调不同目标" })) }] };
  vi.mocked(API.getNovelWorkflow).mockResolvedValue(enriched);
  const adopt = vi.spyOn(API, "adoptNoteSVT").mockResolvedValue({ svt_id: "new" });
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  expect(await screen.findByText("主线目标")).toBeInTheDocument();
  expect(screen.getByText("备选1")).toBeInTheDocument();
  expect(screen.getByText("备选2")).toBeInTheDocument();
  expect(adopt).not.toHaveBeenCalled();
  fireEvent.click(screen.getAllByRole("button", { name: "替换为主归属 SVT" })[1]!);
  await waitFor(() => expect(adopt).toHaveBeenCalledWith("demo", "note-1", "c2", "source-version"));
});

it("selects a chapter range and generates only those Notes on explicit click", async () => {
  const run = vi.spyOn(API, "runNoteWorkflow").mockResolvedValue({});
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  await screen.findByText("阅读范围与设置");
  const range = screen.getByText("阅读范围与设置");
  if (!range.closest("details")!.open) fireEvent.click(range);
  expect(screen.getByText(/已生成 0 \/ 2 章 Notes/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("spinbutton", { name: "起始章节序号" }), { target: { value: "2" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "结束章节序号" }), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "选择此范围" }));
  expect(run).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /AI 泛读并生成 Notes · 已选 1 章/ }));
  await waitFor(() => expect(run).toHaveBeenCalledWith("demo", "read", ["note-2"], "source-version"));
});

it("blocks scene generation for a changed primary SVT and explains the next action", async () => {
  vi.mocked(API.getNovelWorkflow).mockResolvedValue({ ...data, settings: { summary_max_chars: 1200, understanding_enabled: false }, notes: [{ ...data.notes[0]!, status: "read", svt_id: "primary", svt_status: "needs_review" }] });
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: /卷一 · 第1章/ }));
  expect(screen.getByRole("button", { name: "生成场与镜头" })).toBeDisabled();
  expect(screen.getByText(/主归属已调整：请选中相关 SVT/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "从所选 Note 提炼 SVT" })).toBeEnabled();
});

it("retains the scene library after the workbench remounts following an asset registration", async () => {
  const first = render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: /^场镜素材库/ }));
  expect(new URLSearchParams(window.location.search).get("workbench")).toBe("scenes");
  first.unmount();
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  expect(await screen.findByPlaceholderText("搜索场、镜头或对白")).toBeInTheDocument();
});

it("organizes Note information, original text and condensed text in lazy horizontal tabs without duplicate edition controls", async () => {
  const edition = { basis: "edition-basis", created_at: "now", original_chars: 100, edited_chars: 20, parts: [{ source_file: "source/book.txt", start: 0, end: 100, passages: [{ unit: 0, treatment: "retain" as const, text: "本章精简后的文本", reason: "保留行动", original_quote: "原著完整正文", evidence: { source_file: "source/book.txt", start: 0, end: 100 }, protected: false }] }] };
  vi.mocked(API.getNovelWorkflow).mockResolvedValue({ ...data, notes: [{ ...data.notes[0]!, edition, svt_candidates: [], status: "read", reading: { basis: "r", summaries: ["本章内容概况"], assets: [], changes: [], events: [], questions: [] } }] });
  const source = vi.spyOn(API, "getChapterNoteSource").mockResolvedValue({ text: "原著完整正文" });
  const condensed = vi.spyOn(API, "getChapterEdition").mockResolvedValue(edition);
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  expect(await screen.findByText("本章内容概况")).toBeInTheDocument();
  const tabs = screen.getByRole("tablist", { name: "章节阅读视图" });
  expect(within(tabs).getAllByRole("tab")).toHaveLength(3);
  expect(screen.getByRole("tab", { name: "Note信息" })).toHaveAttribute("aria-selected", "true");
  expect(screen.queryByText(/SVT 备选/)).not.toBeInTheDocument();
  expect(screen.queryByText(/不为凑数/)).not.toBeInTheDocument();
  expect(screen.queryByText("章节精编稿")).not.toBeInTheDocument();
  expect(source).not.toHaveBeenCalled(); expect(condensed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("tab", { name: "章节原文" }));
  expect(await screen.findByText("原著完整正文")).toBeVisible();
  expect(source).toHaveBeenCalledWith("demo", "note-1");
  expect(condensed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("tab", { name: "章节精简稿" }));
  expect(await screen.findByText("本章精简后的文本")).toBeVisible();
  expect(condensed).toHaveBeenCalledWith("demo", "note-1");
  expect(screen.queryByText(/原文 100 字 · 精编 20 字/)).not.toBeInTheDocument();
});
