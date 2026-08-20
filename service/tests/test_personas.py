"""Focused unit tests for the personas engine: blueprint normalization,
evaluation gate details, marginal math, and id patterns.

These mirror the pinned literals in tests/intelligence/run.mjs.
"""

from __future__ import annotations

import re

from humalike.engine.personas import (
    ENHANCEMENT_SECTION,
    SYSTEM_PROMPT_PREAMBLE,
    build_enhanced_persona,
    compute_diversity,
    compute_marginals,
    design_blueprint,
    evaluate,
    normalize_blueprint,
    sample_personas,
)

CUSTOM_BLUEPRINT = {
    "domain": "constraint_probe",
    "order": ["age", "hours"],
    "fields": [
        {"name": "age", "kind": "numeric", "description": "age in years", "parents": [],
         "numeric": {"min": 0, "max": 120, "mean": 40, "sd": 15, "integer": True},
         "conditionals": []},
        {"name": "hours", "kind": "numeric", "description": "weekly hours", "parents": [],
         "numeric": {"min": 0, "max": 100, "mean": 20, "sd": 10, "integer": True},
         "conditionals": []},
    ],
    "constraints": [
        {"name": "age_nonnegative", "lhs": "age", "op": ">=", "rhs": "0"},
        {"name": "hours_nonnegative", "lhs": "hours", "op": ">=", "rhs": "0"},
    ],
}


def test_normalize_blueprint_fills_exact_defaults():
    normalized = normalize_blueprint(CUSTOM_BLUEPRINT)
    assert normalized == {
        "domain": "constraint_probe",
        "language": "",
        "order": ["age", "hours"],
        "fields": [
            {"name": "age", "label": "", "kind": "numeric", "description": "age in years",
             "formula": "", "parents": [], "categorical": None,
             "numeric": {"min": 0, "max": 120, "mean": 40, "sd": 15, "integer": True},
             "conditionals": [], "ordered_values": None},
            {"name": "hours", "label": "", "kind": "numeric", "description": "weekly hours",
             "formula": "", "parents": [], "categorical": None,
             "numeric": {"min": 0, "max": 100, "mean": 20, "sd": 10, "integer": True},
             "conditionals": [], "ordered_values": None},
        ],
        "constraints": CUSTOM_BLUEPRINT["constraints"],
        "style_axes": {},
        "name_origins": [],
        "rationale": "",
        "sources": [],
    }


def test_normalize_blueprint_is_idempotent_on_generated_blueprint():
    blueprint = design_blueprint("Two fictional community librarians")
    assert normalize_blueprint(blueprint) == blueprint


def test_constraint_violation_gate_details_pinned():
    persona = {"persona_id": "constraint_probe_1",
               "fields": {"age": "-3", "hours": "unknown"},
               "system_prompt": "x", "markdown": "y"}
    result = evaluate([persona], normalize_blueprint(CUSTOM_BLUEPRINT))
    assert result["passed"] is False
    assert result["gates"] == []
    assert result["diversity"] is None
    assert result["marginals"] == []
    schema, constraints = result["scorecards"][0]["gates"]
    assert (schema["name"], schema["passed"], schema["score"]) == ("schema", False, None)
    assert schema["detail"] == "hours='unknown' is not numeric"
    assert (constraints["name"], constraints["passed"]) == ("constraints", False)
    assert constraints["detail"] == "age_nonnegative: age=-3 >= 0 (0)"


def test_non_applicable_constraint_gate_detail_pinned():
    blueprint = normalize_blueprint({
        "domain": "not_applicable_probe",
        "order": ["hours"],
        "fields": [{"name": "hours", "kind": "numeric", "description": "weekly hours",
                    "parents": [],
                    "numeric": {"min": 0, "max": 100, "mean": 20, "sd": 10, "integer": True},
                    "conditionals": []}],
        "constraints": [{"name": "hours_nonnegative", "lhs": "hours", "op": ">=", "rhs": "0"}],
    })
    persona = {"persona_id": "p1", "fields": {"hours": "unknown"},
               "system_prompt": "", "markdown": ""}
    result = evaluate([persona], blueprint)
    assert result["passed"] is False
    schema, constraints = result["scorecards"][0]["gates"]
    assert schema["passed"] is False
    assert constraints["passed"] is True
    assert constraints["detail"] == "0 applicable constraint(s) passed"


def test_evaluate_without_blueprint_is_exact_empty_result():
    persona = {"persona_id": "solo_1", "fields": {"age": "31"},
               "system_prompt": "s", "markdown": "m"}
    assert evaluate([persona], None) == {
        "passed": True, "gates": [], "scorecards": [],
        "diversity": None, "marginals": [], "notes": [],
    }


