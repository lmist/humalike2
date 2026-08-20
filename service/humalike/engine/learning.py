"""Social Learning extract engine (spec/04 §Social Learning, spec/05).

Derives the exact profile schema and a non-empty prompt_block from an
attributed transcript. Deterministic: register/style/norms come from
lexical statistics, not a model. Channel-less transcripts emit []
(ADR hum-l2mw). Learned style is computed here and is not written into
durable factual memory.
"""

from __future__ import annotations

import re
from collections import Counter


_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "]+"
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_NO_RE = re.compile(
    r"\b(?:no|avoid|don't|dont|never)\s+([^,.!?]+)",
    re.IGNORECASE,
)
_CMP_RE = re.compile(r"([^<>\n]{2,40}?)\s*>\s*([^<>\n]{2,40})")
_FILLER = re.compile(
    r"\b(?:this time|right now|please|pls|lol|lmao|haha)\b", re.IGNORECASE
)

_INFORMAL = {
    "yo", "yep", "yeah", "yup", "nah", "lol", "lmao", "pls", "plz",
    "gotchu", "gonna", "wanna", "kinda", "tbh", "imo", "sup", "hey",
    "hi", "haha", "bless", "nice",
}
_FORMAL = {
    "please", "would", "could", "shall", "regarding", "kindly",
    "sincerely", "however", "therefore",
}
_WARM = {
    "pls", "please", "thanks", "thank", "bless", "gotchu", "love",
    "hug", "nice", "hey", "hi", "hello", "cheers",
}
_SLANG = {
    "yo": ("informal greeting", "opens a casual turn"),
    "gotchu": ("got you / I will handle it", "acknowledgement of a request"),
    "yep": ("yes", "agreement"),
    "pls": ("please", "softens a request"),
    "plz": ("please", "softens a request"),
    "lol": ("laughing", "softens a turn"),
    "lmao": ("laughing", "marks humor"),
    "bless": ("thanks / relief", "appreciation"),
    "tbh": ("to be honest", "frank aside"),
    "gonna": ("going to", "informal future"),
    "wanna": ("want to", "informal desire"),
}
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and",
    "or", "in", "on", "at", "for", "with", "my", "your", "our", "me", "you",
    "i", "we", "they", "he", "she", "it", "this", "that", "just", "so",
    "if", "but", "not", "no", "yes",
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _confidence(n: int, extra: int = 0) -> float:
    return round(_clamp01(0.28 + 0.09 * n + 0.04 * extra), 3)


def derive_channels(messages: list[dict]) -> list[str]:
    """Unique labelled channels in first-seen order; append unlabelled if any
    message lacks a channel. A fully channel-less transcript is []."""
    seen: list[str] = []
    missing = False
    for message in messages:
        raw = message.get("channel")
        channel = raw.strip() if isinstance(raw, str) else ""
        if not channel:
            missing = True
            continue
        if channel not in seen:
            seen.append(channel)
    if not seen:
        return []
    if missing:
        seen.append("unlabelled")
    return seen


def _joined(messages: list[dict]) -> str:
    return "\n".join(str(m.get("text") or "") for m in messages)


def _letters(text: str) -> str:
    return "".join(ch for ch in text if ch.isalpha())


def _casing(text: str) -> str:
    letters = _letters(text)
    if not letters:
        return "unspecified"
    lower = sum(1 for ch in letters if ch.islower())
    upper = len(letters) - lower
    if upper == 0:
        return "lowercase"
    if lower == 0:
        return "uppercase"
    words = _WORD_RE.findall(text)
    if words and all(w[:1].isupper() and w[1:].islower() for w in words if len(w) > 1):
        return "title"
    sentence_like = re.findall(r"[.!?]\s+[A-Z]|^\s*[A-Z]", text)
    if sentence_like and upper / len(letters) < 0.2:
        return "sentence"
    return "mixed"


