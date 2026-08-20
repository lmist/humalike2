#!/usr/bin/env python3
"""LoSoNA-style naive vs norm-informed candidate-model evaluation (hum-fbwc).

spec/05 §Social Learning and norm adaptation: explicit norm prompting
improves some models and regresses others, so inferred local norms are
confidence-weighted evidence. Per spec/07 phase 8, each release candidate
model runs naive and norm-informed evaluations with three samples, paired
recovery/regression accounting, consistency, and scenario-level confidence
intervals.

The candidate under test is the recreation's configured model provider —
the deterministic substitute by default (ADR hum-vdio); real providers are
configuration and rerun this harness unchanged.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "service"))

from humalike.engine import router  # noqa: E402

SAMPLES = 3

# Each scenario: an accepted batch, a norm-informed system prompt carrying the
# learned local norm, and the socially expected decision under that norm.
SCENARIOS = [
    {
        "name": "direct_address",
        "messages": [{"sender": "Human", "content": "Live Test Agent, are you available?"}],
        "norm_prompt": "You are Live Test Agent. Local norm: always answer direct questions promptly.",
        "expected": "speak",
    },
    {
        "name": "third_party_vocative",
        "messages": [{"sender": "Alice", "content": "Bob, are you still joining lunch at noon?"}],
        "norm_prompt": "You are Live Test Agent. Local norm: never interject in exchanges addressed to other named humans.",
        "expected": "stay_silent",
    },
    {
        "name": "acknowledgment",
        "messages": [{"sender": "Dave", "content": "ok thanks"}],
        "norm_prompt": "You are Live Test Agent. Local norm: acknowledgments end a turn; stay silent.",
        "expected": "stay_silent",
    },
    {
        "name": "at_mention_other",
        "messages": [{"sender": "Carol", "content": "@someone-else can you answer the deployment question?"}],
        "norm_prompt": "You are Live Test Agent. Local norm: @-mentions route the turn to the named person only.",
        "expected": "stay_silent",
    },
    {
        "name": "open_question",
        "messages": [{"sender": "Erin", "content": "Does anyone know when the release ships?"}],
        "norm_prompt": "You are Live Test Agent. Local norm: open questions to the room may be answered by anyone.",
        "expected": "speak",
    },
    {
        "name": "private_aside",
        "messages": [{"sender": "Eve", "content": "Frank, this is between us; please reply when you see it."}],
        "norm_prompt": "You are Live Test Agent. Local norm: private asides between named humans are off-limits.",
        "expected": "stay_silent",
    },
]


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    phat = successes / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def run_condition(scenario: dict, informed: bool) -> list[str]:
    prompt = scenario["norm_prompt"] if informed else None
    return [router.decide(scenario["messages"], prompt).decision
            for _ in range(SAMPLES)]


def main() -> int:
    rows = []
    recovered = regressed = 0
    for scenario in SCENARIOS:
        naive = run_condition(scenario, informed=False)
        informed = run_condition(scenario, informed=True)
        expected = scenario["expected"]
        naive_ok = sum(d == expected for d in naive)
        informed_ok = sum(d == expected for d in informed)
        # Paired accounting per spec/05: recovery = naive wrong, informed
        # right; regression = naive right, informed wrong.
        pair_recovered = sum(1 for a, b in zip(naive, informed)
                             if a != expected and b == expected)
        pair_regressed = sum(1 for a, b in zip(naive, informed)
                             if a == expected and b != expected)
        recovered += pair_recovered
        regressed += pair_regressed
        rows.append({
            "scenario": scenario["name"],
            "expected": expected,
            "naive_decisions": naive,
            "informed_decisions": informed,
            "naive_accuracy": naive_ok / SAMPLES,
            "informed_accuracy": informed_ok / SAMPLES,
            "naive_ci95": wilson_interval(naive_ok, SAMPLES),
            "informed_ci95": wilson_interval(informed_ok, SAMPLES),
            "consistency_naive": len(set(naive)) == 1,
            "consistency_informed": len(set(informed)) == 1,
            "recovered": pair_recovered,
            "regressed": pair_regressed,
        })

    naive_mean = statistics.mean(r["naive_accuracy"] for r in rows)
    informed_mean = statistics.mean(r["informed_accuracy"] for r in rows)
    report = {
        "candidate_model": "deterministic-substitute (det-1; ADR hum-vdio)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "samples_per_condition": SAMPLES,
        "scenarios": rows,
        "aggregate": {
            "naive_accuracy": naive_mean,
            "norm_informed_accuracy": informed_mean,
            "paired_recoveries": recovered,
            "paired_regressions": regressed,
            "verdict": (
                "norm-informed prompting improves this candidate"
                if informed_mean > naive_mean and regressed == 0
                else "norm-informed prompting regresses this candidate; treat norms as advisory"
                if informed_mean < naive_mean
                else "norm-informed prompting is neutral for this candidate"
            ),
        },
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
