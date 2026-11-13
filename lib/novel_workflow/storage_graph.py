"""Relational projections committed with the authoritative workflow revision."""

import hashlib
import json


def project(conn, project_id, path, revision, payload, *, importing=False):
    def entity(kind, identity, basis=None):
        identity = str(identity)
        conn.execute(
            "INSERT INTO nw_entities(project_id,kind,entity_id,revision_id,basis) VALUES(?,?,?,?,?) "
            "ON CONFLICT(project_id,kind,entity_id) DO UPDATE SET revision_id=excluded.revision_id, "
            "basis=excluded.basis,deleted=0",
            (project_id, kind, identity, revision, basis),
        )
        return identity

    def link(kind, identity, target_kind, target, relation, basis=""):
        if target is None:
            return
        # Historical source versions may outlive their original adopted SVT/asset.
        # Such references remain explicit tombstones, never active identities.
        found = conn.execute(
            "SELECT 1 FROM nw_entities WHERE project_id=? AND kind=? AND entity_id=?",
            (project_id, target_kind, str(target)),
        ).fetchone()
        if not found:
            if importing or relation in {"depends_on", "asset_reference"}:
                conn.execute(
                    "INSERT INTO nw_entities(project_id,kind,entity_id,deleted) VALUES(?,?,?,1)",
                    (project_id, target_kind, str(target)),
                )
                if relation == "asset_reference":
                    # External labels are resolved by the existing project asset registry.
                    conn.execute(
                        "UPDATE nw_entities SET deleted=0 WHERE project_id=? AND kind=? AND entity_id=?",
                        (project_id, target_kind, str(target)),
                    )
            else:
                raise ValueError(f"Missing {target_kind} reference: {target}")
        conn.execute(
            "INSERT OR REPLACE INTO nw_links VALUES(?,?,?,?,?,?,?,?)",
            (project_id, path, kind, str(identity), target_kind, str(target), relation, basis or ""),
        )

    # Superseded rows stay addressable by their old references, but are not current.
    conn.execute(
        "UPDATE nw_entities SET deleted=1 WHERE project_id=? AND revision_id IN "
        "(SELECT id FROM nw_revisions WHERE project_id=? AND path=?)",
        (project_id, project_id, path),
    )
    conn.execute("DELETE FROM nw_links WHERE project_id=? AND document_path=?", (project_id, path))
    if path == "index.json":
        for note in payload["notes"]:
            entity("note", note["id"], note["basis"])
        for group in payload.get("groups", []):
            identity = entity("group", group["id"])
            for note in group["note_ids"]:
                link("group", identity, "note", note, "contains")
    elif path.startswith("notes/"):
        note_id = path.split("/")[1]
        identity = entity("note_version", payload["basis"], payload["basis"])
        link("note_version", identity, "note", note_id, "version_of")
        for name in ("events", "assets", "changes", "threads", "aliases"):
            for record in payload.get(name, []):
                kind = "event" if name == "events" else "observation"
                item = entity(kind, record["id"])
                link(kind, item, "note_version", identity, "source")
                for dialogue in record.get("dialogues", []):
                    did = entity("dialogue", dialogue["id"])
                    link("dialogue", did, "event", item, "belongs_to")
    elif path == "svts.json":
        conn.execute("DELETE FROM nw_note_svt WHERE project_id=?", (project_id,))
        for svt in payload["svts"]:
            identity = entity("svt", svt["id"])
            if svt.get("stale"):
                conn.execute(
                    "UPDATE nw_entities SET deleted=1 WHERE project_id=? AND kind='svt' AND entity_id=?",
                    (project_id, identity),
                )
            for note in svt["note_ids"]:
                link("svt", identity, "note", note, "depends_on", payload.get("note_bases", {}).get(note))
                if not svt.get("stale"):
                    conn.execute(
                        "INSERT INTO nw_note_svt(project_id,note_id,svt_id) VALUES(?,?,?)", (project_id, note, identity)
                    )
            for event in svt["event_ids"]:
                link("svt", identity, "event", event, "contains")
            for kind in ("climaxes", "payoffs"):
                for moment in svt.get(kind, []):
                    mid = hashlib.sha256(
                        json.dumps(
                            [identity, kind, sorted(moment["event_ids"]), sorted(moment["dialogue_ids"])],
                            ensure_ascii=False,
                        ).encode()
                    ).hexdigest()[:24]
                    entity("moment", mid)
                    link("moment", mid, "svt", identity, kind)
                    for event in moment["event_ids"]:
                        link("moment", mid, "event", event, "source")
                    for dialogue in moment["dialogue_ids"]:
                        link("moment", mid, "dialogue", dialogue, "quotes")
    elif path == "scene_library.json":
        for batch in payload["batches"].values():
            bid = entity("scene_batch", batch["basis"], batch["basis"])
            for basis in batch.get("note_bases", {}).values():
                link("scene_batch", bid, "note_version", basis, "depends_on", basis)
            for scene in batch["scenes"]:
                sid = entity("scene", scene["id"])
                link("scene", sid, "scene_batch", bid, "belongs_to")
                for shot in scene["shots"]:
                    shid = entity("shot", shot["id"])
                    link("shot", shid, "scene", sid, "belongs_to")
                    for event in shot.get("event_ids", []):
                        link("shot", shid, "event", event, "depends_on")
                    for segment in shot.get("segments", []):
                        for field, kind in (
                            ("characters_in_scene", "character"),
                            ("scenes", "scene_asset"),
                            ("props", "prop"),
                        ):
                            for ref in segment.get(field, []):
                                link("shot", shid, kind, ref, "asset_reference")
                    for name in ("appearance_notes", "attribution_history", "edit_history"):
                        if shot.get(name):
                            did = entity("decision", shid + ":" + name)
                            link("decision", did, "shot", shid, "applies_to")
            for key in batch.get("craft_decisions", {}):
                did = entity("decision", bid + ":" + key)
                link("decision", did, "scene_batch", bid, "applies_to")
    else:
        identity = entity("document", path, payload.get("basis") if isinstance(payload, dict) else None)
        if isinstance(payload, dict):
            for basis in payload.get("note_bases", {}).values():
                link("document", identity, "note_version", basis, "depends_on", basis)
            if payload.get("reading_basis"):
                link(
                    "document",
                    identity,
                    "note_version",
                    payload["reading_basis"],
                    "depends_on",
                    payload["reading_basis"],
                )
