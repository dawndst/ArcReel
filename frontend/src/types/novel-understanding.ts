export interface NovelReport {
  id: string;
  episode: number;
  next_episode: number | null;
  decision: {
    action: "keep" | "revise" | "merge_next";
    reason: string;
    title: string;
    hook: string;
    story_beats: string[];
    must_film: string[];
    compress: string[];
    omit: string[];
    preserve_setup: string[];
  };
  evidence: { source_file: string; start: number; end: number; quote: string }[];
}
export interface NovelStatus {
  enabled: boolean;
  supported?: boolean;
  phase: string;
  coverage?: number;
  completed_chunks: number;
  total_chunks: number;
  facts_count?: number;
  error?: string | null;
  reports: NovelReport[];
}
export interface NovelAdoption {
  status: "applied" | "confirmation_required";
  impact?: { restaled: number[]; retired: number[]; removed: number[]; merged_units: number; text: string };
}
