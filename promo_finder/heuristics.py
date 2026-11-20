"""Cheap, transparent signals. Used to (1) shortlist candidates before any LLM call and
(2) act as an offline baseline scorer when no API key is available."""
import re

HOOK_WORDS = r"slap|strike|struck|shove|grab|seize|hurl|throw|collaps|scream|gasp|blood|dagger|sword|knife|kill|dead|death|die|betray|traitor|lie[sd]?\b|liar|poison|pregnan|child|bastard|divorce|annul|banish|exile|arrest|guilty|duke|king|queen|prince|secret|truth|reveal|impostor|fake|mine\b|never|how dare|get out|you will pay|who are you|what did you|you lied|kneel|beg"
SHOCK_ACTION = r"slap|strike|struck|shove|grab|seiz|hurl|throw|thrust|collaps|bursts?|kick|draws? (?:a |his |her )?(?:sword|dagger|blade)|blood|stagger|recoil|freez|gasp|shatter|smash|tears? (?:off|open)"
CLIFF_SFX = r"cliffhanger|sting|ominous|abrupt|cut to black|swell|shock|silence|sharp|thunder|crash"
RESOLVE = r"embrace|kiss|smil|laugh|thank you|forgive|safe now|peace|relief|tender|reconcil|warm|sleep|rest\b"
TEASE = r"\?\s*$|\.\.\.\s*$|—\s*$|-\s*$"
INTENSE_TONE = r"furious|rage|shock|stunn|gasp|scream|shout|cold|menac|threat|panic|desperat|anguish|broken|trembl|sneer|command|fierce|horrif|disbelief"

def first_window(events, t0, secs=3.0):
    return [e for e in events if e.start < t0 + secs and e.kind in ("DIALOGUE", "ACTION")]

def last_window(events, t1, secs=4.0):
    return [e for e in events if e.end > t1 - secs]

def hook_score(events, t0):
    """0-10. Look only at the first 3 seconds of the clip."""
    w = first_window(events, t0)
    if not w: return 1.0
    s = 2.0
    for e in w:
        txt = e.text.lower()
        if e.kind == "ACTION" and re.search(SHOCK_ACTION, txt): s += 3
        if e.kind == "DIALOGUE":
            n = len(txt.split())
            if re.search(HOOK_WORDS, txt): s += 2
            if "!" in e.text: s += 1.5
            if n <= 9: s += 1          # punchy
            if re.search(INTENSE_TONE, e.tone, re.I): s += 1
            if e.text.strip().lower().rstrip("?.!") in ("yes", "no", "why", "what", "i see", "very well", "thank you", "good morning"):
                s -= 3                 # a reply with no context is a weak opener
            if n > 22: s -= 1.5        # long speech is not a scroll-stopper
    return max(0.0, min(10.0, s))

def cliff_score(events, t1, ep_end, ep_is_last_clip=False):
    """0-10. Look at the last ~4s of the clip."""
    w = last_window(events, t1)
    if not w: return 1.0
    s = 2.0
    blob = " ".join(e.text.lower() for e in w)
    last = [e for e in w if e.kind in ("DIALOGUE", "ACTION")]
    if last:
        le = last[-1]
        if re.search(TEASE, le.text): s += 2.5
        if le.kind == "DIALOGUE" and len(le.text.split()) <= 10: s += 1
        if le.kind == "ACTION" and re.search(SHOCK_ACTION, le.text.lower()): s += 2.5
    for e in w:
        if e.kind == "SFX" and re.search(CLIFF_SFX, e.text.lower()): s += 2.5; break
    if abs(ep_end - t1) < 2.0: s += 1.5   # episode-end cuts are usually written as cliffhangers
    if re.search(RESOLVE, blob): s -= 3
    return max(0.0, min(10.0, s))

def intensity_score(events):
    tones = sum(bool(re.search(INTENSE_TONE, e.tone, re.I)) for e in events if e.kind == "DIALOGUE")
    bangs = sum(e.text.count("!") for e in events if e.kind == "DIALOGUE")
    acts = sum(bool(re.search(SHOCK_ACTION, e.text.lower())) for e in events if e.kind == "ACTION")
    return max(0.0, min(10.0, 1 + tones * 0.8 + bangs * 0.4 + acts * 1.2))

def standalone_score(events, ep_num):
    """0-10. Fewer speakers, fewer dangling references -> easier for a stranger."""
    spk = {e.speaker for e in events if e.kind == "DIALOGUE" and not e.vo}
    s = 7.0
    if len(spk) < 2: s -= 2
    if len(spk) > 4: s -= (len(spk) - 4) * 1.2
    d = [e for e in events if e.kind == "DIALOGUE"]
    if d and re.match(r"(he|she|him|her|they|that|it|as i said|so)\b", d[0].text.lower()): s -= 1.5
    if sum(bool(re.search(r"\b(as before|last night|yesterday|remember when|i told you)\b", e.text.lower())) for e in d) >= 2: s -= 1
    if ep_num == 1: s += 1.5   # first episode introduces everyone
    return max(0.0, min(10.0, s))
