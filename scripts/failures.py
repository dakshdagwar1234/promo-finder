#!/usr/bin/env python3
"""Failure and alignment analysis for promo-finder."""
import json
import re
import os
import sys

def parse_segs(s):
    out = []
    for seg in s.split(" + "):
        parts = seg.strip().split()
        if len(parts) >= 2:
            ep = int(parts[0][1:])
            rng = parts[1]
            s1, s2 = rng.split("-")
            t1 = int(s1.split(":")[0]) * 60 + float(s1.split(":")[1])
            t2 = int(s2.split(":")[0]) * 60 + float(s2.split(":")[1])
            out.append((ep, t1, t2))
    return out

def clip_overlap(a_segs, b_segs):
    total_ov = 0.0
    for ep_a, sa, ea in a_segs:
        for ep_b, sb, eb in b_segs:
            if ep_a == ep_b:
                o = max(0.0, min(ea, eb) - max(sa, sb))
                total_ov += o
    dur_a = sum(ea - sa for _, sa, ea in a_segs)
    dur_b = sum(eb - sb for _, sb, eb in b_segs)
    return total_ov / max(1e-9, min(dur_a, dur_b))

def main():
    all_c_path = "outputs/all_candidates.json"
    promos_path = "outputs/promos.json"
    heur_promos_path = "outputs_heuristic/promos.json"

    with open(all_c_path, "r", encoding="utf-8") as f:
        all_candidates = json.load(f)

    # ---------------------------------------------------------
    # 1. The 11 rejected clips (rejected true and not unscored)
    # ---------------------------------------------------------
    rejected = [
        c for c in all_candidates
        if c.get("rejected") and not c.get("stranger_test", {}).get("unscored") and not c.get("unscored")
    ]
    print("=" * 80)
    print(f"1. REJECTED CLIPS ({len(rejected)} total; rejected=True, not unscored)")
    print("=" * 80)
    for i, c in enumerate(rejected, 1):
        cid = c.get("id")
        score = c.get("score", 0.0)
        llm = c.get("llm", {})
        hook = llm.get("hook", "N/A")
        cliff = llm.get("cliffhanger", "N/A")
        st = c.get("stranger_test", {})
        summary = st.get("summary", "N/A")
        u = st.get("understandable", "N/A")
        e = st.get("ending_unresolved", "N/A")
        issue = st.get("issue", "none")

        print(f"\n[{i}] ID: {cid} | Final Score: {score}")
        print(f"    Scorer: Hook={hook}, Cliffhanger={cliff}")
        print(f"    Stranger Test: Understandable={u}, Ending_Unresolved={e}")
        print(f"    Summary: {summary}")
        print(f"    Issue: {issue}")

    # ---------------------------------------------------------
    # 2. 10 clips where standalone - understandable is largest
    # ---------------------------------------------------------
    verified = [
        c for c in all_candidates
        if "standalone" in c.get("llm", {}) and "understandable" in c.get("stranger_test", {})
    ]
    overconfident = []
    for c in verified:
        standalone = float(c["llm"]["standalone"])
        understandable = float(c["stranger_test"]["understandable"])
        diff = standalone - understandable
        overconfident.append((diff, standalone, understandable, c))
    overconfident.sort(key=lambda x: -x[0])

    print("\n" + "=" * 80)
    print("2. TOP 10 SCORER OVERCONFIDENT CLIPS (Scorer 'standalone' - Stranger 'understandable')")
    print("=" * 80)
    for i, (diff, standalone, understandable, c) in enumerate(overconfident[:10], 1):
        print(f"\n[{i}] ID: {c.get('id')} | Diff: +{diff:.1f} (Scorer standalone={standalone:.0f}, Stranger understandable={understandable:.0f})")
        print(f"    Verifier Summary: {c.get('stranger_test', {}).get('summary')}")
        print(f"    Scorer Why: {c.get('llm', {}).get('why')}")

    # ---------------------------------------------------------
    # 3. 10 clips where cliffhanger - ending_unresolved is largest
    # ---------------------------------------------------------
    cliff_gap = []
    for c in verified:
        cliff = float(c["llm"]["cliffhanger"])
        ending_unresolved = float(c["stranger_test"]["ending_unresolved"])
        diff = cliff - ending_unresolved
        cliff_gap.append((diff, cliff, ending_unresolved, c))
    cliff_gap.sort(key=lambda x: -x[0])

    print("\n" + "=" * 80)
    print("3. TOP 10 CLIFFHANGER DISCREPANCY CLIPS (Scorer 'cliffhanger' - Stranger 'ending_unresolved')")
    print("=" * 80)
    for i, (diff, cliff, ending_unresolved, c) in enumerate(cliff_gap[:10], 1):
        print(f"\n[{i}] ID: {c.get('id')} | Diff: +{diff:.1f} (Scorer cliffhanger={cliff:.0f}, Stranger ending_unresolved={ending_unresolved:.0f})")
        print(f"    Scorer Cliffhanger Desc: {c.get('llm', {}).get('cliffhanger_desc')}")
        print(f"    Verifier Issue: {c.get('stranger_test', {}).get('issue')}")

    # ---------------------------------------------------------
    # 4. Top 15 promos breakdown
    # ---------------------------------------------------------
    with open(promos_path, "r", encoding="utf-8") as f:
        promos = json.load(f)[:15]

    contiguous_cnt = sum(1 for p in promos if p.get("type") == "contiguous")
    teaser_cnt = sum(1 for p in promos if p.get("type") == "teaser+body")
    other_cnt = len(promos) - contiguous_cnt - teaser_cnt

    verified_promos = [p for p in promos if "understandable" in p.get("stranger_test", {})]
    if verified_promos:
        avg_u = sum(p["stranger_test"]["understandable"] for p in verified_promos) / len(verified_promos)
        avg_e = sum(p["stranger_test"]["ending_unresolved"] for p in verified_promos) / len(verified_promos)
    else:
        avg_u = avg_e = 0.0

    print("\n" + "=" * 80)
    print("4. TOP 15 PROMOS COMPOSITION & VERIFICATION SCORES")
    print("=" * 80)
    print(f"Type breakdown: {contiguous_cnt} contiguous, {teaser_cnt} teaser+body" + (f", {other_cnt} other" if other_cnt else ""))
    print(f"Verified promos: {len(verified_promos)}/15")
    print(f"Average understandable: {avg_u:.2f} / 10")
    print(f"Average ending_unresolved: {avg_e:.2f} / 10")

    # ---------------------------------------------------------
    # 5. Overlap with heuristic baseline promos
    # ---------------------------------------------------------
    with open(heur_promos_path, "r", encoding="utf-8") as f:
        heur_promos = json.load(f)[:15]

    matching_pairs = []
    overlapping_p_ids = set()

    for i, p in enumerate(promos):
        p_segs = parse_segs(p["segments"])
        for j, h in enumerate(heur_promos):
            h_segs = parse_segs(h["segments"])
            if p_segs and h_segs and p_segs[0][0] == h_segs[0][0]:
                ov = clip_overlap(p_segs, h_segs)
                if ov >= 0.5:
                    overlapping_p_ids.add(p["id"])
                    matching_pairs.append((i + 1, p["id"], j + 1, h["id"], ov))

    print("\n" + "=" * 80)
    print("5. OVERLAP WITH HEURISTIC BASELINE PROMOS (>= 50% time overlap, same episode)")
    print("=" * 80)
    for p_rank, pid, h_rank, hid, ov in matching_pairs:
        print(f"  Promo #{p_rank} ({pid}) overlaps Heuristic Promo #{h_rank} ({hid}) by {ov:.1%}")
    print(f"\nTotal overlapping promos: {len(overlapping_p_ids)} / 15 ({len(overlapping_p_ids)/15:.1%})")

if __name__ == "__main__":
    main()
