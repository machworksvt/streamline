"""Engine bench data → engine_deck.json (Master Plan §8 sibling artifact, D8).

Layout mirrors the aero side: `ingest` reads what was logged (no interpretation), `fit` reduces
it to the deck's numbers with every reduction step recorded, `deck` assembles the artifact. The
dynamic MODEL (spool ODE, fuel state, thrust lapse) lives in icarus-dynamics and reads its
constants from the deck — this package produces parameters with provenance, never a simulation.
"""