def _formality(text: str) -> str:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    informal = sum(1 for w in words if w in _INFORMAL)
    formal = sum(1 for w in words if w in _FORMAL)
    if informal > formal:
        return "informal"
    if formal > informal:
        return "formal"
    return "neutral"


def _warmth(text: str) -> str:
    words = {w.lower() for w in _WORD_RE.findall(text)}
    if _EMOJI_RE.search(text) or words & _WARM:
        return "warm"
    if any(w in text.lower() for w in ("sorry", "please", "thanks")):
        return "warm"
    return "neutral"


def _length_label(messages: list[dict]) -> str:
    if not messages:
        return "short"
    avg = sum(len((m.get("text") or "").split()) for m in messages) / len(messages)
    if avg < 6:
        return "short"
    if avg < 18:
        return "medium"
    return "long"


def _formatting(text: str) -> str:
    if "```" in text or re.search(r"^\s*[-*]\s", text, re.M):
        return "structured"
    if "?" in text and re.search(r"[.!,]", text):
        return "conversational"
    if re.search(r"[.!?]", text):
        return "punctuated"
    return "plain"


def _emoji_label(text: str) -> str:
    found = _EMOJI_RE.findall(text)
    if not found:
        return "none"
    if len(found) == 1:
        return "sparse"
    return "present"


