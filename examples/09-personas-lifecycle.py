#!/usr/bin/env python3
"""Phase 7 — personas: generate, enhance, and validate through the async repositories.

Every persona action returns ``{id, status:"pending"}`` and the work is read
back from an owner-scoped repository whose ``result``/``error`` stay ``None``
until terminal. This example walks all three kinds and checks the invariants
that do not depend on generated prose: persona id numbering, the required
``system_prompt`` preamble, ``progress`` phase vocabulary, the enhanced
persona's *empty* ``fields`` (tested on purpose — do not "improve" it), and
the two scorecard gates named ``schema`` and ``constraints``.

Population runs took about 52 s and enhancement about 37 s live, so this is
the slowest example by far.

    HUMALIKE_API_URL=http://127.0.0.1:8191 HUMALIKE_API_KEY=ak_... \\
      python3 examples/09-personas-lifecycle.py
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "clients", "python"))

from humalike_client import HumalikeClient  # noqa: E402

SYSTEM_PROMPT_PREAMBLE = (
    "You are the person described below. Stay in character, speak in their "
    "voice, and never break character or mention being an AI."
)

hum = HumalikeClient()
count = int(os.environ.get("EXAMPLE_PERSONA_COUNT", "3"))

# -- generate --------------------------------------------------------------
accepted = hum.generate_personas(
    prompt="Independent bookshop owners in coastal Portugal", count=count, grounding="off")
print(f"generate      {accepted}")
assert accepted["status"] == "pending", "generate returns exactly {id, status:'pending'}"

population = hum.wait_for_job(hum.population, accepted["id"], interval=2.0)
print(f"population    status={population['status']} progress={population['progress']}")
assert population["id"] == accepted["id"], "the resource id equals the action id"
assert population["prompt"] and population["count"] == count, "request fields are echoed"
if population["status"] != "succeeded":
    raise SystemExit(f"population failed: {population['error']!r}")

result = population["result"]
personas = result["personas"]
assert len(personas) == count, "personas.length must equal count"
assert [p["persona_id"] for p in personas] == [f"p{i:04d}" for i in range(1, count + 1)], \
    "persona ids are p0001, p0002, …"
blueprint_fields = {f["name"] for f in result["blueprint"]["fields"]}
for persona in personas:
    assert set(persona["fields"]) == blueprint_fields, \
        "persona field keys equal all blueprint field names"
    assert persona["markdown"].startswith("# Persona"), "markdown starts with '# Persona'"
    assert persona["system_prompt"].startswith(SYSTEM_PROMPT_PREAMBLE), \
        "system_prompt starts with the fixed preamble"
    assert persona["system_prompt"] != persona["markdown"]
print(f"personas      {len(personas)} generated, {len(blueprint_fields)} blueprint fields")
print(f"diversity     max={result['diversity']['max_pairwise_similarity']} "
      f"mean={result['diversity']['mean_pairwise_similarity']} "
      f"duplicate_pairs={result['diversity']['duplicate_pairs']}")
for marginal in result["marginals"]:
    tvd = 0.5 * sum(abs(c["requested"] - c["achieved"]) for c in marginal["cells"])
    assert abs(tvd - marginal["total_variation_distance"]) < 1e-6, \
        "total_variation_distance is ½·Σ|requested−achieved|"
    print(f"  marginal    {marginal['attribute']} tvd={marginal['total_variation_distance']:.4f}")

# -- enhance ---------------------------------------------------------------
seed = ("Marta Ferreira, 52, runs a second-hand bookshop in Nazare. "
        "Collects 1970s Portuguese sci-fi. Refuses to stock celebrity memoirs.")
accepted = hum.enhance_persona(seed, grounding="off")
enhancement = hum.wait_for_job(hum.enhancement, accepted["id"], interval=2.0)
print(f"enhancement   status={enhancement['status']} grounding={enhancement['grounding']}")
if enhancement["status"] != "succeeded":
    raise SystemExit(f"enhancement failed: {enhancement['error']!r}")

enhanced = enhancement["persona"]
assert enhancement["source"] == seed, "source echoes the request"
assert enhanced["fields"] == {}, "an enhanced persona has empty fields by design"
assert enhanced["system_prompt"] == enhanced["markdown"], \
    "system_prompt and markdown are identical for an enhancement"
assert enhanced["markdown"].startswith("CHARACTER PROFILE"), "no '#' headings on an enhancement"
assert seed in enhanced["markdown"], "the seed is embedded verbatim"
assert enhanced["persona_id"].startswith("enhanced-") and len(enhanced["persona_id"]) == len("enhanced-") + 12
print(f"enhanced      persona_id={enhanced['persona_id']} fields={enhanced['fields']} "
      f"chars={len(enhanced['markdown'])}")

# -- validate --------------------------------------------------------------
accepted = hum.validate_personas(personas, result["blueprint"])
evaluation = hum.wait_for_job(hum.evaluation, accepted["id"], interval=1.0)
print(f"evaluation    status={evaluation['status']} progress={evaluation['progress']}")
if evaluation["status"] != "succeeded":
    raise SystemExit(f"evaluation failed: {evaluation['error']!r}")

verdict = evaluation["result"]
print(f"passed        {verdict['passed']}")
for gate in verdict["gates"]:
    print(f"  gate        {gate['name']} passed={gate['passed']} score={gate['score']} :: {gate['detail']}")
for scorecard in verdict["scorecards"][:3]:
    names = [g["name"] for g in scorecard["gates"]]
    assert names == ["schema", "constraints"], f"scorecard gates are schema then constraints, got {names}"
    print(f"  {scorecard['persona_id']}     {names} soft_scores={scorecard['soft_scores']}")
assert verdict["passed"] == all(g["passed"] for g in verdict["gates"]), \
    "passed is true exactly when every gate passed"

# A single persona with no blueprint: batch gates disappear entirely.
accepted = hum.validate_personas([{"persona_id": "solo"}])
solo = hum.wait_for_job(hum.evaluation, accepted["id"], interval=1.0)
print(f"no blueprint  {solo['result']}")
assert solo["result"] == {"passed": True, "gates": [], "scorecards": [],
                          "diversity": None, "marginals": [], "notes": []}, \
    "validating without a blueprint returns the documented empty verdict"

# A valid but unknown id is a 200 with JSON null, not a 404.
assert hum.population(str(uuid.uuid4())) is None, "a missing valid UUID returns null"
print("missing uuid  null")

print("09-personas-lifecycle OK")
