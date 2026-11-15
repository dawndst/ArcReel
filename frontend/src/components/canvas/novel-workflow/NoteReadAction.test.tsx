import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { NoteReadAction } from "./NoteReadAction";
import type { ChapterNote } from "@/types/novel-workflow";

it("labels saved Note requests as resume and delegates once to the centrally confirmed API", async () => {
  const run = vi.fn().mockResolvedValue(undefined);
  render(<NoteReadAction notes={[{id:'n',title:'第二章',status:'read'} as ChapterNote]} disabled={false} run={run} />);
  fireEvent.click(screen.getByRole('button',{name:/Note 已生成/}));
  await waitFor(() => expect(run).toHaveBeenCalledExactlyOnceWith(['n']));
});
it("does not submit an empty selection", () => {
  const run = vi.fn();
  render(<NoteReadAction notes={[]} disabled={false} run={run} />);
  expect(screen.getByRole('button')).toBeDisabled();
  expect(run).not.toHaveBeenCalled();
});
