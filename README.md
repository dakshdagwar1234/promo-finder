# Promo Finder

Promo Finder identifies viral 20–60s promotional clips from microdrama screenplay packs by enforcing short-video marketing fundamentals: an immediate hook in the first 3 seconds to halt feed scrolling, high narrative tension ending on an unresolved cliffhanger, and standalone comprehensibility for first-time viewers. By combining rule-based deterministic candidate slicing with dual-stage LLM evaluation (batch scoring plus an adversarial blind stranger verification test), it guarantees cut accuracy while ranking the highest-converting ad moments.

## Pipeline Architecture
1. **Parse (`promo_finder/parser.py`)**: Ingests screenplay text and converts it into strongly typed events (`DIALOGUE`, `ACTION`, `SFX`, `CAMERA`) with exact floating-point timestamps and speaker/tone attributes.
2. **Candidate Generation (`promo_finder/candidates.py`)**: Slices contiguous windows (20–60s) beginning on dialogue/action lines and ending on spoken lines/dramatic beats, along with cold-open "teaser+body" stitches. Applies rule-based heuristic scoring and greedy non-max suppression (NMS) to yield the top candidate pool (default 8 per episode). **The LLM never invents or writes timestamps; it only evaluates pre-sliced candidate IDs.**
3. **LLM Scoring (`promo_finder/score.py` - Stage A)**: Batches candidates episode-by-episode to an LLM evaluator (1 call per episode) to score hook strength (0–10 in first 3s), cliffhanger strength (0–10 in last ~4s), standalone clarity, intensity, and a 1-sentence rationale.
4. **Blind Stranger Test (`promo_finder/score.py` - Stage B)**: Top-40 scoring candidates undergo an adversarial verification pass where a second LLM prompt evaluates the raw transcript with zero episode context or loglines. Clips scoring low on stranger understandability (<5) or ending resolution (<5) are automatically rejected.
5. **Ranking & Diversity (`run.py`)**: Blends heuristic, scorer, and stranger-test metrics into a final calibrated score, enforcing maximum per-episode limits (default: 2) and deduplicating time overlaps.

## Setup
- **Python Version**: Python 3.10+
- **Dependencies**: The pipeline uses standard library modules only (`urllib`, `json`, `re`, `argparse`, `dataclasses`, `hashlib`, etc.) with plain HTTP requests. No third-party SDKs or packages are required.
```bash
pip install -r requirements.txt
```

## Configuration via Environment Variables
All configuration is handled model-agnostically through environment variables or CLI flags (no code edits required):

| Variable | Description | Default |
|:---|:---|:---|
| `LLM_PROVIDER` | Provider backend: `gemini`, `anthropic`, `openai` (any OpenAI-compatible API), or `none` | `none` |
| `LLM_MODEL` | Primary scoring model (e.g. `openai/gpt-oss-120b`, `gemini-2.5-pro`) | `""` |
| `LLM_VERIFY_MODEL`| Model for Stage B stranger test (defaults to `LLM_MODEL`) | `LLM_MODEL` |
| `LLM_API_KEY` | API secret key for the selected provider | `""` |
| `LLM_BASE_URL` | Base URL for OpenAI-compatible endpoints | `https://api.openai.com/v1` |
| `LLM_TPM` | Tokens-per-minute throttle limit (`0` disables throttling) | `0` |
| `PROMO_CACHE` | Directory path for disk response cache | `.llm_cache` |

### PowerShell Configuration Examples
```powershell
# OpenRouter / OpenAI-compatible endpoint
$env:LLM_PROVIDER="openai"
$env:LLM_BASE_URL="https://openrouter.ai/api/v1"
$env:LLM_MODEL="openai/gpt-oss-120b"
$env:LLM_VERIFY_MODEL="openai/gpt-oss-20b"
$env:LLM_API_KEY="your-api-key"
$env:LLM_TPM="200000"

# Gemini Direct
$env:LLM_PROVIDER="gemini"
$env:LLM_MODEL="gemini-2.5-pro"
$env:LLM_API_KEY="your-gemini-key"

# Anthropic Direct
$env:LLM_PROVIDER="anthropic"
$env:LLM_MODEL="claude-3-7-sonnet-20250219"
$env:LLM_API_KEY="your-anthropic-key"
```

## Execution
```powershell
# Run heuristic baseline (no LLM required, instant offline execution)
python run.py --input "data/I Married a Broken Soldier. He was a Duke" --out outputs_heuristic

# Run full LLM pipeline with scoring and blind stranger test
python run.py --input "data/I Married a Broken Soldier. He was a Duke" --out outputs

# Run on a subset of episodes
python run.py --input "data/I Married a Broken Soldier. He was a Duke" --episodes 1-5 --out outputs_test
```

### Swapping Models & Providers
To swap the model or provider, update the environment variables or pass CLI arguments without altering any codebase logic:
```powershell
# Swap via CLI arguments directly
python run.py --input "data/..." --provider openai --model "openai/gpt-4o" --verify-model "openai/gpt-4o-mini" --base-url "https://api.openai.com/v1"
```

## Outputs Produced
Running `run.py` writes four structured artifacts into `--out` (e.g. `outputs/`):
- `promos.json`: The final ranked top-15 promo recommendations with metadata, segment timings, hook lines, cliffhanger descriptions, and rationale.
- `promos.csv`: Flattened tabular format of top promos for spreadsheet analysis.
- `report.md`: Markdown summary report detailing execution mode, token consumption, runtime, ID matching breakdown, and top-ranked clips.
- `all_candidates.json`: Exhaustive dump of all shortlisted candidate windows across all episodes, including stage scores, match diagnostics, stranger-test metrics, and rejection flags.

> **Note on Safety:** The LLM only receives and outputs candidate ID strings; timestamps are strictly generated and validated by deterministic parser and candidate logic, completely eliminating timestamp hallucination.

## Caching & Rate Limit Handling
- **Disk Caching**: Every prompt is hashed (`SHA-256` of provider, model, system prompt, and body) and stored under `.llm_cache/` (or `$env:PROMO_CACHE`). Subsequent runs are instant and consume zero tokens.
- **Fail-Fast on Daily Limits**: When receiving an HTTP 429 response containing `"tokens per day"`, the pipeline terminates immediately with a `RuntimeError` rather than sleeping pointlessly. Because all completed calls are committed to disk cache immediately upon return, re-running the command later resumes instantly without losing prior progress.

## Known Limitations
1. **Model ID Output Formatting**: Some LLMs emit shortened IDs or positional numbers instead of verbatim candidate IDs. A 3-tier fallback (exact string match -> last-two timestamp match -> positional index alignment) paired with a hook-line lexical sanity check is used to recover alignments safely.
2. **Subtle & Quiet Hooks**: Heuristic and LLM prompt scoring reward overt shocks, slaps, shouts, and weapon draws over understated psychological intrigue or subtle micro-expressions.
3. **Synthetic Teaser Stitches**: Flash-forward "teaser+body" stitches frequently sound jarring or disorienting without music/visual continuity, so organic contiguous clips generally outperform them on stranger understandability.

## Data Note
Screenplay files and episodic scripts belong to Kuku's proprietary content and are not distributed within this repository. Place screenplay folders in `data/` (ignored by git).
