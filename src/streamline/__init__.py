"""streamline — the AeroDB producer for the Icarus chain.

Geometry (`projects/<aircraft>/geometry/*.vsp3`) → campaign definition → VSPAERO stability and
parasite-drag runs → canonical tables → contract-validated artifacts (`aerodb.json`,
`massprops.json`, `engine_deck.json`) → release. Master Plan §8; the plan of record is in the
2026-08-16 build log.

Package layout mirrors the three extension seams (plan §3.0):

    vsp/         the OpenVSP session and geometry substrate — the only place `openvsp` is imported
    analyses/    Ticket → run(session, geometry, ticket) → Result, registered by name
    backends/    where numbers come from (vspaero, parasite; avl/xfoil later) — same table rows out
    campaign/    the grid, the runner (shardable), the assembler (pure)
    export/      materializers: rows → contract-validated artifact files
    report/      the human-facing PDF/JSON/MD
    cli.py       the only path to artifacts

Nothing here imports `casadi`; the contract package proves ingestibility on its own (plan §2.6).
"""

__version__ = "2.0.0a0"
