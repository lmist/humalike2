"""Personas engine (spec/05 §Personas): deterministic blueprint design,
population sampling, enhancement rendering, and evaluation gates.

Everything is seeded from the job id, so a resource's result is stable across
polls, worker restarts, and re-runs. No model calls are made.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections import Counter
from datetime import timezone
from typing import Any

from ..db import session
from ..storage import Job, dumps, loads
from ..timefmt import ts, utcnow

SYSTEM_PROMPT_PREAMBLE = (
    "You are the person described below. Stay in character, speak in their "
    "voice, and never break character or mention being an AI."
)
ENHANCEMENT_SECTION = (
    "USER-PROVIDED AGENT INFORMATION\n"
    "Use this as high-priority context for identity, preferences, and behavior:\n"
)

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "with", "in", "on", "to",
    "who", "that", "their", "them", "some", "various", "varied", "fictional",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "different", "diverse", "several",
}

_FIRST_NAMES = (
    "Ada", "Bruno", "Carmen", "Dmitri", "Elena", "Felix", "Greta", "Hiro",
    "Ingrid", "Jonas", "Kaisa", "Luis", "Mireille", "Nadia", "Otto", "Priya",
)
_LAST_NAMES = (
    "Aalto", "Barnes", "Castillo", "Dubois", "Ekström", "Fontaine", "Grieg",
    "Hoffmann", "Ivanova", "Jansson", "Kowalski", "Lindqvist", "Moreau",
    "Nakamura", "Okafor", "Petrova",
)


def _seed(job_id: str) -> int:
    return int.from_bytes(hashlib.sha256(job_id.encode()).digest()[:8], "big")


def _field_hash(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")


def _iso(dt) -> str:
    # SQLite round-trips timezone-aware UTC datetimes as naive; restore UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return ts(dt)


# --------------------------------------------------------------------------
# Blueprint design


def _domain_from_prompt(prompt: str) -> str:
    words = ["".join(ch for ch in w.lower() if ch.isalnum() or ch == "_")
             for w in prompt.split()]
    kept = [w for w in words if w and w not in _STOPWORDS and not w.isdigit()]
    return "_".join(kept[:2]) if kept else "general_population"


def design_blueprint(prompt: str) -> dict:
    """Deterministic blueprint: sampled demographics with conditional habits,
    one derived field, named constraints, style axes, and name origins."""
    domain = _domain_from_prompt(prompt)
    fields = [
        {
            "name": "name", "label": "Full name", "kind": "text",
            "description": "The persona's full name.", "formula": "",
            "parents": [], "categorical": None, "numeric": None,
            "conditionals": [], "ordered_values": None,
        },
        {
            "name": "age", "label": "Age", "kind": "numeric",
            "description": "Age in whole years.", "formula": "",
            "parents": [], "categorical": None,
            "numeric": {"min": 22, "max": 75, "mean": 44.0, "sd": 12.0, "integer": True},
            "conditionals": [], "ordered_values": None,
        },
        {
            "name": "age_group", "label": "Age group", "kind": "derived",
            "description": "Career stage derived from age.",
            "formula": "age <= 34 ? 'early_career' : age <= 54 ? 'mid_career' : 'seasoned'",
            "parents": ["age"], "categorical": None, "numeric": None,
            "conditionals": [],
            "ordered_values": ["early_career", "mid_career", "seasoned"],
        },
        {
            "name": "weekly_reading_hours", "label": "Weekly reading hours",
            "kind": "numeric",
            "description": "Hours spent reading per week, conditioned on age group.",
            "formula": "", "parents": ["age_group"],
            "categorical": None, "numeric": None,
            "conditionals": [
                {"when": {"age_group": "early_career"}, "categorical": None,
                 "numeric": {"min": 2, "max": 12, "mean": 6.0, "sd": 2.5, "integer": True}},
                {"when": {"age_group": "mid_career"}, "categorical": None,
                 "numeric": {"min": 4, "max": 16, "mean": 9.0, "sd": 3.0, "integer": True}},
                {"when": {"age_group": "seasoned"}, "categorical": None,
                 "numeric": {"min": 6, "max": 20, "mean": 12.0, "sd": 3.5, "integer": True}},
            ],
            "ordered_values": None,
        },
        {
            "name": "favorite_genre", "label": "Favorite genre", "kind": "categorical",
            "description": "Preferred reading genre.", "formula": "",
            "parents": [],
            "categorical": {"weights": {"mystery": 2, "history": 1, "science_fiction": 1}},
            "numeric": None, "conditionals": [], "ordered_values": None,
        },
        {
            "name": "communication_style", "label": "Communication style",
            "kind": "categorical",
            "description": "How the persona tends to communicate.", "formula": "",
            "parents": [],
            "categorical": {"weights": {"warm": 2, "direct": 1, "playful": 1}},
            "numeric": None, "conditionals": [], "ordered_values": None,
        },
        {
            "name": "bio", "label": "Short bio", "kind": "text",
            "description": "A one-paragraph biography.", "formula": "",
            "parents": [], "categorical": None, "numeric": None,
            "conditionals": [], "ordered_values": None,
        },
    ]
    return {
        "domain": domain,
        "language": "en",
        "order": [f["name"] for f in fields],
        "fields": fields,
        "constraints": [
            {"name": "age_minimum", "lhs": "age", "op": ">=", "rhs": "18"},
            {"name": "weekly_reading_hours_nonnegative",
             "lhs": "weekly_reading_hours", "op": ">=", "rhs": "0"},
        ],
        "style_axes": {
            "tone": ["warm", "dry", "enthusiastic"],
            "formality": ["casual", "balanced", "formal"],
        },
        "name_origins": ["english", "nordic", "spanish", "japanese"],
        "rationale": (
            f"Deterministic blueprint for '{prompt}': demographic sampling with "
            "a derived career stage, reading habits conditioned on it, and "
            "named plausibility constraints."
        ),
        "sources": [],
    }


# --------------------------------------------------------------------------
# Population sampling


def _coprime_step(span: int, salt: int) -> int:
    # An index step coprime with the span guarantees distinct values while
    # index < span, keeping pairwise similarity low.
    if span <= 1:
        return 1
    from math import gcd
    for candidate in (7, 11, 13, 17, 19, 23, 29, 5, 3):
        step = candidate + 2 * (salt % 3)
        if gcd(step, span) == 1:
            return step
    return 1


def _sample_numeric(dist: dict, name: str, seed: int, index: int) -> str:
    lo, hi = int(dist["min"]), int(dist["max"])
    span = hi - lo + 1
    salt = _field_hash(name)
    base = (seed + salt) % span
    value = lo + (base + index * _coprime_step(span, salt)) % span
    return str(value)


def _categorical_assignments(weights: dict, count: int, seed: int, name: str) -> list[str]:
    """Largest-remainder quota assignment so achieved fractions track the
    requested weights as closely as possible for any batch size."""
    keys = list(weights.keys())
    total = float(sum(weights.values())) or 1.0
    quotas = [weights[k] * count / total for k in keys]
    counts = [int(q) for q in quotas]
    remainders = sorted(range(len(keys)), key=lambda i: (-(quotas[i] - counts[i]), i))
    for i in remainders[: count - sum(counts)]:
        counts[i] += 1
    assigned = [k for k, c in zip(keys, counts) for _ in range(c)]
    random.Random(seed ^ _field_hash(name)).shuffle(assigned)
    return assigned


def _derive(name: str, fields: dict) -> str:
    if name == "age_group":
        age = int(fields["age"])
        if age <= 34:
            return "early_career"
        if age <= 54:
            return "mid_career"
        return "seasoned"
    return "n/a"


def sample_personas(blueprint: dict, count: int, seed: int) -> list[dict]:
    by_name = {f["name"]: f for f in blueprint["fields"]}
    assignments = {
        f["name"]: _categorical_assignments(f["categorical"]["weights"], count, seed, f["name"])
        for f in blueprint["fields"]
        if f["kind"] == "categorical" and f["categorical"]
    }
    used_names: set[str] = set()
    personas = []
    for index in range(count):
        values: dict[str, str] = {}
        for field_name in blueprint["order"]:
            field = by_name[field_name]
            if field_name == "name":
                first = _FIRST_NAMES[(seed + index) % len(_FIRST_NAMES)]
                last = _LAST_NAMES[(seed // 16 + index * 3) % len(_LAST_NAMES)]
                full = f"{first} {last}"
                if full in used_names:
                    full = f"{full} {index + 1}"
                used_names.add(full)
                values["name"] = full
            elif field["kind"] == "numeric":
                dist = field["numeric"]
                if dist is None:
                    for conditional in field["conditionals"]:
                        if all(values.get(k) == v for k, v in conditional["when"].items()):
                            dist = conditional["numeric"]
                            break
                values[field_name] = _sample_numeric(dist, field_name, seed, index)
            elif field["kind"] == "categorical":
                values[field_name] = assignments[field_name][index]
            elif field["kind"] == "derived":
                values[field_name] = _derive(field_name, values)
            elif field_name == "bio":
                values["bio"] = (
                    f"{values['name']} is a {values['age']}-year-old "
                    f"{blueprint['domain'].replace('_', ' ')} persona who favors "
                    f"{values['favorite_genre'].replace('_', ' ')} and reads about "
                    f"{values['weekly_reading_hours']} hours a week in a "
                    f"{values['communication_style']} voice."
                )
            else:
                values[field_name] = "unspecified"
        lines = "\n".join(
            f"- {by_name[n]['label']}: {values[n]}" for n in blueprint["order"]
        )
        personas.append({
            "persona_id": f"p{index + 1:04d}",
            "fields": values,
            "system_prompt": f"{SYSTEM_PROMPT_PREAMBLE}\n\nProfile:\n{lines}",
            "markdown": f"# Persona\n\n{lines}",
        })
    return personas


# --------------------------------------------------------------------------
# Diversity and marginal math (shared by population and evaluation)


def _similarity(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    equal = sum(1 for k in keys if k in a and k in b and a[k] == b[k])
    return equal / len(keys)


def compute_diversity(field_maps: list[dict]) -> dict:
    sims = [
        _similarity(field_maps[i], field_maps[j])
        for i in range(len(field_maps))
        for j in range(i + 1, len(field_maps))
    ]
    if not sims:
        return {"max_pairwise_similarity": 0.0, "mean_pairwise_similarity": 0.0,
                "duplicate_pairs": 0}
    return {
        "max_pairwise_similarity": max(sims),
        "mean_pairwise_similarity": sum(sims) / len(sims),
        "duplicate_pairs": sum(1 for s in sims if s >= 1.0),
    }


def compute_marginals(field_maps: list[dict], blueprint: dict) -> list[dict]:
    n = len(field_maps)
    marginals = []
    for field in blueprint.get("fields") or []:
        if field.get("kind") != "categorical":
            continue
        categorical = field.get("categorical")
        weights = categorical.get("weights") if isinstance(categorical, dict) else None
        if not isinstance(weights, dict) or not weights:
            continue
        total = float(sum(weights.values())) or 1.0
        observed = Counter(
            m[field["name"]] for m in field_maps if field["name"] in m
        )
        keys = list(weights) + sorted(k for k in observed if k not in weights)
        cells = [
            {"key": key,
             "requested": weights.get(key, 0) / total,
             "achieved": (observed.get(key, 0) / n) if n else 0.0}
            for key in keys
        ]
        tvd = 0.5 * sum(abs(c["requested"] - c["achieved"]) for c in cells)
        marginals.append({
            "attribute": field["name"],
            "cells": cells,
            "total_variation_distance": tvd,
        })
    return marginals


# --------------------------------------------------------------------------
# Enhancement


def _distinctive_tokens(source: str, limit: int = 10) -> list[str]:
    tokens = []
    for raw in source.split():
        token = raw.strip(".,;:!?()[]\"'")
        if not token:
            continue
        if any(ch.isdigit() for ch in token) or token[0].isupper() or "-" in token:
            if token not in tokens:
                tokens.append(token)
    return tokens[:limit]


def build_enhanced_persona(job_id: str, source: str) -> dict:
    hex12 = hashlib.sha256(job_id.encode()).hexdigest()[:12]
    anchors = ", ".join(_distinctive_tokens(source)) or "the details provided"
    text = (
        "CHARACTER PROFILE\n"
        f"Profile reference {hex12}.\n"
        "\n"
        "IDENTITY\n"
        "This character is fully defined by the user-provided information "
        "quoted below; every detail in it is canon and must stay consistent.\n"
        f"Anchor details to keep consistent: {anchors}.\n"
        "\n"
        f"{ENHANCEMENT_SECTION}"
        f"{source}\n"
        "\n"
        "BEHAVIOR\n"
        "Speak in the first person, stay in character at all times, and keep "
        "continuity with every identity detail above.\n"
        f"Weave these anchors naturally into conversation: {anchors}.\n"
    )
    return {
        "persona_id": f"enhanced-{hex12}",
        "fields": {},
        "system_prompt": text,
        "markdown": text,
    }


# --------------------------------------------------------------------------
# Blueprint normalization (validation echo) and evaluation


def normalize_blueprint(blueprint: dict) -> dict:
    def default(value, fallback):
        return fallback if value is None else value

    return {
        "domain": default(blueprint.get("domain"), ""),
        "language": default(blueprint.get("language"), ""),
        "order": default(blueprint.get("order"), []),
        "fields": [
            {
                "name": default(field.get("name"), ""),
                "label": default(field.get("label"), ""),
                "kind": default(field.get("kind"), ""),
                "description": default(field.get("description"), ""),
                "formula": default(field.get("formula"), ""),
                "parents": default(field.get("parents"), []),
                "categorical": field.get("categorical"),
                "numeric": field.get("numeric"),
                "conditionals": default(field.get("conditionals"), []),
                "ordered_values": field.get("ordered_values"),
            }
            for field in default(blueprint.get("fields"), [])
        ],
        "constraints": default(blueprint.get("constraints"), []),
        "style_axes": default(blueprint.get("style_axes"), {}),
        "name_origins": default(blueprint.get("name_origins"), []),
        "rationale": default(blueprint.get("rationale"), ""),
        "sources": default(blueprint.get("sources"), []),
    }


def _parse_number(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def evaluate(personas: list[dict], blueprint: dict | None) -> dict:
    if blueprint is None:
        return {"passed": True, "gates": [], "scorecards": [],
                "diversity": None, "marginals": [], "notes": []}

    bp_fields = blueprint.get("fields") or []
    constraints = blueprint.get("constraints") or []

    # Constraint evaluation across the batch: a constraint is applicable to a
    # persona only when its lhs field carries a schema-valid numeric value.
    evaluations: list[list[tuple[str, dict, Any]]] = []
    batch_pass_counts = {c["name"]: 0 for c in constraints}
    for persona in personas:
        rows = []
        for constraint in constraints:
            raw = persona["fields"].get(constraint["lhs"])
            lhs = _parse_number(raw)
            rhs = _parse_number(constraint.get("rhs"))
            op = _OPS.get(constraint.get("op"))
            if lhs is None or rhs is None or op is None:
                rows.append(("not_applicable", constraint, raw))
            elif op(lhs, rhs):
                rows.append(("pass", constraint, raw))
                batch_pass_counts[constraint["name"]] += 1
            else:
                rows.append(("fail", constraint, raw))
        evaluations.append(rows)

    scorecards = []
    for persona, rows in zip(personas, evaluations):
        failing = None
        valid = 0
        for field in bp_fields:
            value = persona["fields"].get(field.get("name"))
            if field.get("kind") == "numeric":
                if _parse_number(value) is None:
                    failing = (field.get("name"), "" if value is None else value)
                    break
                valid += 1
            elif value is not None:
                valid += 1
        if failing is not None:
            schema_gate = {"name": "schema", "passed": False, "score": None,
                           "detail": f"{failing[0]}='{failing[1]}' is not numeric"}
        else:
            schema_gate = {"name": "schema", "passed": True, "score": None,
                           "detail": f"{valid} field(s) valid"}

        first_fail = next(((c, raw) for status, c, raw in rows if status == "fail"), None)
        if first_fail is not None:
            constraint, raw = first_fail
            constraints_gate = {
                "name": "constraints", "passed": False, "score": None,
                "detail": (
                    f"{constraint['name']}: {constraint['lhs']}={raw} "
                    f"{constraint['op']} {constraint['rhs']} "
                    f"({batch_pass_counts[constraint['name']]})"
                ),
            }
        else:
            applicable = sum(1 for status, _, _ in rows if status == "pass")
            constraints_gate = {
                "name": "constraints", "passed": True, "score": None,
                "detail": f"{applicable} applicable constraint(s) passed",
            }
        scorecards.append({
            "persona_id": persona["persona_id"],
            "gates": [schema_gate, constraints_gate],
            "soft_scores": {},
        })

    if len(personas) >= 2:
        field_maps = [p["fields"] for p in personas]
        diversity = compute_diversity(field_maps)
        marginals = compute_marginals(field_maps, blueprint)
        max_sim = diversity["max_pairwise_similarity"]
        sim_passed = max_sim <= 0.9
        gates = [{
            "name": "max_pairwise_similarity",
            "passed": sim_passed,
            "score": max_sim,
            "detail": f"max pairwise similarity {max_sim:.3f} "
                      + ("<= 0.9" if sim_passed else "> 0.9"),
        }]
        advisory = "[advisory: n<50] " if len(personas) < 50 else ""
        for marginal in marginals:
            tvd = marginal["total_variation_distance"]
            tvd_passed = tvd <= 0.5
            gates.append({
                "name": f"marginal_tvd:{marginal['attribute']}",
                "passed": tvd_passed,
                "score": tvd,
                "detail": advisory + f"total variation distance {tvd:.3f} "
                          + ("<= 0.5" if tvd_passed else "> 0.5"),
            })
    else:
        diversity = None
        marginals = []
        gates = []

    passed = (
        all(g["passed"] for g in gates)
        and all(g["passed"] for card in scorecards for g in card["gates"])
    )
    return {"passed": passed, "gates": gates, "scorecards": scorecards,
            "diversity": diversity, "marginals": marginals, "notes": []}


# --------------------------------------------------------------------------
# Job handlers and resource projections


def _load_job(job_id: str) -> Job | None:
    with session() as s:
        return s.get(Job, job_id)


def _update_job(job_id: str, **changes) -> None:
    with session() as s:
        job = s.get(Job, job_id)
        if job is None or job.status in ("succeeded", "failed"):
            return
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = utcnow()


async def run_population(job_id: str) -> None:
    job = _load_job(job_id)
    if job is None:
        return
    request = loads(job.request_json)
    count = request["count"]
    seed = _seed(job_id)

    _update_job(job_id, progress_json=dumps(
        {"phase": "designing", "produced": 0, "total": count}))
    await asyncio.sleep(0.3)
    blueprint = design_blueprint(request["prompt"])

    _update_job(job_id, progress_json=dumps(
        {"phase": "generating", "produced": 0, "total": count}))
    await asyncio.sleep(0.3)
    personas = sample_personas(blueprint, count, seed)
    field_maps = [p["fields"] for p in personas]
    result = {
        "personas": personas,
        "blueprint": blueprint,
        "diversity": compute_diversity(field_maps),
        "marginals": compute_marginals(field_maps, blueprint),
    }
    _update_job(
        job_id,
        status="succeeded",
        progress_json=dumps({"phase": "complete", "produced": count, "total": count}),
        result_json=dumps(result),
    )


async def run_enhancement(job_id: str) -> None:
    job = _load_job(job_id)
    if job is None:
        return
    request = loads(job.request_json)
    _update_job(job_id, status="running")
    await asyncio.sleep(0.45)
    persona = build_enhanced_persona(job_id, request["persona"])
    _update_job(job_id, status="succeeded", result_json=dumps(persona))


async def run_evaluation(job_id: str) -> None:
    job = _load_job(job_id)
    if job is None:
        return
    request = loads(job.request_json)
    _update_job(job_id, progress_json=dumps({"phase": "evaluating"}))
    await asyncio.sleep(0.2)
    result = evaluate(request["personas"], request["blueprint"])
    _update_job(
        job_id,
        status="succeeded",
        progress_json=dumps({"phase": "complete"}),
        result_json=dumps(result),
    )


def resource_view(job: Job) -> dict:
    request = loads(job.request_json)
    common = {
        "id": job.id,
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
        "status": job.status,
        "error": loads(job.error_json),
    }
    if job.kind == "population":
        return {
            **common,
            "progress": loads(job.progress_json),
            "prompt": request["prompt"],
            "count": request["count"],
            "grounding": request["grounding"],
            "result": loads(job.result_json),
        }
    if job.kind == "enhancement":
        return {
            **common,
            "source": request["persona"],
            "grounding": request["grounding"],
            "persona": loads(job.result_json),
        }
    return {
        **common,
        "progress": loads(job.progress_json),
        "personas": request["personas"],
        "blueprint": request["blueprint"],
        "result": loads(job.result_json),
    }
