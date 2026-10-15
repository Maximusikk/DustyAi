"""AI providers for the optional “AI analysis” button: free tiers, a local model, or your own paid key.

Three wire formats cover everything: OpenAI-compatible chat completions (OpenAI, Groq, OpenRouter, Gemini's
compatibility endpoint, Ollama, LM Studio, DeepSeek, Mistral, ...), Anthropic Messages, and Cloudflare Workers AI.
Only names and sizes of a few findings are ever sent (no file paths); with a local model nothing leaves the PC.
Keys live in ai.json inside the app's data folder and are never sent back to the page."""
import json
import os
import threading
import urllib.error
import urllib.request

import settings

CONFIG_FILE = os.path.join(settings.DATA_DIR, "ai.json")
_lock = threading.Lock()

# group: free = has a free tier, local = runs on this PC, paid = bring your own paid key
PROVIDERS = [
    dict(id="cloudflare", name="Cloudflare Workers AI", group="free", kind="cloudflare", account=True, key=True,
         model="@cf/meta/llama-3.2-3b-instruct", url="https://dash.cloudflare.com/profile/api-tokens",
         note="Free daily limit. Needs your Account ID and an API token with Workers AI permission."),
    dict(id="groq", name="Groq", group="free", kind="openai", key=True, base="https://api.groq.com/openai/v1",
         model="llama-3.1-8b-instant", url="https://console.groq.com/keys", note="Free tier, very fast."),
    dict(id="openrouter", name="OpenRouter", group="free", kind="openai", key=True,
         base="https://openrouter.ai/api/v1", model="meta-llama/llama-3.3-70b-instruct:free",
         url="https://openrouter.ai/keys", note="Many free models (their names end with :free)."),
    dict(id="gemini", name="Google Gemini", group="free", kind="openai", key=True,
         base="https://generativelanguage.googleapis.com/v1beta/openai", model="gemini-2.0-flash",
         url="https://aistudio.google.com/apikey", note="Free tier in Google AI Studio."),
    dict(id="ollama", name="Ollama (this PC)", group="local", kind="openai", key=False, base_editable=True,
         base="http://localhost:11434/v1", model="llama3.2", url="https://ollama.com/download",
         note="Runs on your computer: nothing leaves it. Install Ollama and pull a model first."),
    dict(id="openai", name="OpenAI (ChatGPT)", group="paid", kind="openai", key=True,
         base="https://api.openai.com/v1", model="gpt-4o-mini", url="https://platform.openai.com/api-keys",
         note="Paid, pay as you go."),
    dict(id="anthropic", name="Anthropic (Claude)", group="paid", kind="anthropic", key=True,
         base="https://api.anthropic.com/v1", model="claude-haiku-5-5",
         url="https://console.anthropic.com/settings/keys", note="Paid, pay as you go."),
    dict(id="custom", name="Other (OpenAI-compatible)", group="custom", kind="openai", key=True, base_editable=True,
         base="", model="", note="Any OpenAI-compatible endpoint: LM Studio, DeepSeek, Mistral, Together, ..."),
]
BY_ID = {p["id"]: p for p in PROVIDERS}
MAX_TOKENS = 700  # leave room for a full answer: 300 cut the reply off


class AIError(Exception):
    """Shown to the user; never contains a key."""

    def __init__(self, message, code=502):
        super().__init__(message)
        self.code = code


