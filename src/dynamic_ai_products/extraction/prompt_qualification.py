"""SPEC-024 prompt qualification, bound to the two-operation route (ADR-044).

Three rings already gate a live call: adapter qualification, adapter enablement,
live-call authorization. The enablement ring has always been *required* to carry
``prompt_qualification_reference`` and ``prompt_qualification_sha256`` — SPEC-027
places the SPEC-024 reference there rather than on the authorization — but until
now nothing loaded the artifact those two fields name. The chain walk only
checked their *shape*: a non-blank string and sixty-four hex characters. A run
could therefore execute a frozen prompt under an enablement that pinned a file
which did not exist, and no edit to that prompt could break anything, because the
prompt's own digest and the governance chain were two disconnected hash trees.

This module joins them. The record is hydrated from the governance root like any
other ring, and then every identity it declares is checked against the thing the
run is actually about to do: the resolved prompt's exact bytes, the stage-output
schema this run validates against, the client contract the adapter qualification
already accepted, and the routing contract the enablement declares.

**Two roots, deliberately.** The governance records are JSON and live under the
injected ``governance_artifact_root``. The two documents this record cites — the
SPEC-024 qualification policy and the tracked change request — are Markdown and
live in the repository tree, so they are read against the already-injected
``repo_root`` through :func:`hydrate_pinned_bytes`. A repository-relative
reference is never resolved inside the governance root, and the reference
patterns make that unrepresentable rather than merely discouraged.

**Only the bootstrap basis executes.** ``evaluated_comparison`` records cite
evaluation runs that resolve against a third root which nothing injects or
hash-verifies yet. Accepting one would let unverified references authorize a
live call, so that basis is refused outright — before the property set is even
selected — rather than admitted on the strength of being schema-valid. The
successor increment that introduces the evaluation-artifact root introduces the
second property set with it.

No schema file executes on this path (ADR-032). Every const, enum, pattern, and
conditional in ``prompt_qualification_record.schema.json`` is re-enforced here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import ExtractionError
from .input_packet import hydrate_pinned_bytes

# Private helpers are imported rather than reimplemented. ``manifests`` owns the
# credential scan, the exact-property discipline, and the aware-instant parser
# for every other governance record; a local copy would be a second set of rules
# free to drift from the one the three released rings are held to.
from .manifests import (
    STAGE_OUTPUT_CONTRACT_ID,
    _require_aware_instant,
    _require_exact_properties,
)

# The prompt registry owns the set of versions it has published; this module
# recognises them rather than keeping a second copy that could fall behind.
from .prompts import KNOWN_PROMPT_REGISTRY_VERSIONS

__all__ = [
    "BASIS_UNSUPPORTED",
    "BOOTSTRAP_BASIS",
    "BOOTSTRAP_LIFECYCLE_STATE",
    "BOOTSTRAP_ROLLOUT_STATE",
    "BOOTSTRAP_SCOPE",
    "BOOTSTRAP_STATUS",
    "DECLARED_NON_CLAIMS",
    "EVALUATED_BASIS",
    "GOVERNING_SPEC_REFERENCE",
    "KNOWN_LIMITATION_CODES",
    "PROMPT_QUALIFICATION_CONTRACT",
    "PROMPT_QUALIFICATION_INVALID",
    "PROMPT_QUALIFICATION_MISMATCH",
    "PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP",
    "PROMPT_QUALIFICATION_SCHEMA_VERSION",
    "REFERENCE_UNRESOLVABLE",
    "validate_prompt_qualification",
]

PROMPT_QUALIFICATION_CONTRACT = "prompt_qualification_record@0.1.0"
PROMPT_QUALIFICATION_SCHEMA_VERSION = "0.1.0"

BOOTSTRAP_BASIS = "bootstrap_pre_evaluation"
EVALUATED_BASIS = "evaluated_comparison"

# The exact iff the bootstrap basis carries. A record on this basis rests on no
# completed evaluation, so it may only ever reach the rollout state that performs
# a development-scope live call; pilot and release are unreachable through it.
BOOTSTRAP_SCOPE = "qualified_for_development"
BOOTSTRAP_STATUS = "bootstrap_authorized_live_dev"
BOOTSTRAP_LIFECYCLE_STATE = "candidate"
BOOTSTRAP_ROLLOUT_STATE = "live_dev"

# Ordered and exact. A set or an unordered membership test would have admitted
# any permutation, and a permuted tuple is a different statement.
DECLARED_NON_CLAIMS: tuple[str, ...] = (
    "not_an_evaluation_verdict",
    "not_an_acceptance_decision",
    "not_a_release_qualification",
    "not_a_complete_universe_finding",
)

# The qualification-registry policy, which is SPEC-024 whatever stage the prompt
# serves. A stage spec is stage context and belongs to the change request; naming
# one here would mislabel stage context as qualification policy.
GOVERNING_SPEC_REFERENCE = "specs/SPEC-024-run-versioning-and-comparison.md"

KNOWN_LIMITATION_CODES: tuple[str, ...] = (
    "single_pass_recall_only_not_consolidated",
    "sec_only_partial_corpus",
    "single_firm_single_observation_year",
    "no_completed_evaluation_run",
    "no_baseline_comparison",
)

PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP: frozenset[str] = frozenset(
    {
        "change_request_reference",
        "change_request_sha256",
        "code_commit",
        "contract",
        "decided_at",
        "declared_non_claims",
        "execution_contract_id",
        "execution_contract_sha256",
        "governing_spec_reference",
        "governing_spec_sha256",
        "known_limitation_codes",
        "prompt_artifact_sha256",
        "prompt_id",
        "prompt_lifecycle_state",
        "prompt_reference",
        "prompt_registry_version",
        "qualification_basis",
        "qualification_id",
        "qualification_scope",
        "qualification_status",
        "reviewer",
        "routing_contract_id",
        "routing_contract_sha256",
        "schema_version",
        "stage",
        "stage_output_contract_id",
        "stage_output_contract_sha256",
        "supersedes_qualification_id",
    }
)

BASIS_UNSUPPORTED = "prompt_qualification_basis_unsupported"
PROMPT_QUALIFICATION_INVALID = "prompt_qualification_invalid"
PROMPT_QUALIFICATION_MISMATCH = "prompt_qualification_mismatch"
REFERENCE_UNRESOLVABLE = "prompt_qualification_reference_unresolvable"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
# ``re.fullmatch`` is strict about the whole string, so no lookahead is needed
# here. The schema needs one because an ECMA-262 ``pattern`` is a search whose
# ``$`` matches before a trailing line terminator, which would admit a reference
# carrying an embedded newline.
_PROMPT_REFERENCE_RE = re.compile(r"prompts/extraction/[a-z0-9_]+\.md")
_CHANGE_REQUEST_REFERENCE_RE = re.compile(r"evals/change_requests/CR-[0-9]{4}-[a-z0-9-]+\.md")


def _require_text(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(
            f"prompt qualification {field} must be a non-blank string",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )
    return value


def _require_digest(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ExtractionError(
            f"prompt qualification {field} must be 64 lowercase hex characters",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )
    return value


def _require_reference(record: dict[str, Any], field: str, pattern: re.Pattern[str]) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ExtractionError(
            f"prompt qualification {field} is not a permitted repository reference",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )
    return value


def _require_const(record: dict[str, Any], field: str, expected: str) -> None:
    if record.get(field) != expected:
        raise ExtractionError(
            f"prompt qualification {field} must be {expected!r}",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )


def _require_equal(field: str, observed: Any, expected: Any, subject: str) -> None:
    if observed != expected:
        raise ExtractionError(
            f"the prompt qualification {field} is not {subject}",
            reason_code=PROMPT_QUALIFICATION_MISMATCH,
            detail=f"expected {expected!r}, observed {observed!r}",
        )


def _require_repo_document(
    repo_root: str | Path, reference: str, digest: str, *, what: str
) -> None:
    """Re-read a cited repository document and prove it is the pinned bytes.

    The read happens against ``repo_root``, never the governance root, and goes
    through the shared containment used for every pinned artifact: relative-only,
    no drive qualifier, no upward traversal, no symlink, no escape.
    """
    hydrate_pinned_bytes(
        repo_root,
        {"reference": reference, "sha256": digest},
        what=what,
        unsafe_code=REFERENCE_UNRESOLVABLE,
        sha_code=REFERENCE_UNRESOLVABLE,
    )


def validate_prompt_qualification(
    *,
    record: Any,
    enablement: dict[str, Any],
    authorization: dict[str, Any],
    qualification: dict[str, Any],
    prompt: dict[str, Any],
    prompt_plan: dict[str, Any],
    stage: str,
    stage_output_schema_sha256: str,
    client_contract_sha256: str,
    code_commit: str,
    run_created_at: str,
    repo_root: str | Path,
) -> dict[str, Any]:
    """Bind the pinned prompt qualification to what this route is about to send.

    The caller has already hash-verified the record's bytes against the pin the
    enablement declares. What remains is the part a digest cannot establish: that
    the record qualifies *this* prompt, *this* stage-output contract, *this*
    execution contract and *this* route, on a basis whose evidence exists.
    """
    if not isinstance(record, dict):
        raise ExtractionError(
            "the prompt qualification record must be a mapping",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )

    # P0. Before the property set is selected, because the two bases have
    # different shapes and only one of them has verifiable evidence. The declared
    # value is deliberately not echoed: nothing has been scanned yet.
    basis = record.get("qualification_basis")
    if basis != BOOTSTRAP_BASIS:
        raise ExtractionError(
            "this route accepts only a bootstrap_pre_evaluation prompt "
            "qualification; an evaluated_comparison record cites evaluation runs "
            "that no injected root can hash-verify here, and a schema-valid but "
            "unverified reference must not authorize a live call",
            reason_code=BASIS_UNSUPPORTED,
        )

    # Scans for credential material first, then refuses any missing or undeclared
    # property against the closed bootstrap set.
    record = _require_exact_properties(
        record,
        PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP,
        what="prompt qualification record",
        code=PROMPT_QUALIFICATION_INVALID,
    )

    _require_const(record, "contract", PROMPT_QUALIFICATION_CONTRACT)
    _require_const(record, "schema_version", PROMPT_QUALIFICATION_SCHEMA_VERSION)
    _require_const(record, "governing_spec_reference", GOVERNING_SPEC_REFERENCE)

    # ADR-053 (G6-P). This was a const pinned to ``extraction_prompt_registry_v1``
    # and, forty lines below, an equality against the version *this build*
    # resolved. Together they made the prompt registry unchangeable: any move --
    # a reorder, an addition -- left the two demands unsatisfiable at once, so a
    # released validator silently froze a registry it does not own.
    #
    # A record documents the registry version that was current when it was
    # minted. Membership in the closed, code-owned set of published versions is
    # the question worth asking; equality with today's constant is not.
    if record.get("prompt_registry_version") not in KNOWN_PROMPT_REGISTRY_VERSIONS:
        raise ExtractionError(
            "prompt_registry_version must be one of the registry versions this "
            f"code has published: {list(KNOWN_PROMPT_REGISTRY_VERSIONS)}",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )

    # The bootstrap iff. These three values are what makes the basis honest, and
    # together they keep a pre-evaluation record from ever reaching pilot or
    # release; refusing a revoked status or a draft lifecycle separately would be
    # dead code beneath them.
    _require_const(record, "qualification_scope", BOOTSTRAP_SCOPE)
    _require_const(record, "qualification_status", BOOTSTRAP_STATUS)
    _require_const(record, "prompt_lifecycle_state", BOOTSTRAP_LIFECYCLE_STATE)
    for party, label in ((enablement, "enablement"), (authorization, "authorization")):
        if party.get("rollout_state") != BOOTSTRAP_ROLLOUT_STATE:
            raise ExtractionError(
                "a bootstrap_pre_evaluation prompt qualification authorizes only "
                f"the {BOOTSTRAP_ROLLOUT_STATE} rollout state, and the {label} "
                "declares another",
                reason_code=PROMPT_QUALIFICATION_INVALID,
            )

    if list(record.get("declared_non_claims") or ()) != list(DECLARED_NON_CLAIMS):
        raise ExtractionError(
            "a bootstrap prompt qualification must declare exactly the four "
            "non-claims, in order",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )

    limitations = record.get("known_limitation_codes")
    if (
        not isinstance(limitations, list)
        or not limitations
        or len(set(limitations)) != len(limitations)
        or any(code not in KNOWN_LIMITATION_CODES for code in limitations)
    ):
        raise ExtractionError(
            "known_limitation_codes must be a non-empty list of distinct codes "
            "from the closed vocabulary",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )

    supersedes = record.get("supersedes_qualification_id")
    if supersedes is not None and (not isinstance(supersedes, str) or not supersedes.strip()):
        raise ExtractionError(
            "supersedes_qualification_id must be a non-blank string or null",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )

    for field in (
        "code_commit",
        "execution_contract_id",
        "qualification_id",
        "reviewer",
        "routing_contract_id",
        "stage_output_contract_id",
    ):
        _require_text(record, field)
    for field in (
        "change_request_sha256",
        "execution_contract_sha256",
        "governing_spec_sha256",
        "prompt_artifact_sha256",
        "routing_contract_sha256",
        "stage_output_contract_sha256",
    ):
        _require_digest(record, field)

    prompt_reference = _require_reference(record, "prompt_reference", _PROMPT_REFERENCE_RE)
    change_request_reference = _require_reference(
        record, "change_request_reference", _CHANGE_REQUEST_REFERENCE_RE
    )

    # P1-P4. The prompt this route resolved, byte for byte. A single edited byte
    # in the frozen artifact breaks P3, which is what forces requalification
    # instead of letting a changed prompt inherit an old decision.
    _require_equal("prompt_id", record.get("prompt_id"), prompt_plan["prompt_id"], "the prompt this route executes")
    _require_equal("prompt_reference", prompt_reference, prompt["reference"], "the resolved prompt artifact")
    _require_equal(
        "prompt_artifact_sha256",
        record.get("prompt_artifact_sha256"),
        prompt["prompt_hash"],
        "the digest of the resolved prompt bytes",
    )
    # ADR-053 (G6-P). The registry-version equality that stood here compared the
    # record against ``load_prompt``'s stamp -- and that stamp is read from a
    # module constant at call time, so it describes the *build*, not the prompt
    # artifact. It therefore added nothing to the binding that P1-P3 do not
    # already establish byte-exactly, while making every historical record
    # invalid the moment the registry moved for an unrelated reason. What the
    # record must satisfy is membership in the published set, checked above.

    # P5-P7. One stage, one output contract, equal to the released schema this
    # run actually validates against.
    _require_equal("stage", record.get("stage"), stage, "the stage of this run")
    _require_equal(
        "stage_output_contract_id",
        record.get("stage_output_contract_id"),
        STAGE_OUTPUT_CONTRACT_ID.get(stage),
        "the stage-output contract identity for this stage",
    )
    _require_equal(
        "stage_output_contract_sha256",
        record.get("stage_output_contract_sha256"),
        stage_output_schema_sha256,
        "the released stage-output schema this run validates against",
    )

    # P8-P10. The executing contract and route, agreed with the rings that
    # already accepted them, so the prompt cannot be qualified under one
    # execution contract while the adapter is qualified under another.
    _require_equal(
        "execution_contract_id",
        record.get("execution_contract_id"),
        qualification.get("execution_contract_id"),
        "the contract the adapter qualification declares",
    )
    _require_equal(
        "execution_contract_sha256",
        record.get("execution_contract_sha256"),
        qualification.get("execution_contract_sha256"),
        "the contract digest the adapter qualification declares",
    )
    _require_equal(
        "execution_contract_sha256",
        record.get("execution_contract_sha256"),
        client_contract_sha256,
        "the client contract this route is about to execute",
    )
    for field in ("routing_contract_id", "routing_contract_sha256"):
        _require_equal(
            field, record.get(field), enablement.get(field), "the route the enablement declares"
        )

    # P11-P12. Two repository documents, re-read and hash-verified against the
    # repository root. Neither is resolvable inside the governance root.
    _require_repo_document(
        repo_root,
        GOVERNING_SPEC_REFERENCE,
        record["governing_spec_sha256"],
        what="prompt qualification governing spec",
    )
    _require_repo_document(
        repo_root,
        change_request_reference,
        record["change_request_sha256"],
        what="prompt qualification change request",
    )

    # P13-P14. The decision belongs to this build, and cannot postdate the run it
    # authorizes. Lexicographic comparison would be wrong rather than imprecise:
    # two spellings of one instant do not compare equal as text.
    _require_equal("code_commit", record.get("code_commit"), code_commit, "the commit of this run")
    decided_at = _require_aware_instant(
        record.get("decided_at"),
        field="prompt qualification decided_at",
        code=PROMPT_QUALIFICATION_INVALID,
    )
    instant = _require_aware_instant(
        run_created_at, field="run_created_at", code=PROMPT_QUALIFICATION_INVALID
    )
    if decided_at > instant:
        raise ExtractionError(
            "the prompt qualification decision postdates the run it authorizes",
            reason_code=PROMPT_QUALIFICATION_INVALID,
        )
    return record
