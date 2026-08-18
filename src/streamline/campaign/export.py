"""Export: the assembled documents → release files, with the MANIFEST as the hash ledger.

Hashed files are written through the contract's canonical writer; `BUILD.json` (timestamps, host,
durations) is the only place wallclock is allowed and is never hashed (§10.3). `release_gate`
is the refusal: blocking lint, unpinned solver, or missing release-required completeness stops a
release — but not an exploratory export, which is how a failing artifact gets LOOKED AT.
"""

from __future__ import annotations

import datetime
import platform
from pathlib import Path

from aerodb_contract import canonical_json, lint as lint_mod, load as contract_load, schema as contract_schema


class ReleaseBlocked(RuntimeError):
    pass


def write_release(out_dir: Path, *, aerodb: dict, massprops: dict | None,
                  engine_deck: dict | None, raw_paths: list[Path],
                  streamline_commit: str) -> dict:
    """Write every artifact + MANIFEST.json + BUILD.json into out_dir; returns the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    files["aerodb.json"] = canonical_json.write(out_dir / "aerodb.json", aerodb)
    if massprops is not None:
        files["massprops.json"] = canonical_json.write(out_dir / "massprops.json", massprops)
    if engine_deck is not None:
        files["engine_deck.json"] = canonical_json.write(out_dir / "engine_deck.json", engine_deck)

    merged = out_dir / "raw.jsonl"
    with merged.open("w", encoding="utf-8", newline="\n") as fh:
        for p in raw_paths:
            fh.write(Path(p).read_text(encoding="utf-8"))
    files["raw.jsonl"] = canonical_json.sha256_file(merged)

    manifest = {
        "id": aerodb["id"],
        "contract_version": contract_schema.SCHEMA_VERSION,
        "files": files,
        "geometry_sha256": aerodb["aircraft"]["geometry_sha256"],
        "campaign_sha256": aerodb["provenance"]["campaign_sha256"],
        "streamline_commit": streamline_commit,
        "openvsp_version": aerodb["provenance"]["backend"]["openvsp_version"],
        "unpinned": aerodb["provenance"]["backend"]["unpinned"],
    }
    contract_schema.check(manifest, "manifest")
    canonical_json.write(out_dir / "MANIFEST.json", manifest)

    # Unhashed sidecar — the ONLY file allowed a clock or a hostname.
    build = {"written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "host": platform.node(), "platform": platform.platform()}
    (out_dir / "BUILD.json").write_text(canonical_json.dumps(build), encoding="utf-8")
    return manifest


def release_gate(aerodb: dict) -> None:
    """Raise unless this artifact is releasable: pinned solver, no blocking lint, contract-valid."""
    contract_schema.check(aerodb, "aerodb")
    blocking = lint_mod.blocking(aerodb["lint"]["results"])
    if blocking:
        lines = [f"{r['check']}: {r['detail']}" for r in blocking]
        raise ReleaseBlocked("blocking lint failures:\n  " + "\n  ".join(lines))
