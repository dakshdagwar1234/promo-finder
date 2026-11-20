"""Model-agnostic LLM layer. Plain HTTP, no SDKs. Swap model/provider via env or CLI.
Providers: gemini | anthropic | openai (any OpenAI-compatible endpoint) | none (heuristic only).
Responses are cached on disk by prompt hash, so re-runs are free and interview re-runs are fast."""
import os, sys, json, time, hashlib, urllib.request, urllib.error, re

CACHE = os.environ.get("PROMO_CACHE", ".llm_cache")

class LLM:
    def __init__(self, provider=None, model=None, api_key=None, base_url=None):
        self.provider = (provider or os.environ.get("LLM_PROVIDER", "none")).lower()
        self.model = model or os.environ.get("LLM_MODEL", "")
        self.key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base = base_url or os.environ.get("LLM_BASE_URL", "")
        self.calls = self.cached = 0
        self.tokens_in = self.tokens_out = 0
        os.makedirs(CACHE, exist_ok=True)

    @property
    def enabled(self): return self.provider not in ("none", "")

    def complete_json(self, system, prompt, retries=4):
        key = hashlib.sha256(f"{self.provider}|{self.model}|{system}|{prompt}".encode()).hexdigest()
        cp = os.path.join(CACHE, key + ".json")
        if os.path.exists(cp):
            self.cached += 1
            return json.load(open(cp, encoding="utf-8"))
        last_err = None
        for attempt in range(retries):
            try:
                raw = self._call(system, prompt)
                data = _parse_json(raw)
                json.dump(data, open(cp, "w", encoding="utf-8"))
                self.calls += 1
                return data
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError, TypeError, IndexError) as e:
                code = getattr(e, "code", None)
                if isinstance(e, urllib.error.HTTPError):
                    body = e.read().decode("utf-8", "ignore")[:500]
                    last_err = f"HTTP {code}: {body}"
                    if code in (400, 401, 403, 404):
                        raise RuntimeError(f"LLM request rejected ({code}): check key/model name. {e} {body}")
                else:
                    last_err = repr(e)
                print(f"[llm] attempt {attempt + 1}/{retries} failed: {last_err}", file=sys.stderr)
                if code == 429:
                    ra = e.headers.get("Retry-After") if hasattr(e, "headers") and e.headers else None
                    try:
                        wait = min(float(ra), 60.0) if ra is not None else 15 * (attempt + 1)
                    except (ValueError, TypeError):
                        wait = 15 * (attempt + 1)
                    time.sleep(wait)
                else:
                    time.sleep(15 * (attempt + 1))
        raise RuntimeError(f"LLM failed after retries. Last error: {last_err}")

    # --- providers -------------------------------------------------------
    def _post(self, url, body, headers):
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "promo-finder/1.0", **headers})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)

    def _call(self, system, prompt):
        if self.provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.key}"
            d = self._post(url, {"systemInstruction": {"parts": [{"text": system}]},
                                 "contents": [{"parts": [{"text": prompt}]}],
                                 "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}, {})
            u = d.get("usageMetadata", {}); self.tokens_in += u.get("promptTokenCount", 0); self.tokens_out += u.get("candidatesTokenCount", 0)
            return d["candidates"][0]["content"]["parts"][0]["text"]
        if self.provider == "anthropic":
            d = self._post("https://api.anthropic.com/v1/messages",
                           {"model": self.model, "max_tokens": 4000, "temperature": 0.2, "system": system,
                            "messages": [{"role": "user", "content": prompt}]},
                           {"x-api-key": self.key, "anthropic-version": "2023-06-01"})
            u = d.get("usage", {}); self.tokens_in += u.get("input_tokens", 0); self.tokens_out += u.get("output_tokens", 0)
            return d["content"][0]["text"]
        if self.provider == "openai":
            base = (self.base or "https://api.openai.com/v1").rstrip("/")
            d = self._post(f"{base}/chat/completions",
                           {"model": self.model, "temperature": 0.2, "response_format": {"type": "json_object"},
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
                           {"Authorization": f"Bearer {self.key}"})
            u = d.get("usage", {}); self.tokens_in += u.get("prompt_tokens", 0); self.tokens_out += u.get("completion_tokens", 0)
            return d["choices"][0]["message"]["content"]
        raise ValueError(f"unknown provider {self.provider}")

def _parse_json(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try: return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", raw, re.S)
        if not m: raise ValueError("no JSON in response")
        return json.loads(m.group(0))
