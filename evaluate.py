#!/usr/bin/env python3
"""Compare tool output with YOUR hand-labelled gold promos.
gold.csv columns: episode,start,end,label   (label = good|bad; times as mm:ss or seconds)
   python evaluate.py --gold gold.csv --pred outputs/promos.json --k 10
Metrics: precision@k (a prediction is a hit if it overlaps a 'good' gold clip by >=50% of the shorter one),
recall of gold-good clips, and false-positive overlap with 'bad' clips."""
import argparse, csv, json

def t(x):
    x = x.strip()
    if ":" in x: m, s = x.split(":"); return int(m) * 60 + float(s)
    return float(x)

def ov(a, b):
    o = min(a[1], b[1]) - max(a[0], b[0])
    return o / max(1e-9, min(a[1] - a[0], b[1] - b[0]))

ap = argparse.ArgumentParser(); ap.add_argument("--gold", required=True); ap.add_argument("--pred", required=True); ap.add_argument("--k", type=int, default=10)
a = ap.parse_args()
gold = [(int(r["episode"]), t(r["start"]), t(r["end"]), r["label"].strip().lower()) for r in csv.DictReader(open(a.gold))]
pred = json.load(open(a.pred))[:a.k]
def hits(p, lab):
    out = []
    for seg in p["segments"].split(" + "):
        _, rng = seg.split(" ", 1); s, e = rng.split("-")
        out.append((int(seg.split()[0][1:]), t(s), t(e)))
    return any(g[3] == lab and g[0] == ep_ and ov((g[1], g[2]), (s, e)) >= .5 for g in gold for ep_, s, e in out)
good = sum(hits(p, "good") for p in pred); bad = sum(hits(p, "bad") for p in pred)
gg = [g for g in gold if g[3] == "good"]
rec = sum(any(int(p["segments"].split()[0][1:]) == g[0] and any(ov((g[1], g[2]), (t(x.split("-")[0]), t(x.split("-")[1]))) >= .5 for x in [seg.split(" ", 1)[1] for seg in p["segments"].split(" + ")]) for p in json.load(open(a.pred))) for g in gg)
print(f"precision@{a.k}: {good}/{len(pred)} = {good/max(1,len(pred)):.0%} | matched a 'bad' clip: {bad} | recall of gold-good: {rec}/{len(gg)}")