def test_marginal_math():
    blueprint = {"fields": [
        {"name": "genre", "kind": "categorical",
         "categorical": {"weights": {"a": 2, "b": 1, "c": 1}}},
    ]}
    field_maps = [{"genre": "a"}, {"genre": "a"}, {"genre": "b"}, {"genre": "d"}]
    (marginal,) = compute_marginals(field_maps, blueprint)
    assert marginal["attribute"] == "genre"
    cells = {c["key"]: c for c in marginal["cells"]}
    assert set(cells) == {"a", "b", "c", "d"}
    assert cells["a"]["requested"] == 0.5 and cells["a"]["achieved"] == 0.5
    assert cells["b"]["requested"] == 0.25 and cells["b"]["achieved"] == 0.25
    assert cells["c"]["requested"] == 0.25 and cells["c"]["achieved"] == 0.0
    assert cells["d"]["requested"] == 0.0 and cells["d"]["achieved"] == 0.25
    expected_tvd = 0.5 * sum(abs(c["requested"] - c["achieved"]) for c in marginal["cells"])
    assert marginal["total_variation_distance"] == expected_tvd
    assert abs(sum(c["requested"] for c in marginal["cells"]) - 1) < 1e-9
    assert abs(sum(c["achieved"] for c in marginal["cells"]) - 1) < 1e-9


def test_generated_population_ids_shapes_and_gates():
    blueprint = design_blueprint("Two fictional community librarians with varied ages")
    personas = sample_personas(blueprint, 5, seed=1234567)
    field_names = sorted(f["name"] for f in blueprint["fields"])
    assert [p["persona_id"] for p in personas] == [f"p{i:04d}" for i in range(1, 6)]
    for persona in personas:
        assert re.fullmatch(r"p\d{4}", persona["persona_id"])
        assert sorted(persona["fields"]) == field_names
        assert all(isinstance(v, str) and v for v in persona["fields"].values())
        assert persona["markdown"].startswith("# Persona\n")
        assert persona["system_prompt"].startswith(SYSTEM_PROMPT_PREAMBLE)
        assert persona["system_prompt"] != persona["markdown"]

    diversity = compute_diversity([p["fields"] for p in personas])
    assert 0 <= diversity["mean_pairwise_similarity"] <= diversity["max_pairwise_similarity"] <= 0.9
    assert diversity["duplicate_pairs"] == 0

    # Our own generated output must clear every evaluation gate.
    result = evaluate(personas, blueprint)
    assert result["passed"] is True
    gate_names = [g["name"] for g in result["gates"]]
    assert gate_names == ["max_pairwise_similarity",
                          "marginal_tvd:favorite_genre",
                          "marginal_tvd:communication_style"]
    assert all(g["passed"] for g in result["gates"])
    assert all(g["detail"].startswith("[advisory: n<50] ")
               for g in result["gates"] if g["name"].startswith("marginal_tvd:"))
    assert result["diversity"] == diversity
    assert result["marginals"] == compute_marginals([p["fields"] for p in personas], blueprint)


def test_sampling_is_deterministic_per_seed():
    blueprint = design_blueprint("librarians")
    assert sample_personas(blueprint, 3, seed=42) == sample_personas(blueprint, 3, seed=42)
    assert sample_personas(blueprint, 3, seed=42) != sample_personas(blueprint, 3, seed=43)


def test_enhanced_persona_contract():
    seed_text = "Iris Vale is exactly 47 years old, lives in Turku, and uses marker contract-abc."
    persona = build_enhanced_persona("11111111-2222-3333-4444-555555555555", seed_text)
    assert re.fullmatch(r"enhanced-[0-9a-f]{12}", persona["persona_id"])
    assert persona["fields"] == {}
    assert persona["system_prompt"] == persona["markdown"]
    assert persona["markdown"].startswith("CHARACTER PROFILE\n")
    assert (ENHANCEMENT_SECTION + seed_text) in persona["markdown"]
    assert not any(re.match(r"^#{1,6}\s", line) for line in persona["markdown"].splitlines())
    # Distinctive facts also appear outside the verbatim quote.
    outside = persona["markdown"].replace(ENHANCEMENT_SECTION + seed_text, "")
    assert "47" in outside and "Turku" in outside and "contract-abc" in outside
    # Deterministic per job id.
    again = build_enhanced_persona("11111111-2222-3333-4444-555555555555", seed_text)
    assert persona == again
