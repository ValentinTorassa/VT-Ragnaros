"""Minimal client for Jev (TypeSafe AI), a decision model.

Jev reads a JSON "state" and answers closed questions with probabilities; it
never writes text. Only yes/no questions are used here: each comes back with
the probability that the answer is yes.

Two ways to reach it, chosen with `provider`:
  vercel      (default) Vercel AI Gateway, POST /v1/evaluate; questions go out as
              `type: "boolean"` and come back as `answers[id].probability`. Asks
              the gateway for TypeSafe only.
  openrouter  OpenRouter, POST /api/v1/systemone; TypeSafe's own format, where a
              boolean goes out as `type: "noul"` and comes back as `answers[id].noul`.

The key comes from the provider's variable ($AI_GATEWAY_API_KEY or
$OPENROUTER_API_KEY) or from a key file that only its owner can read
(`chmod 600`), by default ~/.config/ragnaros/jev.key ($RAGNAROS_JEV_KEY_FILE
elsewhere), holding the key of the provider in use. It is never written anywhere.

Nothing here retries or waits long: callers that run on every Claude Code
stop wrap the call in within() and fall back to their own behaviour.
"""
import json
import os
import stat
import threading

from . import paths

PROVIDERS = {
    "vercel": {"url": "https://ai-gateway.vercel.sh/v1/evaluate",
               "model": "typesafe-ai/jev-1.14.0", "key_env": "AI_GATEWAY_API_KEY",
               # TypeSafe only, so the gateway never routes the call elsewhere. No
               # zeroDataRetention: on a Hobby plan the gateway answers 403 to it.
               "options": {"gateway": {"only": ["typesafe-ai"]}}},
    "openrouter": {"url": "https://openrouter.ai/api/v1/systemone",
                   "model": "typesafe/jev-1.14", "key_env": "OPENROUTER_API_KEY"},
}
DEFAULT_PROVIDER = "vercel"


def provider_name(name=None):
    name = str(name or DEFAULT_PROVIDER).strip().lower()
    return name if name in PROVIDERS else DEFAULT_PROVIDER


def model(provider=None):
    """A pinned version: a new model moves the probabilities and needs a new eval."""
    return os.environ.get("RAGNAROS_JEV_MODEL") or PROVIDERS[provider_name(provider)]["model"]


def key_file():
    return os.path.expanduser(os.environ.get("RAGNAROS_JEV_KEY_FILE")
                              or os.path.join(paths.config_dir(), "jev.key"))


def api_key(provider=None):
    """(key, None), or (None, why there is no usable key)."""
    variable = PROVIDERS[provider_name(provider)]["key_env"]
    if os.environ.get(variable, "").strip():
        return os.environ[variable].strip(), None
    path = key_file()
    try:
        mode = os.stat(path).st_mode
        if not stat.S_ISREG(mode):
            return None, "key file is not a regular file"
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            return None, "key file readable by others (chmod 600 it)"
        with open(path) as f:
            key = f.read().strip()
    except FileNotFoundError:
        return None, "no key"
    except OSError as error:
        return None, f"key file: {type(error).__name__}"
    return (key, None) if key else (None, "empty key file")


def body(state, questions, provider=None, model_name=None):
    """The request body in the provider's format."""
    provider = provider_name(provider)
    if provider == "openrouter":
        questions = {qid: dict(q, type="noul") if q.get("type") == "boolean" else dict(q)
                     for qid, q in questions.items()}
    request = {"model": model_name or model(provider), "state": state, "questions": questions}
    if PROVIDERS[provider].get("options"):
        request["providerOptions"] = PROVIDERS[provider]["options"]
    return request


def evaluate(state, questions, key, provider=None, model_name=None, timeout=1.5):
    """One POST, no retries; returns the decoded reply ({answers, usage, ...})."""
    import urllib.request  # ~20 ms to import: only the background worker pays it

    provider = provider_name(provider)
    request = urllib.request.Request(
        PROVIDERS[provider]["url"], method="POST",
        data=json.dumps(body(state, questions, provider, model_name)).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.load(reply)


def probability(reply, qid):
    """The yes-probability of one question (`probability` from the gateway, `noul`
    from OpenRouter); ValueError on a malformed reply."""
    try:
        answer = reply["answers"][qid]
        p = answer.get("probability", answer.get("noul"))
    except (KeyError, TypeError, AttributeError):
        raise ValueError(f"no answer for {qid!r}") from None
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
        raise ValueError(f"no probability for {qid!r}")
    return float(p)


def usage(reply):
    """What the call cost, when the provider says: {"cost": USD, "tokens": input tokens}."""
    out = {}
    if not isinstance(reply, dict):
        return out
    gateway = (reply.get("providerMetadata") or {}).get("gateway") or {}
    counts = reply.get("usage") if isinstance(reply.get("usage"), dict) else {}
    for value in (gateway.get("cost"), counts.get("cost")):
        try:
            out["cost"] = float(value)  # the gateway sends it as a string
            break
        except (TypeError, ValueError):
            continue
    tokens = counts.get("inputTokens", counts.get("prompt_tokens"))
    if isinstance(tokens, int) and not isinstance(tokens, bool):
        out["tokens"] = tokens
    return out


def within(seconds, fn, *args):
    """fn(*args), or TimeoutError once `seconds` of wall clock have passed.

    A socket timeout alone does not bound DNS or a slow trickle of bytes;
    the call runs in a daemon thread that the process simply leaves behind.
    """
    result = {}

    def run():
        try:
            result["value"] = fn(*args)
        except BaseException as error:  # handed back to the caller below
            result["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise TimeoutError(f"no answer in {seconds:g} s")
    if "error" in result:
        raise result["error"]
    return result["value"]
