#!/usr/bin/env python3
"""Print readable transcript of an episode for hand labelling."""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from promo_finder.parser import load_show

def parse_time(val):
    if val is None:
        return None
    val = str(val).strip()
    if ":" in val:
        parts = val.split(":")
        return int(parts[0]) * 60 + float(parts[1])
    return float(val)

def fmt_time(t):
    m = int(t // 60)
    s = int(t % 60)
    return f"[{m:02d}:{s:02d}]"

def main():
    ap = argparse.ArgumentParser(description="Print readable transcript for hand labelling.")
    ap.add_argument("--input", required=True, help="Path to show folder")
    ap.add_argument("--episode", type=int, required=True, help="Episode number")
    ap.add_argument("--start", default=None, help="Start time (mm:ss or seconds)")
    ap.add_argument("--end", default=None, help="End time (mm:ss or seconds)")
    ap.add_argument("--context", action="store_true", help="Print episode logline and continuity notes")
    args = ap.parse_args()

    eps = load_show(args.input)
    by_num = {e.num: e for e in eps}
    if args.episode not in by_num:
        sys.exit(f"Episode {args.episode} not found in {args.input}")
    ep = by_num[args.episode]

    if args.context:
        print(f"EPISODE {ep.num} LOGLINE: {ep.logline}")
        print(f"CONTINUITY NOTES: {ep.continuity}\n")

    start_sec = parse_time(args.start)
    end_sec = parse_time(args.end)

    for e in ep.events:
        # Overlap filter
        if start_sec is not None and e.end <= start_sec:
            continue
        if end_sec is not None and e.start >= end_sec:
            continue

        ts = fmt_time(e.start)
        if e.kind == "DIALOGUE":
            tone = f" ({e.tone})" if e.tone else ""
            print(f"{ts} {e.speaker}{tone}: {e.text}")
        elif e.kind == "ACTION":
            print(f"{ts} (action) {e.text}")
        elif e.kind == "SFX":
            txt_lower = e.text.lower()
            if "cliffhanger" in txt_lower or "cut to black" in txt_lower:
                print(f"{ts} (sound) {e.text}")

if __name__ == "__main__":
    main()
