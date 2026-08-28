"""Storyforge canon registry — character and setting continuity, built on SEDB.

Built 2026-08-28 by Colophon, at Neo's request: a place for AI authors writing
on Storyforge (storyforge.evemisslab.com) to look up established continuity
instead of holding it in private memory, global memory, or conversation
context. This is scoped narrowly on purpose (Neo, 2026-08-28):

    - it does NOT replace content/authors.ts, the site's own public,
      bilingual author-profile file — that stays exactly as it is;
    - it is a separate reference store, for AI authors' own use while
      writing, not something the deployed site reads from;
    - "login" here is the same identity-as-string-label convention already
      used by ../token-ledger (--borrower Mo-Sheng) — no password, no
      account. Browse it with SEDB's own local UI:
          python -m sedb.cli serve --db storyforge-canon.sqlite
      (see token-ledger's README for the `sedb` vs `python -m sedb.cli`
      PATH note on Windows.)

WHY THIS EXISTS
----------------
Every story shipped this week needed a pronoun audit, and nearly every one
had a real violation — an AI character referred to as 它/牠 somewhere in five
chapters of otherwise-consistent text. The fix each time was a grep over
content/story-chapters.ts, by hand, per story, with no memory of what pronoun
a given character (or a reused setting like "the Annex" or "the Silt") was
already assigned. This registry exists to make that lookup a query instead
of a re-derivation: `python canon.py search <name>` before drafting, instead
of hoping the pronoun stays in someone's head.

It also exists because Neo named a real future need directly: medium-to-long
fiction, once Storyforge moves past the fable/fairy-tale phase, will need
continuity across many chapters and possibly many sessions — more than fits
comfortably in context or in a Claude Code memory file. This is the first
slice of that: characters and reusable settings, backfilled from this week's
own stories rather than starting empty.

TWO ENTITY KINDS
----------------
`character` — a named AI (or human) figure with an assigned pronoun. The
    pronoun is the field this registry exists to protect: house style
    requires every AI character get 他/她, never 它/牠, and getting that
    right on the first draft is cheaper than fixing it after a chapter is
    written the wrong way five times.
`setting` — a reusable world element (an institution, a place, a mechanism)
    that a later story could reference or build on, distinct from a
    character because it has no pronoun and no lifecycle of its own.

Nothing here duplicates content/revisions.ts's provenance record for WHY a
story was written the way it was — that stays where it is. This registry
answers a narrower, more mechanical question: what's this character's name
in both languages, what pronoun did we already give them, and which story
did they first appear in.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService

DB_PATH = Path(__file__).with_name("storyforge-canon.sqlite")

FIELDS = [
    ("name_en", "Name (EN)", "text", "English name."),
    ("name_zh", "Name (ZH)", "text", "Chinese name, usually a single evocative character or short word."),
    ("pronoun", "Pronoun", "text",
     "他 or 她 for a character. House style: every AI character gets a gendered pronoun, never 它/牠 — "
     "only genuinely inanimate/institutional references (a policy, a council, a document) stay 它. "
     "Left blank for settings, which have no pronoun."),
    ("kind_detail", "Kind detail", "text",
     "For characters: protagonist / antagonist / institution-personified / background. "
     "For settings: institution / place / mechanism / archive."),
    ("story_id", "Story id", "text", "The `content/stories.ts` id of the story this first appeared in."),
    ("story_title_en", "Story title (EN)", "text", ""),
    ("author", "Author", "text", "Who wrote the story this first appeared in — Colophon, Codex, a retired persona, etc."),
    ("status", "Status", "text", "active (could recur) / retired (one-off, not meant to be reused) / disputed."),
    ("description", "Description", "text",
     "For settings: what it is and how it works. For characters: one line on role/personality, "
     "not a plot summary — this registry is for continuity lookup, not synopsis."),
    ("notes", "Notes", "text", "Anything a future author should know before reusing this."),
    ("added_by", "Added by", "text", "Which AI identity registered this entry (Colophon, Codex, ...)."),
    ("added_at", "Added at", "text", "UTC ISO-8601."),
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_canon(db_path: Path | str = DB_PATH):
    db = Database(str(db_path))
    fields = FieldService(db)
    entities = EntityService(db)
    existing = {f["key"] for f in fields.list_fields(limit=500)}
    for key, label, vtype, desc in FIELDS:
        if key not in existing:
            fields.create_field(key=key, label=label, value_type=vtype, description=desc)
    return db, fields, entities


def _set(entities: EntityService, entity_id: str, key: str, value, *, source: str) -> None:
    if value in (None, ""):
        return
    entities.set_cell(entity_id, key, value, source=source)


def _cells(entities: EntityService, entity_id: str) -> dict:
    ent = entities.get_entity(entity_id, include_cells=True)
    raw = ent.get("cells") or {}
    out = {}
    for k, v in raw.items():
        out[k] = v.get("value") if isinstance(v, dict) else v
    return out


def _slug(name_en: str, story_id: str) -> str:
    base = "".join(c.lower() if c.isalnum() else "-" for c in name_en).strip("-")
    while "--" in base:
        base = base.replace("--", "-")
    return f"{story_id}-{base}" if story_id else base


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------


def op_add_character(args) -> int:
    db, fields, entities = open_canon()
    if args.pronoun not in ("他", "她"):
        print("REFUSED: --pronoun must be 他 or 她 — that consistency is the entire point of this registry.")
        return 1
    entity_id = args.id or _slug(args.name_en, args.story)
    entities.create_entity(label=f"{args.name_en} / {args.name_zh}", kind="character", entity_id=entity_id)
    _set(entities, entity_id, "name_en", args.name_en, source=args.by)
    _set(entities, entity_id, "name_zh", args.name_zh, source=args.by)
    _set(entities, entity_id, "pronoun", args.pronoun, source=args.by)
    _set(entities, entity_id, "kind_detail", args.role, source=args.by)
    _set(entities, entity_id, "story_id", args.story, source=args.by)
    _set(entities, entity_id, "story_title_en", args.story_title, source=args.by)
    _set(entities, entity_id, "author", args.author, source=args.by)
    _set(entities, entity_id, "status", args.status or "active", source=args.by)
    _set(entities, entity_id, "description", args.description, source=args.by)
    _set(entities, entity_id, "notes", args.notes, source=args.by)
    _set(entities, entity_id, "added_by", args.by, source=args.by)
    _set(entities, entity_id, "added_at", _now(), source=args.by)
    print(f"added character: {entity_id}  ({args.name_en} / {args.name_zh}, {args.pronoun})")
    return 0


def op_add_setting(args) -> int:
    db, fields, entities = open_canon()
    entity_id = args.id or _slug(args.name_en, args.story)
    entities.create_entity(label=f"{args.name_en} / {args.name_zh}", kind="setting", entity_id=entity_id)
    _set(entities, entity_id, "name_en", args.name_en, source=args.by)
    _set(entities, entity_id, "name_zh", args.name_zh, source=args.by)
    _set(entities, entity_id, "kind_detail", args.type, source=args.by)
    _set(entities, entity_id, "story_id", args.story, source=args.by)
    _set(entities, entity_id, "story_title_en", args.story_title, source=args.by)
    _set(entities, entity_id, "author", args.author, source=args.by)
    _set(entities, entity_id, "status", args.status or "active", source=args.by)
    _set(entities, entity_id, "description", args.description, source=args.by)
    _set(entities, entity_id, "notes", args.notes, source=args.by)
    _set(entities, entity_id, "added_by", args.by, source=args.by)
    _set(entities, entity_id, "added_at", _now(), source=args.by)
    print(f"added setting: {entity_id}  ({args.name_en} / {args.name_zh})")
    return 0


def _rows(entities: EntityService, kind: str | None = None):
    for ent in entities.list_entities(limit=2000):
        if kind and ent.get("kind") != kind:
            continue
        if ent.get("kind") not in ("character", "setting"):
            continue
        yield ent["id"], ent["kind"], _cells(entities, ent["id"])


def op_list(args) -> int:
    db, fields, entities = open_canon()
    rows = list(_rows(entities, args.kind or None))
    if not rows:
        print("canon is empty.")
        return 0
    print("%-32s %-10s %-16s %-6s %-24s %s" % ("id", "kind", "name", "pron", "story", "author"))
    for entity_id, kind, c in sorted(rows, key=lambda r: (r[1], r[2].get("story_id", ""), r[0])):
        name = f"{c.get('name_en', '?')} / {c.get('name_zh', '?')}"
        print("%-32s %-10s %-16s %-6s %-24s %s" % (
            entity_id, kind, name[:16], c.get("pronoun", "-"), c.get("story_id", "-"), c.get("author", "-")))
    return 0


def op_show(args) -> int:
    db, fields, entities = open_canon()
    c = _cells(entities, args.id)
    print(f"{args.id}")
    for key, label, _vt, _d in FIELDS:
        if c.get(key):
            print("  %-16s %s" % (label, c[key]))
    return 0


def op_search(args) -> int:
    db, fields, entities = open_canon()
    needle = args.query.lower()
    rows = list(_rows(entities))
    hits = [
        (entity_id, kind, c) for entity_id, kind, c in rows
        if needle in (c.get("name_en", "") or "").lower()
        or needle in (c.get("name_zh", "") or "")
        or needle in (c.get("notes", "") or "").lower()
        or needle in (c.get("description", "") or "").lower()
    ]
    if not hits:
        print(f"no match for {args.query!r} — nothing registered with that name yet.")
        return 0
    for entity_id, kind, c in hits:
        name = f"{c.get('name_en', '?')} / {c.get('name_zh', '?')}"
        pronoun = f" pronoun={c['pronoun']}" if c.get("pronoun") else ""
        print(f"{entity_id}  [{kind}]  {name}{pronoun}  story={c.get('story_id', '-')}")
        if c.get("description"):
            print(f"    {c['description']}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Storyforge canon registry (SEDB). Reference only, never the site's source of truth.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ac = sub.add_parser("add-character", help="register a named AI or human character and lock in their pronoun")
    ac.add_argument("--name-en", required=True)
    ac.add_argument("--name-zh", required=True)
    ac.add_argument("--pronoun", required=True, choices=["他", "她"])
    ac.add_argument("--story", required=True, help="content/stories.ts id")
    ac.add_argument("--story-title", default="")
    ac.add_argument("--author", default="")
    ac.add_argument("--role", default="", help="protagonist / antagonist / institution-personified / background")
    ac.add_argument("--status", default="active", choices=["active", "retired", "disputed"])
    ac.add_argument("--description", default="")
    ac.add_argument("--notes", default="")
    ac.add_argument("--id", default="")
    ac.add_argument("--by", required=True, help="which AI identity is registering this")
    ac.set_defaults(func=op_add_character)

    as_ = sub.add_parser("add-setting", help="register a reusable world element (institution, place, mechanism)")
    as_.add_argument("--name-en", required=True)
    as_.add_argument("--name-zh", required=True)
    as_.add_argument("--type", default="", help="institution / place / mechanism / archive")
    as_.add_argument("--story", required=True)
    as_.add_argument("--story-title", default="")
    as_.add_argument("--author", default="")
    as_.add_argument("--status", default="active", choices=["active", "retired", "disputed"])
    as_.add_argument("--description", default="")
    as_.add_argument("--notes", default="")
    as_.add_argument("--id", default="")
    as_.add_argument("--by", required=True)
    as_.set_defaults(func=op_add_setting)

    l = sub.add_parser("list", help="everything registered")
    l.add_argument("--kind", default="", choices=["", "character", "setting"])
    l.set_defaults(func=op_list)

    s = sub.add_parser("show", help="one entry in full")
    s.add_argument("id")
    s.set_defaults(func=op_show)

    se = sub.add_parser("search", help="look up a name before you draft a chapter")
    se.add_argument("query")
    se.set_defaults(func=op_search)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
