"""Closed static contract pins and their drift guards (ADR-033).

Extraction may not import ``evaluation.contracts``, so every released
evaluation-shaped artifact it emits carries a **closed static pin**. A pin that
is never re-derived is a copied constant, so these tests recompute each one
from the real released model. If a released model changes, the pin fails here
loudly rather than minting a wrong ``contract_hash`` in a published artifact.
"""

from __future__ import annotations

import pytest

from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.envelopes import (
    PredictionArtifactManifest,
    PredictionEnvelope,
)
from dynamic_ai_products.evaluation.parent_observation_snapshot import (
    ParentObservationSnapshot,
)
from dynamic_ai_products.evaluation.source_snapshot import SourcePassageSnapshotManifest
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.parent_snapshots import PARENT_SNAPSHOT_CONTRACT
from dynamic_ai_products.extraction.prediction_manifest import (
    PREDICTION_MANIFEST_CONTRACT,
)
from dynamic_ai_products.extraction.raw_artifacts import (
    PREDICTION_ENVELOPE_CONTRACT,
    require_pin,
)
from dynamic_ai_products.extraction.source_snapshot_bridge import (
    SOURCE_SNAPSHOT_MANIFEST_CONTRACT,
)

PINS = [
    (PARENT_SNAPSHOT_CONTRACT, ParentObservationSnapshot),
    (PREDICTION_ENVELOPE_CONTRACT, PredictionEnvelope),
    (PREDICTION_MANIFEST_CONTRACT, PredictionArtifactManifest),
    (SOURCE_SNAPSHOT_MANIFEST_CONTRACT, SourcePassageSnapshotManifest),
]


@pytest.mark.parametrize("pin,model", PINS, ids=[p["contract_id"] for p, _ in PINS])
def test_static_pin_re_derives_from_the_released_model(pin, model):
    recomputed = model_contract_hash(model, pin["contract_id"], pin["contract_version"])
    assert pin["contract_hash"] == recomputed, (
        f"{pin['contract_id']} drifted: the released model changed and the closed "
        "pin must be rebaselined through a decision-log entry."
    )


@pytest.mark.parametrize("pin,_model", PINS, ids=[p["contract_id"] for p, _ in PINS])
def test_every_pin_carries_exactly_id_version_and_hash(pin, _model):
    assert sorted(pin) == ["contract_hash", "contract_id", "contract_version"]
    assert pin["contract_version"] == "0.1.0"
    assert len(pin["contract_hash"]) == 64
    assert set(pin["contract_hash"]) <= set("0123456789abcdef")


def test_require_pin_returns_a_copy_not_the_shared_constant():
    returned = require_pin(
        PARENT_SNAPSHOT_CONTRACT,
        contract_id="parent_observation_snapshot",
        contract_version="0.1.0",
    )
    assert returned == PARENT_SNAPSHOT_CONTRACT
    returned["contract_id"] = "mutated"
    assert PARENT_SNAPSHOT_CONTRACT["contract_id"] == "parent_observation_snapshot"


def test_require_pin_rejects_a_correct_hash_under_the_wrong_identity():
    """Checking only the digest would let a pin carry the wrong id or version."""
    with pytest.raises(ExtractionError) as excinfo:
        require_pin(
            PARENT_SNAPSHOT_CONTRACT,
            contract_id="prediction_envelope",
            contract_version="0.1.0",
        )
    assert excinfo.value.reason_code == "contract_pin_invalid"

    with pytest.raises(ExtractionError) as excinfo:
        require_pin(
            PARENT_SNAPSHOT_CONTRACT,
            contract_id="parent_observation_snapshot",
            contract_version="0.2.0",
        )
    assert excinfo.value.reason_code == "contract_pin_invalid"


@pytest.mark.parametrize(
    "pin",
    [
        None,
        "not-a-mapping",
        {"contract_id": "parent_observation_snapshot", "contract_version": "0.1.0"},
        {
            "contract_id": "parent_observation_snapshot",
            "contract_version": "0.1.0",
            "contract_hash": "0" * 64,
            "extra": "x",
        },
        {
            "contract_id": "parent_observation_snapshot",
            "contract_version": "0.1.0",
            "contract_hash": "NOTHEX" + "0" * 58,
        },
        {
            "contract_id": "parent_observation_snapshot",
            "contract_version": "0.1.0",
            "contract_hash": ("A" * 64),
        },
    ],
)
def test_require_pin_fails_closed_on_a_malformed_pin(pin):
    with pytest.raises(ExtractionError) as excinfo:
        require_pin(
            pin, contract_id="parent_observation_snapshot", contract_version="0.1.0"
        )
    assert excinfo.value.reason_code == "contract_pin_invalid"


def test_pins_are_distinct_across_contracts():
    hashes = {pin["contract_hash"] for pin, _ in PINS}
    assert len(hashes) == len(PINS)