def load():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(changes):
    """changes: {provider, settings: {key, model, base, account}} — empty strings keep the stored value;
    {"clear": id} removes that provider's settings."""
    with _lock:
        d = load()
        d.setdefault("providers", {})
        pid = changes.get("provider")
        if pid is not None:
            if pid not in BY_ID:
                raise AIError("Unknown provider", 400)
            d["provider"] = pid
        if changes.get("clear") in BY_ID:
            d["providers"].pop(changes["clear"], None)
        for pid2, vals in (changes.get("settings") or {}).items():
            if pid2 not in BY_ID or not isinstance(vals, dict):
                continue
            cur = d["providers"].setdefault(pid2, {})
            for k in ("key", "model", "base", "account"):
                v = str(vals.get(k) or "").strip()
                if not v:
                    continue
                if len(v) > 400 or "\n" in v or "\r" in v:
                    raise AIError("Invalid value", 400)
                if k == "base" and not v.lower().startswith(("http://", "https://")):
                    raise AIError("The address must start with http:// or https://", 400)
                cur[k] = v
        os.makedirs(settings.DATA_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        return d


def resolve(fallback_cloudflare=None):
    """(provider dict, effective settings) for the selected provider, or (None, None) if nothing is set up.
    fallback_cloudflare() may return legacy {key, account, model} (the old .env file) for Cloudflare."""
    d = load()
    pid = d.get("provider")
    stored = d.get("providers") or {}
    if not pid and fallback_cloudflare and (fallback_cloudflare() or {}).get("key"):
        pid = "cloudflare"
    p = BY_ID.get(pid)
    if not p:
        return None, None
    s = dict(stored.get(pid) or {})
    if pid == "cloudflare" and fallback_cloudflare and not s.get("key"):
        legacy = fallback_cloudflare() or {}
        for k in ("key", "account", "model"):
            s.setdefault(k, legacy.get(k) or "")
    s["model"] = s.get("model") or p["model"]
    s["base"] = s.get("base") or p.get("base", "")
    if p.get("key") and not s.get("key"):
        return p, None
    if p.get("account") and not s.get("account"):
        return p, None
    if p["id"] == "custom" and not (s.get("base") and s.get("model")):
        return p, None
    return p, s


def public_state(fallback_cloudflare=None):
    """What the Settings page may see: which providers are filled in, never the keys."""
    d = load()
    stored = d.get("providers") or {}
    legacy = (fallback_cloudflare() or {}) if fallback_cloudflare else {}
    out = []
    for p in PROVIDERS:
        s = stored.get(p["id"]) or {}
        has_key = bool(s.get("key")) or (p["id"] == "cloudflare" and bool(legacy.get("key")))
        has_acc = bool(s.get("account")) or (p["id"] == "cloudflare" and bool(legacy.get("account")))
        out.append({"id": p["id"], "name": p["name"], "group": p["group"], "needs_key": p.get("key", False),
                    "needs_account": p.get("account", False), "base_editable": p.get("base_editable", False),
                    "default_model": p["model"], "default_base": p.get("base", ""), "url": p.get("url"),
                    "note": p.get("note", ""), "has_key": has_key, "has_account": has_acc,
                    "model": s.get("model") or (legacy.get("model") if p["id"] == "cloudflare" else "") or "",
                    "base": s.get("base") or ""})
    prov, eff = resolve(fallback_cloudflare)
    return {"selected": (prov or {}).get("id") or d.get("provider"), "ready": bool(eff), "providers": out}


def _error_text(e):
    try:
        body = json.load(e)
    except (ValueError, OSError):
        return ""
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        err = err.get("message")
    if not err and isinstance(body, dict) and body.get("errors"):
        err = "; ".join(str(x.get("message", "")) for x in body["errors"] if isinstance(x, dict))
    return str(err or "")[:200]


def _post(p, url, headers, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        hint = {401: "the key is invalid", 403: "the key has no permission for this", 404: "model or address not found",
                429: "rate limit or quota exceeded"}.get(e.code, "")
        detail = _error_text(e)
        raise AIError(f"{p['name']} returned {e.code}" + (f": {hint}" if hint else "")
                      + (f" ({detail})" if detail and detail != hint else ""))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        extra = " Is Ollama running?" if p["id"] == "ollama" else ""
        raise AIError(f"Cannot reach {p['name']}: {getattr(e, 'reason', e)}.{extra}")
    except ValueError:
        raise AIError(f"{p['name']} returned an invalid response")


def complete(p, s, system, user, cf_base="https://api.cloudflare.com/client/v4"):
    """One chat completion → text."""
    timeout = 120 if p["group"] == "local" else 45
    if p["kind"] == "cloudflare":
        url = f"{os.environ.get('CF_API_BASE', cf_base).rstrip('/')}/accounts/{s['account']}/ai/run/{s['model']}"
        data = _post(p, url, {"Authorization": f"Bearer {s['key']}"},
                     {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                      "max_tokens": MAX_TOKENS, "temperature": 0.2}, timeout)
        text = ((data.get("result") or {}).get("response") or "")
        if not data.get("success", True) or not text.strip():
            raise AIError("Empty model response")
        return text
    base = s["base"].rstrip("/")
    if p["kind"] == "anthropic":
        data = _post(p, base + "/messages", {"x-api-key": s["key"], "anthropic-version": "2023-06-01"},
                     {"model": s["model"], "max_tokens": MAX_TOKENS, "system": system, "temperature": 0.2,
                      "messages": [{"role": "user", "content": user}]}, timeout)
        text = "".join(b.get("text", "") for b in data.get("content") or [] if isinstance(b, dict))
    else:
        headers = {"Authorization": f"Bearer {s['key']}"} if s.get("key") else {}
        limit = {"max_completion_tokens" if p["id"] == "openai" else "max_tokens": MAX_TOKENS}
        data = _post(p, base + "/chat/completions", headers,
                     {"model": s["model"], "temperature": 0.2, **limit,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, timeout)
        choices = data.get("choices") or [{}]
        text = ((choices[0].get("message") or {}).get("content") or "")
    if not text.strip():
        raise AIError("Empty model response")
    return text
