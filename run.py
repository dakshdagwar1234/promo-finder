#!/usr/bin/env python3
"""Find promo clips in a microdrama screenplay pack.
   python run.py --input path/to/show_folder --out outputs/            (offline heuristic baseline)
   LLM_API_KEY=... python run.py --input ... --provider gemini --model <model-name>
"""
import argparse, csv, json, os, sys, time
from promo_finder.parser import load_show
from promo_finder.candidates import shortlist, fmt
from promo_finder.llm import LLM
from promo_finder import score as S

def overlaps(a, b):
    for x in a.segments:
        for y in b.segments:
            if x.ep == y.ep and min(x.end, y.end) - max(x.start, y.start) > 3: return True
    return False

def select(cands, n, per_ep):
    picked, count = [], {}
    for c in sorted(cands, key=lambda c: -c.final):
        if c.verify.get("rejected"): continue
        ep = c.segments[0].ep
        if count.get(ep, 0) >= per_ep or any(overlaps(c, p) for p in picked): continue
        picked.append(c); count[ep] = count.get(ep, 0) + 1
        if len(picked) >= n: break
    return picked

def seg_str(c): return " + ".join(f"E{s.ep} {fmt(s.start)}-{fmt(s.end)}" for s in c.segments)

def row(rank, c):
    return {"rank": rank, "id": c.cid, "episode": c.segments[0].ep, "type": c.kind,
            "segments": seg_str(c), "length_s": round(c.length, 1), "score": round(c.final, 2),
            "hook": S.hook_text(c), "cliffhanger": S.cliff_text(c), "why_it_works": S.why_text(c),
            "heuristic": {k: round(v, 2) for k, v in c.h.items()}, "llm": c.llm, "stranger_test": c.verify}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True); ap.add_argument("--out", default="outputs")
    ap.add_argument("--provider", default=None, help="gemini | anthropic | openai | none (default: env LLM_PROVIDER or none)")
    ap.add_argument("--model", default=None); ap.add_argument("--base-url", default=None)
    ap.add_argument("--top-k", type=int, default=8, help="candidates per episode sent to the LLM")
    ap.add_argument("--n", type=int, default=15, help="promos to output"); ap.add_argument("--max-per-episode", type=int, default=2)
    ap.add_argument("--verify-top", type=int, default=40, help="candidates that get the blind stranger test")
    ap.add_argument("--episodes", default=None, help="e.g. 1-10 to run a subset")
    a = ap.parse_args()
    t0 = time.time()
    eps = load_show(a.input)
    if a.episodes:
        lo, hi = (a.episodes.split("-") + [a.episodes])[:2]; eps = [e for e in eps if int(lo) <= e.num <= int(hi)]
    if not eps: sys.exit("no episodes found")
    llm = LLM(a.provider, a.model, base_url=a.base_url)
    by_num = {e.num: e for e in eps}
    print(f"[1/5] parsed {len(eps)} episodes, {sum(len(e.events) for e in eps)} events")

    pool, total_gen = [], 0
    for ep in eps:
        c = shortlist(ep, a.top_k); pool += c
    print(f"[2/5] candidate generation: {len(pool)} shortlisted (code only, 0 LLM calls)")

    if llm.enabled:
        print(f"[3/5] LLM scoring with {llm.provider}:{llm.model} (1 call per episode)")
        for ep in eps:
            cs = [c for c in pool if c.segments[0].ep == ep.num]
            S.stage_a(llm, ep, by_num.get(ep.num - 1), cs, by_num)
        for c in pool: S.finalize(c, True)
        print(f"[4/5] blind stranger test on top {a.verify_top}")
        top = sorted(pool, key=lambda c: -c.final)[:a.verify_top]
        S.stage_b(llm, top, by_num)
        for c in pool: S.finalize(c, True)
    else:
        print("[3-4/5] no LLM configured -> heuristic baseline only (set --provider/LLM_API_KEY for the real run)")
        for c in pool: S.finalize(c, False)

    picked = select(pool, a.n, a.max_per_episode)
    os.makedirs(a.out, exist_ok=True)
    rows = [row(i + 1, c) for i, c in enumerate(picked)]
    json.dump(rows, open(f"{a.out}/promos.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    flat = [{k: (v if not isinstance(v, (dict, list)) else json.dumps(v)) for k, v in r.items() if k not in ("llm", "heuristic", "stranger_test")} for r in rows]
    with open(f"{a.out}/promos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(flat[0].keys())); w.writeheader(); w.writerows(flat)
    allrows = [row(0, c) | {"rejected": bool(c.verify.get("rejected"))} for c in sorted(pool, key=lambda c: -c.final)]
    json.dump(allrows, open(f"{a.out}/all_candidates.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    mode = f"{llm.provider}:{llm.model}" if llm.enabled else "heuristic-baseline (no LLM)"
    md = [f"# Promo report\n\nMode: **{mode}** | episodes: {len(eps)} | shortlisted: {len(pool)} | output: {len(rows)}\n",
          f"Runtime {time.time()-t0:.1f}s | LLM calls {llm.calls} (+{llm.cached} cached) | tokens in/out {llm.tokens_in}/{llm.tokens_out}\n",
          "## Ranked promos (post #1 first)\n"]
    for r in rows:
        md.append(f"### #{r['rank']}  {r['segments']}  ({r['length_s']}s, score {r['score']}, {r['type']})\n"
                  f"- **Hook:** {r['hook']}\n- **Cliffhanger:** {r['cliffhanger']}\n- **Why it works:** {r['why_it_works']}\n")
    rej = [c for c in sorted(pool, key=lambda c: -c.final) if c.verify.get("rejected")][:10]
    md.append("## Highest-scoring clips REJECTED by the verify pass (see failure analysis)\n")
    for c in rej:
        md.append(f"- {seg_str(c)} score {c.final:.1f}: " + (c.verify.get("issue") or "low cliffhanger/standalone (heuristic)"))
    open(f"{a.out}/report.md", "w", encoding="utf-8").write("\n".join(md))
    print(f"[5/5] wrote {a.out}/promos.json, promos.csv, report.md, all_candidates.json  ({time.time()-t0:.1f}s)")
    for r in rows[:5]: print(f"  #{r['rank']} {r['segments']}  score {r['score']}")

if __name__ == "__main__": main()
