#!/usr/bin/env python3
"""Export readable dialogue and action events for top promos."""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from promo_finder.parser import load_show

def to_sec(s):
    m, sec = s.split(":")
    return int(m) * 60 + float(sec)

def parse_segments(seg_str):
    out = []
    for part in seg_str.split(" + "):
        part = part.strip()
        m = re.match(r"E(\d+)\s+(\d{1,2}:\d{2}(?:\.\d+)?)-(\d{1,2}:\d{2}(?:\.\d+)?)", part)
        if m:
            ep_num = int(m.group(1))
            out.append((ep_num, to_sec(m.group(2)), to_sec(m.group(3))))
    return out

def main():
    ap = argparse.ArgumentParser(description="Export top promos transcript.")
    ap.add_argument("--input", required=True, help="Path to show folder")
    ap.add_argument("--pred", default="outputs/promos.json", help="Path to promos.json")
    ap.add_argument("--from", dest="from_rank", type=int, default=1, help="Starting rank (inclusive)")
    ap.add_argument("--to", dest="to_rank", type=int, default=15, help="Ending rank (inclusive)")
    args = ap.parse_args()

    with open(args.pred, "r", encoding="utf-8") as f:
        promos = json.load(f)

    eps = load_show(args.input)
    ep_by_num = {e.num: e for e in eps}

    for p in promos:
        rank = p.get("rank")
        if (args.from_rank is not None and rank < args.from_rank) or (args.to_rank is not None and rank > args.to_rank):
            continue

        print(f"=== #{rank} {p['segments']} ===")
        segs = parse_segments(p["segments"])
        for ep_num, s_start, s_end in segs:
            ep = ep_by_num.get(ep_num)
            if not ep:
                continue
            for e in ep.events:
                if e.end > s_start + 0.05 and e.start < s_end - 0.05:
                    ts = f"[{int(e.start // 60):02d}:{int(e.start % 60):02d}]"
                    txt = e.text[:150]
                    if e.kind == "DIALOGUE":
                        print(f"{ts} {e.speaker}: {txt}")
                    elif e.kind == "ACTION":
                        print(f"{ts} (action) {txt}")

if __name__ == "__main__":
    main()
