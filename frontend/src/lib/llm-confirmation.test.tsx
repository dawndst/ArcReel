import { act, fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { confirmLlmCall, LlmCallCancelled, llmRequestSummary } from "./llm-confirmation";
import { API } from "@/api";

it("recognizes model jobs while leaving source browsing and manual writes direct", () => {
  for (const action of ["read","svt","review","understand","conclusions","scenes","group_summary","conclusion_evidence","shot_draft","speaker_attribution","selection_story"])
    expect(llmRequestSummary('/projects/demo/novel-workflow/run',{method:'POST',body:JSON.stringify({action,note_ids:['n']})})).toBeTruthy();
  expect(llmRequestSummary('/projects/demo/novel-workflow/run',{method:'POST',body:JSON.stringify({action:'questions',question_ai:false})})).toBeNull();
  expect(llmRequestSummary('/projects/demo/novel-workflow/run',{method:'POST',body:JSON.stringify({action:'questions',question_ai:true})})).toBeTruthy();
  for (const endpoint of ['/projects/demo/novel-workflow','/projects/demo/novel-workflow/conclusions/decide','/projects/demo/novel-workflow/dialogue-decision','/projects/demo/workflow-plan'])
    expect(llmRequestSummary(endpoint,{method:'POST'})).toBeNull();
});

it("does not send an actual task when confirmation is cancelled", async () => {
  const fetch = vi.spyOn(globalThis,'fetch');
  const request = API.runNoteWorkflow('demo','svt',['n'],'source');
  const rejected = expect(request).rejects.toBeInstanceOf(LlmCallCancelled);
  await screen.findByRole('dialog');
  expect(fetch).not.toHaveBeenCalled();
  await act(async () => { fireEvent.click(screen.getByRole('button',{name:'取消'})); });
  await rejected;
  expect(fetch).not.toHaveBeenCalled();
  fetch.mockRestore();
});

it("resolves approval once and closes the confirmation", async () => {
  const approve = confirmLlmCall('定向回查 · 1 章');
  await screen.findByRole('dialog');
  await act(async () => { fireEvent.click(screen.getByRole('button',{name:'确认调用 AI'})); });
  await expect(approve).resolves.toBeUndefined();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
