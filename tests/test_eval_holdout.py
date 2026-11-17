"""H eval set v1: the hold-out file covers whole units and agrees with the manifest (docs/h_eval_set_plan.md)."""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rows(p):
    return [json.loads(line) for line in (ROOT / p).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_holdout_covers_whole_units_and_manifest():
    entries = rows("data/index/entries.jsonl")
    holdout = rows("data/index/eval_holdout.jsonl")
    manifest = rows("data/eval/h_eval_v1/manifest.jsonl")
    flagged = {r["source_id"] for r in rows("data/eval/h_eval_v1/flags.jsonl")}
    by_unit = defaultdict(set)
    for e in entries:
        by_unit[e["source_id"]].add(e["entry_id"])
    held = defaultdict(set)
    for h in holdout:
        held[h["source_id"]].add(h["entry_id"])
    for unit, ids in held.items():
        assert ids == by_unit[unit], f"{unit}: hold-out must list every page of the unit"
    selected = {h["entry_id"] for h in holdout if h["selected"]}
    assert selected == {r["entry_id"] for r in manifest}
    assert not flagged & {r["source_id"] for r in manifest}, "a flagged unit is in the manifest"
    assert all(r["rights_basis"] == "public_domain" for r in manifest)
    assert not any(r["seen_writer"] for r in manifest if r["stratum"] == "primary")
