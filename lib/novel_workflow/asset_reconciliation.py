"""Cascade native asset identity edits into unassembled scene candidates.

Caller owns the project metadata lock and includes ``path`` in its formal write
transaction. Dialogue and creative decisions are never regenerated here.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import store
from lib.novel_workflow.shot_production import asset_bindings, planning_inputs


@dataclass
class ReferenceRefresh:
    path: Path
    before: dict
    payload: dict
    references: int = 0

    def apply(self):
        if self.before == self.payload:
            return
        store.write(
            store.root(self.path.parent.parent) / "history" / f"asset-references-{digest(self.before)}.json",
            self.before,
        )
        store.write(self.path, self.payload)


def plan_reference_refresh(path, before, after, rewrite=None, kind=None):
    """Plan both preview and execution; only carry an already current basis forward."""
    file = store.root(path) / "scene_library.json"
    payload = load_json(file) if file.exists() else {"batches": {}}
    plan = ReferenceRefresh(file, deepcopy(payload), payload)
    if not payload["batches"]:
        return plan
    readings = store.valid_readings(path, store.state(path))
    rules = store.effective_rule(path, "shot_production")
    fields = {"character": "characters_in_scene", "scene": "scenes", "prop": "props"}
    for batch in payload["batches"].values():
        reading = readings.get(batch["note_id"])
        shots = {sh["id"]: sh for sc in batch["scenes"] for sh in sc["shots"]}
        ctx = batch.get("production_context")
        current = bool(
            reading and ctx and batch.get("production_basis") == planning_inputs(ctx, rules, shots, before, reading)[2]
        )
        for shot in shots.values():
            if rewrite and kind in fields:
                for segment in shot["segments"]:
                    field = fields[kind]
                    values = []
                    for name in segment.get(field, []):
                        replacement = rewrite(name, False)
                        plan.references += int(replacement is not None and replacement != name)
                        values.append(replacement if replacement is not None else name)
                    segment[field] = list(dict.fromkeys(values))
                    if kind == "character":
                        for utterance in segment.get("utterances", []):
                            name = utterance.get("speaker")
                            replacement = rewrite(name, True) if name else None
                            if replacement is not None and replacement != name:
                                utterance["speaker"] = replacement
                                plan.references += 1
            if reading and shot.get("production"):
                shot["production"]["assets"] = asset_bindings(after, reading, shot)
        if current:
            batch["production_basis"] = planning_inputs(ctx, rules, shots, after, reading)[2]
    return plan
