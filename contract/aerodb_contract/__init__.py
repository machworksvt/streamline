"""aerodb_contract — the contract between streamline (producer) and icarus-dynamics (consumer).

Dependency-free beyond numpy, on purpose: the consumer's dev shell is stdlib + numpy + casadi and
must not grow a package to read an aero table. Owned by streamline (decision D5, 2026-08-16);
icarus-dynamics pins this directory as a flake input.

    schema        the fields of aerodb.json / massprops.json / engine_deck.json / MANIFEST.json
    conventions   frames, signs, units, vocabulary — locked with the schema (conventions.md is the prose)
    load          AeroDB / MassProps / EngineDeck loaders and the numpy reference evaluator
    signs         round-trip sign fixtures, asserted at export and at ingest
    lint          physics lint, results embedded in the artifact
    completeness  the model-completeness checklist (§8.7)
    canonical_json  the one writer every hashed file goes through
    synthetic     a plausible synthetic AeroDB for tests and the ingest proof
    spec          renders spec.md
"""

from .schema import SCHEMA_VERSION, ContractError, check, validate  # noqa: F401
from .load import AeroDB, EngineDeck, MassProps, transfer_moment  # noqa: F401
from .conventions import CONVENTIONS, SURFACES, CONTROL_SURFACES, COEFFICIENTS, RATES  # noqa: F401

CONTRACT_VERSION = SCHEMA_VERSION
