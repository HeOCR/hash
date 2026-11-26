"""H eval sets: the hold-out file covers whole units and agrees with each set's manifest (docs/h_eval_set_plan.md)."""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETS = ("h_eval_v1", "h_eval_v1_1")


def rows(p):
    return [json.loads(line) for line in (ROOT / p).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_holdout_covers_whole_units_and_manifests():
    entries = rows("data/index/entries.jsonl")
    holdout = rows("data/index/eval_holdout.jsonl")
    by_unit = defaultdict(set)
    for e in entries:
        by_unit[e["source_id"]].add(e["entry_id"])
    held, unit_set = defaultdict(set), {}
    for h in holdout:
        held[h["source_id"]].add(h["entry_id"])
        assert unit_set.setdefault(h["source_id"], h["eval_set"]) == h["eval_set"], f"{h['source_id']} in two sets"
    for h in holdout:  # contamination v2 amendment 1 (restricted-eval #1651): only scored pages are protected
        if h["selected"]:
            assert h["train_policy"] == "excluded_scored" and "train_tag" not in h, h["entry_id"]
        else:
            assert h["train_policy"] == "train_allowed_tagged" and h["train_tag"] == "in_hash_eval_holdout_unselected", h["entry_id"]
    for unit, ids in held.items():
        assert ids == by_unit[unit], f"{unit}: hold-out must list every page of the unit"
    for name in SETS:
        path = ROOT / "data" / "eval" / name / "manifest.jsonl"
        if not path.exists():
            continue
        manifest = rows(path.relative_to(ROOT))
        flagged = {r["source_id"] for r in rows(f"data/eval/{name}/flags.jsonl")}
        selected = {h["entry_id"] for h in holdout if h["selected"] and h["eval_set"] == name}
        assert selected == {r["entry_id"] for r in manifest}, name
        assert not flagged & {r["source_id"] for r in manifest}, f"{name}: a flagged unit is in the manifest"
        assert all(r["rights_basis"] == "public_domain" for r in manifest), name
        assert not any(r["seen_writer"] for r in manifest if r["stratum"] == "primary"), name
