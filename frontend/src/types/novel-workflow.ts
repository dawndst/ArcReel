export interface NoteEvidence { source_file: string; start: number; end: number; quote: string; note_id: string }
export interface NoteAsset { id: string; kind: "character" | "scene" | "prop"; name: string; identity_scope: string; description: string; evidence: NoteEvidence }
export interface NoteChange { id: string; character: string; dimension: string; before: string; after: string; story_time: string; evidence: NoteEvidence }
export interface NoteDialogue { id: string; speaker: string; quote: string; value: string; evidence: NoteEvidence }
export interface NoteEvent { id: string; title: string; cause: string; conflict: string; action: string; outcome: string; open_thread: string; dialogues: NoteDialogue[]; evidence: NoteEvidence }
export interface ChapterNote {
  id: string; order: number; title: string; volume: string; chapter: string; chars: number; basis: string; needs_review?: boolean;
  sections: { source_file: string; start: number; end: number; title: string }[];
  status?: "read" | "unread" | "stale" | "outdated";
  reading?: { overview?: NoteOverview; aliases?: NoteAlias[]; relations?: NoteRelation[]; threads?: NoteThread[]; highlights?: NoteHighlight[]; basis: string; summaries: string[]; assets: NoteAsset[]; changes: NoteChange[]; events: NoteEvent[]; questions: string[] } | null;
}
export interface NoteGroup { id: string; title: string; note_ids: string[]; source_basis: string; created_by: string }
export interface NovelSVT {
  id: string; title: string; summary: string; note_ids: string[]; status: "open" | "closed"; mainline_reason: string; stale?: boolean;
  climaxes: { description: string; reason: string }[]; payoffs: { description: string; reason: string }[];
  dialogues: NoteDialogue[]; evidence: NoteEvidence[];
}
export interface NovelWorkflow {
  initialized: boolean; source_basis?: string; notes: ChapterNote[]; groups: NoteGroup[]; stale: boolean;
  ledger?: NovelLedger | null; reviews?: NovelScopeReview[];
  svts: NovelSVT[]; svt_stale?: boolean; suggestions?: string[];
  progress: { phase: string; total: number; done: number; note_id?: string; part?: number; parts?: number; error?: string } | null;
}
export interface ChapterPreview { source_basis: string; notes: ChapterNote[]; excluded: { title: string; start: number; end: number }[] }
export interface NoteFact { id: string; evidence: NoteEvidence }
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
