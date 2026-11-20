"""LLM judgment layer. The model only scores/picks from code-generated candidates (ids), never emits timestamps."""
import json, sys
from .candidates import fmt

def _norm_id(val):
    if not isinstance(val, str): val = str(val)
    return val.strip().strip("'\"“”`").lower()

SYSTEM = """You are a senior short-drama marketing editor (ReelShort / DramaBox style). You judge promo clips for \
vertical-video ads. A promo must: (1) HOOK - something in its first 3 seconds that stops a scrolling viewer (a slap, \
reveal, threat, shocking line); (2) end on a CLIFFHANGER - cut at an unresolved moment so the viewer must know what \
happens next; (3) be understandable to someone who has NEVER seen the show. Be a harsh, calibrated grader: most clips \
deserve 3-6; reserve 8+ for genuinely great ones. Scenes that end in reconciliation, comfort or resolution are NOT cliffhangers. \
Reply with JSON only."""

def render(c, ep_by_num):
    out, t = [], 0.0
    for si, seg in enumerate(c.segments):
        if si: out.append("--- CUT (non-continuous jump) ---")
        for e in [e for e in c.events if e.end > seg.start + .05 and e.start < seg.end - .05]:
            rel = max(0.0, e.start - seg.start) + t
            if e.kind == "DIALOGUE": out.append(f"[{rel:5.1f}s] {e.speaker}{' ('+e.tone+')' if e.tone else ''}: \"{e.text}\"")
            elif e.kind == "ACTION": out.append(f"[{rel:5.1f}s] (action) {e.text}")
            elif e.kind == "SFX": out.append(f"[{rel:5.1f}s] (sound) {e.text}")
        t += seg.end - seg.start
    return "\n".join(out)

def stage_a(llm, ep, prev, cands, ep_by_num):
    ctx = f"Episode {ep.num} logline: {ep.logline}\nContinuity: {ep.continuity}"
    if prev: ctx += f"\nPrevious episode logline: {prev.logline}"
    body = "\n\n".join(f"### CANDIDATE {c.cid} (length {c.length:.0f}s)\n{render(c, ep_by_num)}" for c in cands)
    prompt = f"""{ctx}

Score each candidate promo clip below. Camera directions are omitted.
For each candidate return: hook (0-10, judged ONLY on its first 3 seconds), hook_line (the exact line/action in the \
first 3s), cliffhanger (0-10, judged on the final ~4s: is something left unresolved?), cliffhanger_desc (what is left \
hanging, <=15 words), standalone (0-10, could a stranger follow it using only the clip?), intensity (0-10), \
why (ONE sentence on why it would or would not work as an ad).

{body}

Return JSON: {{"scores":[{{"id":"...","hook":0,"hook_line":"","cliffhanger":0,"cliffhanger_desc":"","standalone":0,"intensity":0,"why":""}}]}}"""
    res = llm.complete_json(SYSTEM, prompt)
    scores_list = res.get("scores", []) if isinstance(res, dict) else []
    by = {_norm_id(s.get("id", "")): s for s in scores_list if isinstance(s, dict) and "id" in s}
    for c in cands:
        nid = _norm_id(c.cid)
        if nid in by: c.llm = by[nid]

    missing = [c for c in cands if not c.llm]
    if missing:
        first_item = scores_list[0] if scores_list and isinstance(scores_list[0], dict) else {}
        first_keys = list(first_item.keys())
        raw_text = getattr(llm, "last_raw", None)
        raw_len_str = f"; raw length: {len(raw_text)}" if raw_text is not None else f"; raw length: {len(json.dumps(res))}"
        missing_ids = ", ".join(c.cid for c in missing)
        print(f"[score] ep {ep.num}: model returned {len(scores_list)}/{len(cands)} scores; missing ids: {missing_ids}; first item keys: {first_keys}{raw_len_str}", file=sys.stderr)

        for i in range(0, len(missing), 3):
            chunk = missing[i:i + 3]
            retry_body = "\n\n".join(f"### CANDIDATE {c.cid} (length {c.length:.0f}s)\n{render(c, ep_by_num)}" for c in chunk)
            retry_prompt = f"""{ctx}

Score each candidate promo clip below. Camera directions are omitted.
For each candidate return: hook (0-10, judged ONLY on its first 3 seconds), hook_line (the exact line/action in the \
first 3s), cliffhanger (0-10, judged on the final ~4s: is something left unresolved?), cliffhanger_desc (what is left \
hanging, <=15 words), standalone (0-10, could a stranger follow it using only the clip?), intensity (0-10), \
why (ONE sentence on why it would or would not work as an ad).
You MUST return exactly one entry for each of the {len(chunk)} candidate ids listed, no more, no fewer.

{retry_body}

Return JSON: {{"scores":[{{"id":"...","hook":0,"hook_line":"","cliffhanger":0,"cliffhanger_desc":"","standalone":0,"intensity":0,"why":""}}]}}"""
            retry_res = llm.complete_json(SYSTEM, retry_prompt)
            r_scores = retry_res.get("scores", []) if isinstance(retry_res, dict) else []
            r_by = {_norm_id(s.get("id", "")): s for s in r_scores if isinstance(s, dict) and "id" in s}
            for c in chunk:
                nid = _norm_id(c.cid)
                if nid in r_by: c.llm = r_by[nid]

