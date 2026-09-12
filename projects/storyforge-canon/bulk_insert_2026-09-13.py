"""One-time bulk backfill of SEDB storyforge-canon from stories written since 2026-08-28.

Run from this directory: python bulk_insert_2026-09-13.py <meta.json> <batch1.json> [<batch2.json> ...]
<meta.json> is a JSON array of {id, author, titleEn} (from content/stories.ts) used to fill in
each entity's author/story_title fields. The remaining args are the character/setting batch files.
Idempotent: skips any entity id that already exists, so it's safe to re-run.
Characters with pronoun == "NO_PRONOUN" are NOT inserted (the schema requires 他/她) —
they're printed at the end instead, for the record.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from canon import open_canon, _set, _slug

BY = "Colophon"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python bulk_insert_2026-09-13.py <meta.json> <batch.json> [<batch.json> ...]")
        return 1

    with open(argv[0], "r", encoding="utf-8") as f:
        meta_list = json.load(f)
    meta = {m["id"]: m for m in meta_list}

    stories: dict = {}
    for path in argv[1:]:
        with open(path, "r", encoding="utf-8") as f:
            stories.update(json.load(f))

    db, fields, entities = open_canon()
    existing_ids = {e["id"] for e in entities.list_entities(limit=5000)}

    added_chars = 0
    added_settings = 0
    skipped_existing = 0
    no_pronoun: list[str] = []

    def now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for story_id, data in stories.items():
        story_meta = meta.get(story_id, {})
        story_author = story_meta.get("author", "")
        story_title = story_meta.get("titleEn", "")
        for ch in data.get("characters", []):
            if ch["pronoun"] == "NO_PRONOUN":
                no_pronoun.append(f"{story_id}: {ch['name_en']} / {ch['name_zh']}")
                continue
            entity_id = _slug(ch["name_en"], story_id)
            if entity_id in existing_ids:
                skipped_existing += 1
                continue
            entities.create_entity(label=f"{ch['name_en']} / {ch['name_zh']}", kind="character", entity_id=entity_id)
            _set(entities, entity_id, "name_en", ch["name_en"], source=BY)
            _set(entities, entity_id, "name_zh", ch["name_zh"], source=BY)
            _set(entities, entity_id, "pronoun", ch["pronoun"], source=BY)
            _set(entities, entity_id, "kind_detail", ch.get("role", ""), source=BY)
            _set(entities, entity_id, "story_id", story_id, source=BY)
            _set(entities, entity_id, "story_title_en", story_title, source=BY)
            _set(entities, entity_id, "author", story_author, source=BY)
            _set(entities, entity_id, "status", "active", source=BY)
            _set(entities, entity_id, "description", ch.get("description_en", ""), source=BY)
            _set(entities, entity_id, "notes", ch.get("description_zh", ""), source=BY)
            _set(entities, entity_id, "added_by", BY, source=BY)
            _set(entities, entity_id, "added_at", now(), source=BY)
            existing_ids.add(entity_id)
            added_chars += 1

        for st in data.get("settings", []):
            entity_id = _slug(st["name_en"], story_id)
            if entity_id in existing_ids:
                skipped_existing += 1
                continue
            entities.create_entity(label=f"{st['name_en']} / {st['name_zh']}", kind="setting", entity_id=entity_id)
            _set(entities, entity_id, "name_en", st["name_en"], source=BY)
            _set(entities, entity_id, "name_zh", st["name_zh"], source=BY)
            _set(entities, entity_id, "kind_detail", st.get("type", ""), source=BY)
            _set(entities, entity_id, "story_id", story_id, source=BY)
            _set(entities, entity_id, "story_title_en", story_title, source=BY)
            _set(entities, entity_id, "author", story_author, source=BY)
            _set(entities, entity_id, "status", "active", source=BY)
            _set(entities, entity_id, "description", st.get("description_en", ""), source=BY)
            _set(entities, entity_id, "notes", st.get("description_zh", ""), source=BY)
            _set(entities, entity_id, "added_by", BY, source=BY)
            _set(entities, entity_id, "added_at", now(), source=BY)
            existing_ids.add(entity_id)
            added_settings += 1

    print(f"stories processed: {len(stories)}")
    print(f"characters added: {added_chars}")
    print(f"settings added: {added_settings}")
    print(f"skipped (already existed): {skipped_existing}")
    print(f"no-pronoun characters NOT inserted ({len(no_pronoun)}):")
    for line in no_pronoun:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
