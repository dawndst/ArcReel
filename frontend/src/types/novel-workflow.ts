export interface ClaimStatus { claim_type?: "fact" | "statement" | "inference" | "vision" | "adaptation" | "unverified"; perspective?: string; source_kind?: "narrative" | "annotation" | "unknown" }
export interface NoteEvidence { source_file: string; start: number; end: number; quote: string; note_id: string }
export interface NoteAsset extends ClaimStatus { asset_code?: string; asset_id?: string; asset_name?: string; asset_missing?: boolean; variant?: string; id: string; kind: "character" | "scene" | "prop"; name: string; identity_scope: string; description: string; evidence: NoteEvidence }
export interface NoteChange extends ClaimStatus { id: string; character: string; dimension: string; before: string; after: string; story_time: string; evidence: NoteEvidence }
export interface NoteDialogue extends ClaimStatus { id: string; speaker: string; quote: string; value: string; evidence: NoteEvidence }
export interface NoteEvent extends ClaimStatus { id: string; title: string; cause: string; conflict: string; action: string; outcome: string; open_thread: string; dialogues: NoteDialogue[]; evidence: NoteEvidence }
export interface ChapterNote {
  svt_id?: string | null; svt_title?: string | null; svt_status?: string; svt_candidates?: SVTCandidate[];
  in_scope?: boolean;
  id: string; order: number; title: string; volume: string; chapter: string; chars: number; basis: string; needs_review?: boolean;
  sections: { source_file: string; start: number; end: number; title: string }[];
  status?: "read" | "unread" | "stale" | "outdated";
  reading?: { overview?: NoteOverview; aliases?: NoteAlias[]; relations?: NoteRelation[]; threads?: NoteThread[]; highlights?: NoteHighlight[]; basis: string; summaries: string[]; assets: NoteAsset[]; changes: NoteChange[]; events: NoteEvent[]; questions: string[] } | null;
}
export interface NoteGroup { usage?: "reference" | "candidate"; synopsis?: NoteOverview; summary_stale?: boolean; id: string; title: string; note_ids: string[]; source_basis: string; created_by: string }
export interface NovelSVT {
  id: string; title: string; summary: string; note_ids: string[]; status: "open" | "closed"; mainline_reason: string; stale?: boolean;
  breakdown_status?: string;
  climaxes: SVTMoment[]; payoffs: SVTMoment[];
  dialogues: NoteDialogue[]; evidence: NoteEvidence[];
}
export interface NovelWorkflow {
  scene_batches?: SceneLibraryBatch[];
  pending_assemblies?: { episode: number; title: string; source_basis: string; request_id: string; shot_ids: string[] }[];
  scope?: { configured: boolean; note_ids: string[]; available_count: number; read_count: number; total_count: number; mode: "ongoing" };
  settings?: { summary_max_chars: number; understanding_enabled: boolean };
  understanding?: { links: UnderstandingLink[]; reports: UnderstandingReport[] };
  initialized: boolean; source_basis?: string; notes: ChapterNote[]; groups: NoteGroup[]; stale: boolean;
  ledger?: NovelLedger | null; reviews?: NovelScopeReview[];
  svts: NovelSVT[]; svt_stale?: boolean; suggestions?: string[];
  progress: { phase: string; total: number; done: number; note_id?: string; part?: number; parts?: number; error?: string } | null;
}
export interface ChapterPreview { source_basis: string; notes: ChapterNote[]; excluded: { title: string; start: number; end: number }[] }
export interface NoteFact extends ClaimStatus { id: string; evidence: NoteEvidence }
export interface NoteAlias extends NoteFact { name: string; alias: string; identity_scope: string }
export interface NoteRelation extends NoteFact { subject: string; target: string; relation: string; previous: string; trigger: string; story_time: string }
export interface NoteThread extends NoteFact { kind: "seed" | "resolution"; description: string; seed_id: string | null; resolutions?: NoteThread[] }
export interface NoteHighlight extends NoteFact { kind: string; description: string; beneficiary: string; intensity: string; reason: string; visual: string }
export interface NoteOverview { summary: string; cause: string; conflict: string; action: string; outcome: string; hook: string; evidence_ids: string[]; questions: string[] }
export interface NovelLedger {
  characters: { id: string; name: string; identity_scope: string; aliases: NoteAlias[]; appear: string[]; mentions: NoteAsset[]; changes: NoteChange[]; relations: NoteRelation[] }[];
  aliases: NoteAlias[]; relations: NoteRelation[]; changes: NoteChange[]; threads: NoteThread[]; unmatched_resolutions: NoteThread[];
}
export interface AdaptationAdvice { action: "keep" | "compress" | "combine" | "omit_candidate"; note_ids: string[]; evidence_ids: string[]; reason: string; character_impact: string; thread_impact: string; dialogue_impact: string; preserve: string }
export interface ReviewSection { theme: string; mainline: string; advice: AdaptationAdvice[]; questions: string[] }
export interface NovelScopeReview { conclusion?: { theme: string; mainline: string; must_preserve: string; adaptation_risks: string; evidence_ids: string[] }; id: string; note_ids: string[]; stale: boolean; sections: ReviewSection[]; overview: ReviewSection[]; created_at: string; scope_kind: string; evidence: Record<string, NoteFact> }

export interface UnderstandingLink extends ClaimStatus {
  id: string; kind: "identity" | "thread_resolution" | "state" | "world_rule" | "causal" | "contradiction";
  subject: string; description: string; status: "supported" | "uncertain"; story_time: string;
  story_start_note_id: string | null; story_end_note_id: string | null;
  note_ids: string[]; evidence: NoteEvidence[]; revealed_at: { note_id: string; order: number; offset: number };
}
export interface UnderstandingReport {
  id: string; stale: boolean; created_at: string; selected_note_ids: string[]; searched_note_count: number;
  inspected_note_ids: string[]; unread_inspected_note_ids: string[];
  unresolved: { note_id: string; question: string }[];
  inspections: { anchor_note_id: string; queries: string[]; note_ids: string[]; round: number }[];
}

export interface LibrarySegment { duration_seconds: number; scene_description: string; characters_in_scene: string[]; scenes: string[]; props: string[]; utterances: { kind: string; speaker: string | null; text: string }[] }
export interface LibraryShot { revision?: string; id: string; title: string; segments: LibrarySegment[]; evidence: NoteEvidence }
export interface LibraryScene { id: string; title: string; location: string; time: string; purpose: string; shots: LibraryShot[] }
export interface SceneRevision { id: string; scene_index: number; shot_index: number; segment_index: number | null; field: string; before: string; after: string; reason: string; source_quote: string; applied: boolean }
export interface SceneLibraryBatch { note_order?: number; part?: number; review_revision?: string; review?: { revisions: SceneRevision[]; unresolved: string[] }; basis: string; note_id: string; stale: boolean; scenes: LibraryScene[]; skipped_reason: string }

export interface SVTCandidate { candidate_id: string; existing_id: string | null; title: string; summary: string; reason: string }
export interface SVTMoment { scene: string; reason: string; note_ids: string[]; dialogue_ids: string[]; dialogues: NoteDialogue[]; evidence: NoteEvidence[] }
export interface PromptRule { id: string; title: string; purpose: string; category: string; content: string; source: "project" | "default"; location: string; version: string }
