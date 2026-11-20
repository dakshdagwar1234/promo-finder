"""Parse Kuku-style screenplay .txt files into typed, timestamped events. Pure code, no LLM."""
import re, glob, os
from dataclasses import dataclass, field

NON_DIALOGUE = {"CAMERA", "ACTION", "SOUND FX"}
BLOCK = re.compile(
    r'^\*\*(.+?):\*\*\nStart: \((\d+):(\d+\.\d+)\) \| End: \((\d+):(\d+\.\d+)\)\n(.*?)(?=\n\n|\Z)',
    re.M | re.S)

@dataclass
class Event:
    idx: int
    kind: str          # DIALOGUE | ACTION | CAMERA | SFX
    speaker: str       # "" for non-dialogue
    tone: str          # parenthetical, e.g. "Cold, Commanding"
    text: str
    start: float
    end: float
    vo: bool = False

@dataclass
class Episode:
    num: int
    path: str
    logline: str
    continuity: str
    duration: float
    events: list = field(default_factory=list)
    scene_starts: list = field(default_factory=list)  # (time, heading)

def _sec(m, s):
    return int(m) * 60 + float(s)

def parse_episode(path):
    t = open(path, encoding="utf-8").read()
    num = int(re.search(r"EPISODE NUMBER:\s*Episode\s+(\d+)", t).group(1))
    g = lambda k: (re.search(rf"{k}:\s*(.*)", t) or [None, ""])[1].strip()
    ep = Episode(num, path, g("EPISODE LOGLINE"), g("CONTINUITY NOTES"), 0.0)
    for m in re.finditer(r"Scene heading:\s*(.*)\nScene start:\s*(\d+):(\d+\.\d+)\nScene end:\s*(\d+):(\d+\.\d+)", t):
        ep.scene_starts.append((_sec(m[2], m[3]), m[1].strip()))
        ep.duration = max(ep.duration, _sec(m[4], m[5]))
    for i, m in enumerate(BLOCK.finditer(t)):
        head, txt = m[1], " ".join(m[6].split())
        name, tone = (head.split(" (", 1) + [""])[:2]
        tone = tone.rstrip(")")
        name = name.strip()
        if name in NON_DIALOGUE:
            kind, spk = {"SOUND FX": "SFX"}.get(name, name), ""
        else:
            kind, spk = "DIALOGUE", name.title()
            txt = txt.strip('"“”')
        ep.events.append(Event(i, kind, spk, tone, txt, _sec(m[2], m[3]), _sec(m[4], m[5]),
                               vo=bool(re.search(r"V\.?O|off-?screen", tone, re.I))))
    ep.events.sort(key=lambda e: (e.start, e.end))
    for i, e in enumerate(ep.events): e.idx = i
    if ep.events: ep.duration = max(ep.duration, ep.events[-1].end)
    return ep

def load_show(folder):
    files = sorted(glob.glob(os.path.join(folder, "**", "*.txt"), recursive=True))
    eps = [parse_episode(f) for f in files]
    return sorted(eps, key=lambda e: e.num)
