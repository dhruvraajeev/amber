"""Same design, config and seed → the same result, byte for byte (plan §8.2).

Reproducibility is what makes a comparison between two designs mean anything: if the numbers moved,
it has to be because the design changed, not because the dice fell differently. Only `engine.wallMs`
and `engine.eventsPerSec` may differ — they measure the host machine, not the simulation.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from test_run import TEMPLATES, design, template

from amber.contracts import Design, RunConfig
from amber.sim.run import simulate

MACHINE_FIELDS = ("wallMs", "eventsPerSec")


def result_json(name="rag-chatbot-hosted", duration_s=30, seed=7) -> str:
    """One run as JSON, with the two fields that measure the host machine removed."""
    result = simulate(design(name), RunConfig(duration_s=duration_s, seed=seed))
    body = json.loads(result.model_dump_json())
    for field in MACHINE_FIELDS:
        del body["engine"][field]
    return json.dumps(body, sort_keys=True)


@pytest.mark.parametrize("name", ["rag-chatbot-hosted", "agent-self-hosted"])
def test_the_same_inputs_give_byte_identical_json(name):
    assert result_json(name) == result_json(name)


def test_only_the_host_machine_fields_are_allowed_to_move():
    first = simulate(design("rag-chatbot-hosted"), RunConfig(duration_s=30, seed=7)).engine
    second = simulate(design("rag-chatbot-hosted"), RunConfig(duration_s=30, seed=7)).engine

    assert (first.events, first.simulated_requests) == (second.events, second.simulated_requests)
    assert first.wall_ms > 0 and second.wall_ms > 0  # both real measurements, not a copied constant


def test_a_different_seed_gives_a_different_run():
    assert result_json(seed=7) != result_json(seed=8)


def test_a_changed_design_gives_a_different_run():
    """A design that only differs in a parameter must not somehow produce the same numbers."""
    raw = template("rag-chatbot-hosted")
    api = next(n for n in raw["nodes"] if n["id"] == "n_api")
    api["params"]["replicas"] += 1
    config = RunConfig(duration_s=30, seed=7)

    changed = simulate(Design.model_validate(raw), config)
    assert changed.design_hash != simulate(design("rag-chatbot-hosted"), config).design_hash
    assert changed.model_dump_json() != result_json()


def test_the_result_is_the_same_in_another_process_with_another_hash_seed():
    """Python salts `hash()` per process. Seeding with it would pass every test above and still make
    two machines disagree, so the same run is compared across two processes salted differently."""
    script = textwrap.dedent(f"""
        import json
        from amber.contracts import Design, RunConfig
        from amber.sim.run import simulate
        design = Design.model_validate(json.load(open({str(TEMPLATES / "rag-chatbot-hosted.json")!r})))
        result = simulate(design, RunConfig(duration_s=30, seed=7))
        body = json.loads(result.model_dump_json())
        for field in {MACHINE_FIELDS!r}:
            del body["engine"][field]
        print(json.dumps(body, sort_keys=True))
    """)
    runs = [_run_with_hash_seed(script, hash_seed) for hash_seed in ("0", "1")]
    assert runs[0] == runs[1] == result_json()


def _run_with_hash_seed(script: str, hash_seed: str) -> str:
    """Run `script` in a fresh interpreter whose `hash()` is salted with `hash_seed`."""
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],  # backend/, where the amber package lives
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": hash_seed, "PATH": "/usr/bin:/bin"},
    )
    return done.stdout.strip()
