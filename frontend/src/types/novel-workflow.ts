export interface NoteEvidence { source_file: string; start: number; end: number; quote: string; note_id: string }
export interface NoteAsset { id: string; kind: "character" | "scene" | "prop"; name: string; identity_scope: string; description: string; evidence: NoteEvidence }
export interface NoteChange { id: string; character: string; dimension: string; before: string; after: string; story_time: string; evidence: NoteEvidence }
export interface NoteDialogue { id: string; speaker: string; quote: string; value: string; evidence: NoteEvidence }
export interface NoteEvent { id: string; title: string; cause: string; conflict: string; action: string; outcome: string; open_thread: string; dialogues: NoteDialogue[]; evidence: NoteEvidence }
export interface ChapterNote {
  id: string; order: number; title: string; volume: string; chapter: string; chars: number; basis: string; needs_review?: boolean;
  sections: { source_file: string; start: number; end: number; title: string }[];
  status?: "read" | "unread" | "stale";
  reading?: { basis: string; summaries: string[]; assets: NoteAsset[]; changes: NoteChange[]; events: NoteEvent[]; questions: string[] } | null;
}
export interface NoteGroup { id: string; title: string; note_ids: string[]; source_basis: string; created_by: string }
export interface NovelSVT {
  id: string; title: string; summary: string; note_ids: string[]; status: "open" | "closed"; mainline_reason: string; stale?: boolean;
  climaxes: { description: string; reason: string }[]; payoffs: { description: string; reason: string }[];
  dialogues: NoteDialogue[]; evidence: NoteEvidence[];
}
export interface NovelWorkflow {
  initialized: boolean; source_basis?: string; notes: ChapterNote[]; groups: NoteGroup[]; stale: boolean;
  svts: NovelSVT[]; svt_stale?: boolean; suggestions?: string[];
  progress: { phase: string; total: number; done: number; note_id?: string; part?: number; parts?: number; error?: string } | null;
}
export interface ChapterPreview { source_basis: string; notes: ChapterNote[]; excluded: { title: string; start: number; end: number }[] }
