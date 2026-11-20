#!/usr/bin/env python3
"""Strict match verification script for promo-finder."""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from collections import Counter
from promo_finder.parser import load_show

def to_sec(s):
    m, sec = s.split(":")
    return int(m) * 60 + float(sec)

def parse_segments(seg_str):
    segs = []
    for part in seg_str.split(" + "):
        part = part.strip()
        m = re.match(r"E(\d+)\s+(\d{1,2}:\d{2}(?:\.\d+)?)-(\d{1,2}:\d{2}(?:\.\d+)?)", part)
        if m:
            segs.append((int(m.group(1)), to_sec(m.group(2)), to_sec(m.group(3))))
    return segs

def get_first_6s_text(segs, ep_by_num):
    clip_6s_events = []
    t_offset = 0.0
    for ep_num, s_start, s_end in segs:
        ep = ep_by_num.get(ep_num)
        if not ep:
            continue
        for e in ep.events:
            if e.end > s_start + 0.05 and e.start < s_end - 0.05:
                rel = max(0.0, e.start - s_start) + t_offset
                if rel < 6.0:
                    clip_6s_events.append((rel, e))
        t_offset += s_end - s_start
    clip_6s_events.sort(key=lambda x: x[0])
    return " ".join((f"{e.speaker}: {e.text}" if e.speaker else e.text) for _, e in clip_6s_events)

def compute_overlap(hook_line, clip_text):
    words = re.findall(r"[a-z']{4,}", (hook_line or "").lower())
    if not words:
        return 1.0
    c_lower = clip_text.lower()
    matches = sum(1 for w in words if w in c_lower)
    return matches / len(words)

def main():
    ap = argparse.ArgumentParser(description="Verify matched results against screenplay text.")
    ap.add_argument("--input", required=True, help="Path to show folder")
    ap.add_argument("--candidates", default="outputs/all_candidates.json", help="Path to all_candidates.json")
    args = ap.parse_args()

    with open(args.candidates, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    eps = load_show(args.input)
    ep_by_num = {e.num: e for e in eps}

    # Counts per match type across all candidates
    match_counts = Counter(r.get("llm", {}).get("_match", "none") for r in candidates)
    print("Counts per _match type:")
    for m_type, cnt in sorted(match_counts.items(), key=lambda x: -x[1]):
        print(f"  {m_type}: {cnt}")

    # Process time and position matches
    records = []
    for r in candidates:
        m_type = r.get("llm", {}).get("_match")
        if m_type in ("time", "position"):
            segs = parse_segments(r["segments"])
            clip_6s = get_first_6s_text(segs, ep_by_num)
            hl = r.get("llm", {}).get("hook_line", "")
            ov = compute_overlap(hl, clip_6s)
            records.append({
                "id": r["id"],
                "match_type": m_type,
                "hook_line": hl,
                "first_6s": clip_6s,
                "overlap": ov
            })

    if records:
        gte_60 = sum(1 for rec in records if rec["overlap"] >= 0.6)
        pct = (gte_60 / len(records)) * 100
        print(f"\nPercentage with overlap >= 0.6: {pct:.1f}% ({gte_60}/{len(records)})")
    else:
        print("\nNo 'time' or 'position' matches found.")

    pos_records = [rec for rec in records if rec["match_type"] == "position"]
    pos_records.sort(key=lambda x: (x["overlap"], x["id"]))

    print(f"\n6 positional matches with LOWEST overlap:")
    for i, rec in enumerate(pos_records[:6], 1):
        print(f"\n#{i} ID: {rec['id']} (overlap: {rec['overlap']:.2f})")
        print(f"   Hook line: {rec['hook_line']}")
        print(f"   First 6s text: {rec['first_6s']}")

if __name__ == "__main__":
    main()
