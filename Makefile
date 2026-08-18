# streamline — every target runs inside `nix develop -c` (the shell IS the environment, §8.9).
#
#   make check          contract tests + unit tests + real-VSP smoke (the PR tier's first step)
#   make test           the whole suite including the slow real solves
#   make golden         the Icarus coarse-grid reference campaign, tolerance-checked   (P5)
#   make massprops      Fusion body export + overrides → projects/icarus/massprops/ledger.json
#   make determinism    assemble+export twice from the same raw rows, byte-diff        (P5)
#   make campaign       the canonical campaign, one shard                              (P5)
#   make report         the validation report for build/                              (P6)
#   make spec           regenerate contract/aerodb_contract/spec.md from the schema     (P2)
#
# Targets that do not exist yet fail loudly rather than pretending; they arrive with their phase.

PY ?= python
PYTEST ?= $(PY) -m pytest

.PHONY: check test fast golden engine massprops determinism campaign report spec version clean

check:
	$(PYTEST) -q -m "not slow"

test:
	$(PYTEST) -q

fast:
	$(PYTEST) -q -m "not vsp"

version:
	$(PY) -m streamline.cli version

spec:
	$(PY) -m aerodb_contract.spec > contract/aerodb_contract/spec.md

# CAMPAIGN/RAW/OUT are provided by the caller, e.g.
#   make campaign CAMPAIGN=projects/icarus/campaign/canonical.json OUT=build/run
CAMPAIGN ?=
RAW ?= $(OUT)/shard0.jsonl
OUT ?= build/run

campaign:
	@test -n "$(CAMPAIGN)" || { echo "make campaign CAMPAIGN=<campaign.json> [OUT=dir]"; exit 2; }
	$(PY) -m streamline.cli campaign run $(CAMPAIGN) --out $(OUT)

assemble:
	@test -n "$(CAMPAIGN)" || { echo "make assemble CAMPAIGN=<campaign.json> [RAW=rows...] [OUT=dir]"; exit 2; }
	$(PY) -m streamline.cli campaign assemble $(CAMPAIGN) --raw $(RAW) --out $(OUT)/release

# §10.3: assemble+export twice from the SAME raw rows, byte-diff the hashed artifacts.
determinism:
	@test -n "$(CAMPAIGN)" || { echo "make determinism CAMPAIGN=<campaign.json> [RAW=rows...]"; exit 2; }
	rm -rf build/det1 build/det2
	$(PY) -m streamline.cli campaign assemble $(CAMPAIGN) --raw $(RAW) --out build/det1 --commit 0000000000000000
	$(PY) -m streamline.cli campaign assemble $(CAMPAIGN) --raw $(RAW) --out build/det2 --commit 0000000000000000
	diff build/det1/aerodb.json build/det2/aerodb.json
	diff build/det1/MANIFEST.json build/det2/MANIFEST.json
	@echo "determinism: byte-identical"

# The coarse PR-tier campaign on the real geometry: run + assemble + lint gate. The
# tolerance-check against golden/reference/ lands once a reference is pinned (needs the NCPU
# bit-stability answer first — see the plan).
golden: engine massprops
	$(PY) -m streamline.cli campaign run projects/icarus/campaign/golden.json --out build/golden
	$(PY) -m streamline.cli campaign assemble projects/icarus/campaign/golden.json \
	    --raw build/golden/shard0.jsonl --out build/golden/release --gate \
	    --engine projects/icarus/engine/engine_deck.json \
	    --ledger projects/icarus/massprops/ledger.json

# The mass ledger: Fusion body export + declared overrides → ledger.json (deterministic; committed).
massprops:
	$(PY) -m streamline.cli massprops from-fusion \
	    --bodies projects/icarus/massprops/fusion/bodies-2026-08-18.psv \
	    --overrides projects/icarus/massprops/fusion-overrides.json \
	    --out projects/icarus/massprops/ledger.json

# The engine deck: bench bags + spec.json → engine_deck.json (deterministic; committed alongside).
engine:
	$(PY) -m streamline.cli engine fit projects/icarus/engine/spec.json

report:
	@echo "make $@: not implemented yet — arrives with its phase (see the plan)"; exit 1

clean:
	rm -rf build .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