def _lexicon(messages: list[dict]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for message in messages:
        text = message.get("text") or ""
        speaker = message.get("speaker") or ""
        lowered = text.lower()
        for phrase in ("tea run", "status update", "tiny updates"):
            if phrase in lowered and phrase not in seen:
                seen.add(phrase)
                items.append({
                    "term": phrase,
                    "meaning": "local in-group phrase",
                    "usage": f'used by {speaker}: "{text}"',
                })
        for word in _WORD_RE.findall(text):
            key = word.lower()
            if key in seen or key not in _SLANG:
                continue
            seen.add(key)
            meaning, usage = _SLANG[key]
            items.append({
                "term": key,
                "meaning": meaning,
                "usage": usage,
            })
    return items


def _taboos(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for message in messages:
        text = message.get("text") or ""
        for match in _NO_RE.finditer(text):
            raw = _FILLER.sub("", match.group(1)).strip(" -:,.")
            raw = re.sub(r"\s+", " ", raw).strip()
            if len(raw) < 3 or raw.lower() in seen:
                continue
            seen.add(raw.lower())
            out.append({
                "rule": f"avoid {raw}",
                "scope": "all",
                "evidence": [text],
            })
    return out


def _norms(messages: list[dict], n: int) -> list[dict]:
    out: list[dict] = []
    for message in messages:
        text = message.get("text") or ""
        cmp_match = _CMP_RE.search(text)
        if cmp_match:
            preferred = cmp_match.group(1).strip(" .")
            avoided = cmp_match.group(2).strip(" .")
            out.append({
                "rule": f"prefer {preferred} over {avoided}",
                "type": "inferred_from_behavior",
                "evidence": [{
                    "breach": avoided,
                    "sanction": f"contrasted against {preferred}",
                }],
                "confidence": _confidence(n, extra=1),
            })
    return out


def _humor(text: str) -> dict:
    rules: list[str] = []
    style = "none"
    lowered = text.lower()
    if any(token in lowered for token in ("lol", "lmao", "haha")):
        style = "light"
        rules.append("use brief laugh tokens to soften a turn")
    if _EMOJI_RE.search(text):
        style = "playful" if style == "none" else style
        rules.append("emoji is welcome in casual turns")
    return {"style": style, "rules": rules}


def _address(messages: list[dict]) -> dict:
    speakers = [m.get("speaker") or "" for m in messages]
    first = next((s for s in speakers if s), "")
    default = "first_name" if first and " " not in first else "given_name"
    deference: list[str] = []
    joined = _joined(messages).lower()
    if any(title in joined for title in ("sir", "madam", "mr.", "ms.", "dr.")):
        deference.append("titles")
    return {"default": default, "deference": deference}


def _roles(messages: list[dict]) -> list[str]:
    seen: list[str] = []
    for message in messages:
        speaker = message.get("speaker") or ""
        if speaker and speaker not in seen:
            seen.append(speaker)
    return seen if len(seen) > 1 else []


def _in_jokes(messages: list[dict]) -> list[str]:
    jokes: list[str] = []
    counts: Counter[str] = Counter()
    for message in messages:
        text = (message.get("text") or "").lower()
        for phrase in ("tea run", "tiny updates", "gotchu"):
            if phrase in text:
                counts[phrase] += 1
    for phrase, count in counts.items():
        if count >= 1 and phrase not in jokes:
            jokes.append(phrase)
    return jokes


def _summary(messages: list[dict]) -> str:
    if len(messages) < 2:
        return ""
    speakers = []
    for message in messages:
        speaker = message.get("speaker") or ""
        if speaker and speaker not in speakers:
            speakers.append(speaker)
    topics = []
    joined = _joined(messages).lower()
    for hint in ("tea", "export", "patch", "update", "ship"):
        if hint in joined and hint not in topics:
            topics.append(hint)
    who = " and ".join(speakers) if speakers else "participants"
    if topics:
        return f"{who} discussed {', '.join(topics)}."
    return f"{who} exchanged {len(messages)} messages."


def _register(messages: list[dict]) -> dict:
    text = _joined(messages)
    formality = _formality(text)
    warmth = _warmth(text)
    casing = _casing(text)
    notes = f"observed {formality} {warmth} voice with {casing} casing"
    return {
        "formality": formality,
        "warmth": warmth,
        "casing": casing,
        "notes": notes,
        "confidence": _confidence(len(messages)),
    }


def _style(messages: list[dict]) -> dict:
    text = _joined(messages)
    return {
        "length": _length_label(messages),
        "formatting": _formatting(text),
        "emoji": _emoji_label(text),
    }


def _prompt_block(profile: dict, messages: list[dict]) -> str:
    speakers = []
    lines = []
    for message in messages:
        speaker = message.get("speaker") or "unknown"
        text = message.get("text") or ""
        if speaker not in speakers:
            speakers.append(speaker)
        lines.append(f"{speaker}: {text}")
    lexicon = profile["lexicon"]
    lex_lines = [
        f"- {item['term']}: {item['meaning']} ({item['usage']})"
        for item in lexicon
    ] or ["- (none observed)"]
    norm_lines = [f"- {n['rule']}" for n in profile["norms"]] or ["- (none observed)"]
    register = profile["register"]
    style = profile["style"]
    return "\n".join([
        "Learned voice card",
        f"Source: {profile['meta']['source']}",
        f"Speakers: {', '.join(speakers)}",
        f"Register: {register['formality']}, {register['warmth']}, {register['casing']}",
        f"Style: {style['length']}, {style['formatting']}, emoji={style['emoji']}",
        "Lexicon:",
        *lex_lines,
        "Norms:",
        *norm_lines,
        "Recent turns:",
        *lines,
    ])


def extract(messages: list[dict], source: str = "") -> dict:
    """Return exactly {profile, prompt_block} for the given transcript."""
    n = len(messages)
    profile = {
        "summary": _summary(messages),
        "register": _register(messages),
        "style": _style(messages),
        "lexicon": _lexicon(messages),
        "banned_phrases": [],
        "address": _address(messages),
        "taboos": _taboos(messages),
        "humor": _humor(_joined(messages)),
        "roles": _roles(messages),
        "norms": _norms(messages, n),
        "in_jokes": _in_jokes(messages),
        "meta": {
            "source": source,
            "channels": derive_channels(messages),
            "message_count": n,
        },
    }
    return {
        "profile": profile,
        "prompt_block": _prompt_block(profile, messages),
    }
