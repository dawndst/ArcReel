export interface EpisodeGuide {
  summary: string;
  story_beats: string[];
  character_changes: string[];
  adaptation_value: string;
  recommendation: "keep" | "compress" | "merge";
  recommendation_reason: string;
  ending_hook: string;
}
export interface EpisodeGuideResponse {
  guide: EpisodeGuide | null;
  stale: boolean;
  running?: boolean;
  source_range: unknown;
}
