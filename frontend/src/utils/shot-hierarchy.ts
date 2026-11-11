import { episodePosition, type EpisodeLedger } from "@/utils/episode-display";

export const MAX_SEGMENT_SECONDS = 15;

export interface ShotPlacement {
  scene_number?: number | null;
  shot_number?: number | null;
  segment_number?: number | null;
}

export function shotHierarchyCode(value: unknown, ledger?: EpisodeLedger): string | null {
  if (!value || typeof value !== "object" || !("scene_number" in value) || !("shot_number" in value)) return null;
  if (typeof value.scene_number !== "number" || typeof value.shot_number !== "number") return null;
  const id = "scene_id" in value && typeof value.scene_id === "string" ? value.scene_id : "";
  const episode = id.match(/^E(\d+)/)?.[1];
  const position = episode && ledger?.length ? episodePosition(ledger, Number(episode)) : episode;
  const prefix = position != null ? `EP${String(position).padStart(2, "0")}-` : "";
  const segment = "segment_number" in value && typeof value.segment_number === "number" ? `-SEG${value.segment_number}` : "";
  return `${prefix}SCN${String(value.scene_number).padStart(3, "0")}-SH${String(value.shot_number).padStart(3, "0")}${segment}`;
}
