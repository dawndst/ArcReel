import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { DramaScene } from "@/types";
import { ShotList } from "./ShotList";
import { shotHierarchyCode } from "@/utils/shot-hierarchy";

const scene = (id: number, scn: number, shot: number, seg: number | null): DramaScene => ({
  scene_id: `E1S0${id}`, scene_number: scn, shot_number: shot, segment_number: seg,
  duration_seconds: 12, segment_break: false, characters_in_scene: [],
  image_prompt: null, video_prompt: null,
});
it("groups narrative scenes and distinguishes SEG from new camera shots", () => {
  render(<ShotList segments={[scene(1,1,1,1), scene(2,1,1,2), scene(3,1,2,null), scene(4,2,1,null)]} selectedIndex={0} onSelect={vi.fn()} contentMode="drama" projectName="demo" collapsed={false} onToggleCollapse={vi.fn()} />);
  expect(screen.getByText("EP01-SCN001")).toBeInTheDocument();
  expect(screen.getByText("EP01-SCN002")).toBeInTheDocument();
  expect(screen.getByText("EP01-SCN001-SH001-SEG1")).toBeInTheDocument();
  expect(screen.getByText("EP01-SCN001-SH001-SEG2")).toBeInTheDocument();
  expect(screen.getByText("EP01-SCN001-SH002")).toBeInTheDocument();
  const search = screen.getByRole("searchbox");
  fireEvent.change(search, {target:{value:"SEG2"}});
  expect(screen.queryByText("EP01-SCN001-SH001-SEG1")).not.toBeInTheDocument();
  expect(screen.getByText("EP01-SCN001-SH001-SEG2")).toBeInTheDocument();
});
it("does not invent hierarchy for old scripts and keeps unsplit shots free of SEG suffixes", () => {
  expect(shotHierarchyCode({scene_id:"E1S01"})).toBeNull();
  expect(shotHierarchyCode(scene(1,2,3,null))).toBe("EP01-SCN002-SH003");
});
