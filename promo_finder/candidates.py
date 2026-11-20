"""Rule-based candidate generation. The LLM never invents timestamps: it only scores / picks from these."""
from dataclasses import dataclass, field
from . import heuristics as H

MIN_LEN, MAX_LEN = 20.0, 60.0

@dataclass
class Segment:
    ep: int
    start: float
    end: float

@dataclass
class Candidate:
    cid: str
    kind: str                       # contiguous | teaser+body
    segments: list
    events: list = field(default_factory=list)   # events in clip order (times kept absolute)
    h: dict = field(default_factory=dict)         # heuristic scores
    llm: dict = field(default_factory=dict)
    verify: dict = field(default_factory=dict)
    final: float = 0.0
    @property
    def length(self): return sum(s.end - s.start for s in self.segments)

def fmt(t): return f"{int(t//60):02d}:{t%60:05.2f}"

def _content(ep):  # only dialogue/action define cut points; camera/sfx ride along
    return [e for e in ep.events if e.kind in ("DIALOGUE", "ACTION")]

def _slice(ep, a, b):
    return [e for e in ep.events if e.end > a + 0.05 and e.start < b - 0.05]

def _score(c, ep):
    ev = c.events
    t0, t1 = c.segments[0].start, c.segments[-1].end
    c.h = {
        "hook": H.hook_score(ev, t0),
        "cliff": H.cliff_score(ev, t1, ep.duration),
        "standalone": H.standalone_score(ev, ep.num),
        "intensity": H.intensity_score(ev),
    }
    c.h["total"] = (0.35 * c.h["hook"] + 0.35 * c.h["cliff"] + 0.2 * c.h["standalone"] + 0.1 * c.h["intensity"])

def contiguous(ep):
    """Every window that starts on a line/action start, ends on a line/action end, 20-60s long."""
    ce = _content(ep)
    out = []
    for i, a in enumerate(ce):
        for b in ce[i:]:
            L = b.end - a.start
            if L > MAX_LEN: break
            if L < MIN_LEN: continue
            if b.kind != "DIALOGUE" and b is not ce[-1]: continue   # end on a spoken line (or the final beat)
            c = Candidate(f"E{ep.num:02d}-{fmt(a.start)}-{fmt(b.end)}", "contiguous",
                          [Segment(ep.num, a.start, b.end)], _slice(ep, a.start, b.end))
            _score(c, ep); out.append(c)
    return out

def teaser_stitches(ep, base, n_base=6, n_tease=12):
    """ReelShort-style cold open: a shocking 2-8s moment from OUTSIDE the body goes first, then we rewind
    to the body. Only built for strong bodies with a weak opening; total length stays <= 60s."""
    ce = _content(ep)
    moments = sorted(((H.hook_score([e], e.start), e) for e in ce if e.end - e.start <= 8), key=lambda x: -x[0])
    moments = [(hs, e) for hs, e in moments if hs >= 7][:n_tease]
    out = []
    for c in base[:n_base]:
        a, b = c.segments[0].start, c.segments[-1].end
        if c.h["hook"] >= 7: continue                      # body already opens strong
        for hs, m in moments:
            if m.end > a - 0.5 and m.start < b: continue   # inside/adjacent to the body: not a flash-forward
            if (m.end - m.start) + c.length > MAX_LEN: continue
            t = Candidate(f"E{ep.num:02d}-T{fmt(m.start)}+{fmt(a)}-{fmt(b)}", "teaser+body",
                          [Segment(ep.num, m.start, m.end), Segment(ep.num, a, b)],
                          _slice(ep, m.start, m.end) + c.events)
            _score(t, ep)
            t.h["total"] -= 0.4                            # stitches risk confusing a stranger
            if t.h["total"] > c.h["total"]: out.append(t); break
    return out

def nms(cands, max_overlap=0.4):
    """Greedy non-max suppression on time overlap, best-first."""
    keep = []
    for c in sorted(cands, key=lambda c: -c.h["total"]):
        s = c.segments[-1]
        ok = True
        for k in keep:
            if k.segments[-1].ep != s.ep: continue
            ov = min(k.segments[-1].end, s.end) - max(k.segments[0].start, c.segments[0].start)
            if ov > max_overlap * min(k.length, c.length): ok = False; break
        if ok: keep.append(c)
    return keep

def shortlist(ep, top_k=8):
    base = nms(contiguous(ep))
    stitched = teaser_stitches(ep, base)
    pool = nms(base + stitched)
    return pool[:top_k]
