# hand_ids.jsonl: bootstrap clusters for the H eval sets

eval asked for the hand of each row (heocr-restricted-eval#39), so clusters come from data, not from re-deriving the
rule. The v1 and v1.1 manifests stay byte-identical (eval pins 63e9f31c… and a1c7f616…), so the hands are in this
sidecar, one row per manifest row, with the manifest's sha256.

- **hand_names:** the hands the v1.1 rule assigns to the page (`scripts/select_h_eval_v1_1.py`, `hands()`): role `writer`;
  `author` only outside `nli__ms_*`; otherwise `unknown:<source_id>`.
- **hand_id:** the cluster for resampling. Pages that share any writer are in one cluster (connected components), so a
  joint letter and the same writer's own letter fall together.
- **Counts (primary, v1 ∪ v1.1):** 49 individual writers, 47 clusters. The difference is two joint letters in v1:
  Chaim Berlin + Moses Nahum Jerusalimski (Berlin also has a letter of his own), and Isser Zalman Meltzer + Moshe
  Mordechai Epstein.

— data-collection[claude/claude-code#shay-macbook-m4]@heocr/opensource
