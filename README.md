# Promo Finder (Kuku AI Generalist, Problem 1)

Finds 20-60s promo clips (hook in first 3s, unresolved ending, understandable cold) in a microdrama screenplay pack.
**Python 3.9+, no dependencies.** Input pack is Kuku's confidential content: keep it out of git (see .gitignore).

```bash
# 1. offline baseline, no key needed (~1s for 50 episodes)
python run.py --input "path/to/show_folder" --out outputs_heuristic

# 2. real run with any LLM (model + provider are config, swap freely)
export LLM_PROVIDER=gemini LLM_MODEL=<model-name> LLM_API_KEY=<key>
python run.py --input "path/to/show_folder" --out outputs

# subset / tuning
python run.py --input ... --episodes 1-10 --n 15 --top-k 8 --max-per-episode 2

# score against your own hand labels (gold.csv: episode,start,end,label[good|bad])
python evaluate.py --gold gold.csv --pred outputs/promos.json --k 10
PROMO_DATA="path/to/show_folder" python tests/test_pipeline.py
```

## Pipeline (code decides structure, LLM decides taste)
1. **Parse** (`parser.py`): screenplay -> typed events with timestamps. Pure code.
2. **Candidates** (`candidates.py`): every window of 20-60s that starts on a line/action and ends on a spoken line; plus
   "teaser+body" stitches (shocking moment first, then rewind). Heuristic score + overlap suppression -> top 8 per episode.
   **The LLM never writes timestamps**, it only scores candidate ids, so timestamps cannot be hallucinated.
3. **LLM score** (`score.py`, 1 call per episode): hook (first 3s), cliffhanger (last 4s), standalone, intensity, one-line why.
4. **Blind stranger test** (top 40 only): a second prompt sees ONLY the raw transcript (no logline, no context) and
   reports whether it understands the clip and whether the ending feels unresolved. Failing clips are rejected.
5. **Rank + diversity**: weighted score, max 2 per episode, no overlaps. Outputs `promos.json/.csv`, `report.md`,
   `all_candidates.json` (includes rejected clips for failure analysis).

Without a key it runs a transparent keyword/rule scorer (the baseline to beat, and the offline fallback).
LLM responses are cached in `.llm_cache/`, so re-running is free and instant.
