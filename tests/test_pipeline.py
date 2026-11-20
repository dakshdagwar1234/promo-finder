"""Run: python -m pytest tests -q   (or: python tests/test_pipeline.py). Needs PROMO_DATA=<show folder>."""
import os, re, json, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from promo_finder.parser import load_show
from promo_finder.candidates import shortlist
from promo_finder.llm import LLM
from promo_finder import score as S

DATA = os.environ.get("PROMO_DATA", "")

class FakeLLM(LLM):
    """Deterministic stand-in so the LLM code path is tested without an API key."""
    def __init__(self): super().__init__("fake", "fake-1"); self.n = 0
    @property
    def enabled(self): return True
    def _call(self, system, prompt):
        self.n += 1
        ids = re.findall(r"### (?:CANDIDATE|CLIP) (\S+)", prompt)
        if "CANDIDATE" in prompt:
            return json.dumps({"scores": [{"id": i, "hook": 7, "hook_line": "x", "cliffhanger": 6, "cliffhanger_desc": "y",
                                           "standalone": 6, "intensity": 5, "why": "z"} for i in ids]})
        return json.dumps({"clips": [{"id": i, "summary": "s", "understandable": 4 if k == 0 else 8,
                                      "ending_unresolved": 8, "would_tap_next": 7, "issue": "needs context"} for k, i in enumerate(ids)]})

def test_parse_and_candidates():
    eps = load_show(DATA)
    assert len(eps) >= 1 and all(e.events for e in eps)
    for ep in eps:
        for c in shortlist(ep):
            assert 20 <= c.length <= 60.01, (c.cid, c.length)
            assert all(s.start < s.end for s in c.segments)

def test_llm_path_and_reject():
    eps = load_show(DATA)[:3]; by = {e.num: e for e in eps}; llm = FakeLLM()
    os.environ["PROMO_CACHE"] = tempfile.mkdtemp()
    import promo_finder.llm as L; L.CACHE = os.environ["PROMO_CACHE"]
    pool = []
    for ep in eps: pool += shortlist(ep, 5)
    for ep in eps: S.stage_a(llm, ep, by.get(ep.num - 1), [c for c in pool if c.segments[0].ep == ep.num], by)
    S.stage_b(llm, pool[:5], by)
    for c in pool: S.finalize(c, True)
    assert all(c.llm for c in pool) and pool[0].verify.get("rejected") is True   # understandable=4 -> rejected

if __name__ == "__main__":
    test_parse_and_candidates(); test_llm_path_and_reject(); print("all tests passed")
