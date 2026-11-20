"""LLM judgment layer. The model only scores/picks from code-generated candidates (ids), never emits timestamps."""
import json, sys, re
from .candidates import fmt

def _norm_id(val):
    if not isinstance(val, str): val = str(val)
    return val.strip().strip("'\"“”`").lower()

def hook_check(c):
    hl = (c.llm.get("hook_line") or "").lower()
    words = re.findall(r"[a-z']{4,}", hl)
    if not words:
        return 1.0
    clip_text = " ".join((e.text or "") for e in c.events).lower()
    matches = sum(1 for w in words if w in clip_text)
    return matches / len(words)

def _extract_times(s):
    matches = re.findall(r"\d{1,2}:\d{2}(?:\.\d+)?", str(s))
    times = []
    for m in matches:
        parts = m.split(":")
        sec = int(parts[0]) * 60 + float(parts[1])
        times.append(sec)
    return times

def match_results(items, returned):
    matched = {}
    used_ret = set()

    # a) exact match on normalised id
    for item in items:
        target_nid = _norm_id(item.cid)
        for idx, r in enumerate(returned):
            if idx in used_ret or not isinstance(r, dict):
                continue
            if _norm_id(r.get("id", "")) == target_nid:
                r["_match"] = "id"
                matched[item.cid] = r
                used_ret.add(idx)
                break

    # b) match on the last two timestamps
    for item in items:
        if item.cid in matched:
            continue
        c_times = _extract_times(item.cid)
        if len(c_times) < 2:
            continue
        candidate_matches = []
        for idx, r in enumerate(returned):
            if idx in used_ret or not isinstance(r, dict):
                continue
            r_times = _extract_times(r.get("id", ""))
            if len(r_times) >= 2 and abs(c_times[-2] - r_times[-2]) < 0.5 and abs(c_times[-1] - r_times[-1]) < 0.5:
                candidate_matches.append((idx, r))
        if len(candidate_matches) == 1:
            idx, r = candidate_matches[0]
            r["_match"] = "time"
            matched[item.cid] = r
            used_ret.add(idx)

    # c) positional
    if len(returned) == len(items):
        for idx, item in enumerate(items):
            if item.cid not in matched and idx not in used_ret:
                r = returned[idx]
                if isinstance(r, dict):
                    r["_match"] = "position"
                    matched[item.cid] = r
                    used_ret.add(idx)

    return matched

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
    matched = match_results(cands, scores_list)
    for c in cands:
        if c.cid in matched: c.llm = matched[c.cid]

    if any(c.llm.get("_match") in ("time", "position") for c in cands if c.llm):
        exp_ids = [c.cid for c in cands[:3]]
        got_ids = [r.get("id", "") for r in scores_list[:3] if isinstance(r, dict)]
        print(f"[score] ep {ep.num}: id mismatch, expected {exp_ids} got {got_ids}", file=sys.stderr)

    missing = [c for c in cands if not c.llm]
    if len(scores_list) < len(cands) and missing:
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
            r_matched = match_results(chunk, r_scores)
            for c in chunk:
                if c.cid in r_matched: c.llm = r_matched[c.cid]

    dropped = 0
    for c in cands:
        if c.llm and c.llm.get("_match") in ("time", "position"):
            if hook_check(c) < 0.25:
                c.llm = {}
                c.verify = {"rejected": True, "issue": "match_suspect: hook_line does not appear in this clip", "unscored": True, "suspect": True}
                dropped += 1
    if dropped > 0:
        print(f"[score] ep {ep.num}: dropped {dropped} suspect matches", file=sys.stderr)

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
        clips_list = res.get("clips", []) if isinstance(res, dict) else []
        matched = match_results(chunk, clips_list)
        for c in chunk:
            if c.cid in matched: c.verify = matched[c.cid]

def finalize(c, use_llm):
    """Final 0-10 score and reject flag. Transparent weighted formula."""
    if c.verify and c.verify.get("suspect"):
        c.final = 0.0
        return
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