VERIFY_SYSTEM = """You are a viewer who has NEVER seen this show, scrolling a social feed. You are given only a raw clip \
transcript. Judge honestly as that stranger. Reply with JSON only."""

def stage_b(llm, cands, ep_by_num, batch=5):
    for i in range(0, len(cands), batch):
        chunk = cands[i:i + batch]
        body = "\n\n".join(f"### CLIP {c.cid}\n{render(c, ep_by_num)}" for c in chunk)
        prompt = f"""Clips are independent. For each: summary (one sentence of what you think is happening), \
understandable (0-10: could you follow who/what/why with zero background?), ending_unresolved (0-10: 10 = the \
ending leaves a burning open question, 0 = the scene feels finished), would_tap_next (0-10), issue (biggest \
problem, or "none").

{body}

Return JSON: {{"clips":[{{"id":"...","summary":"","understandable":0,"ending_unresolved":0,"would_tap_next":0,"issue":""}}]}}"""
        res = llm.complete_json(VERIFY_SYSTEM, prompt)
        by = {s["id"]: s for s in res.get("clips", [])}
        for c in chunk:
            if c.cid in by: c.verify = by[c.cid]

def finalize(c, use_llm):
    """Final 0-10 score and reject flag. Transparent weighted formula."""
    if use_llm and not c.llm:
        c.final = 0.0
        c.verify = {"rejected": True, "issue": "not scored by LLM", "unscored": True}
        return
    h = c.h
    if use_llm and c.llm:
        L, V = c.llm, c.verify
        g = lambda d, k, dflt: float(d.get(k, dflt))
        stranger = (g(V, "understandable", L.get("standalone", 5)) + g(V, "ending_unresolved", L.get("cliffhanger", 5))) / 2 if V else g(L, "standalone", 5)
        c.final = (0.30 * g(L, "hook", h["hook"]) + 0.30 * g(L, "cliffhanger", h["cliff"]) + 0.10 * g(L, "intensity", h["intensity"])
                   + 0.10 * g(L, "standalone", h["standalone"]) + 0.20 * stranger)
        if V and (g(V, "understandable", 10) < 5 or g(V, "ending_unresolved", 10) < 5):
            c.verify["rejected"] = True
    else:
        c.final = h["total"]
        if h["cliff"] < 4 or h["standalone"] < 4: c.verify["rejected"] = True

def hook_text(c):
    if c.llm.get("hook_line"): return c.llm["hook_line"]
    for e in c.events:
        if e.start >= c.segments[0].start - .01 and e.kind in ("DIALOGUE", "ACTION"):
            return (f"{e.speaker}: " if e.speaker else "(action) ") + e.text
    return ""

def cliff_text(c):
    if c.llm.get("cliffhanger_desc"): return c.llm["cliffhanger_desc"]
    last = [e for e in c.events if e.kind in ("DIALOGUE", "ACTION")][-1:]
    return (f"{last[0].speaker}: " if last and last[0].speaker else "(action) ") + last[0].text if last else ""

def why_text(c):
    return c.llm.get("why") or (f"[heuristic] hook {c.h['hook']:.1f}, cliffhanger {c.h['cliff']:.1f}, "
                                f"standalone {c.h['standalone']:.1f}, intensity {c.h['intensity']:.1f}")
