# Analysis Manager Guide

The `AnalysisManager` orchestrates registration, execution, caching, and persistence of analyses. This document explains how analyses are constructed, how tickets/receipts flow through the system, and how to add new analyses safely.

---

## Architecture Overview

Key modules:

- `streamline/analysis/manager.py`: AnalysisManager implementation, job queue, caching, materializers.
- `streamline/analysis/contracts/*.py`: Base Ticket/Receipt models.
- `streamline/vsp/analyses/*.py`: Concrete run/materializer functions for openVSP analyses.
- `streamline/io/results_index.py`, `streamline/io/cache_store.py`: Persistence of results and cached receipts.

High-level workflow:

1. Register an analysis with `register_analysis(...)`.
2. Submit a ticket (`manager.submit(...)`) to queue a job.
3. `run_next()` executes (if dependencies satisfied), producing a receipt.
4. Receipt is cached and persisted via materializer.
5. Events are emitted via `EventBus` to keep UI state in sync.

---

## Tickets, Receipts, Materializers

### Tickets

- Define input parameters for an analysis.
- Must inherit from `streamline.analysis.contracts.Ticket` (Pydantic model).
- Implement `.model_dump()` for serialization; `.sha256(context)` ensures deterministic cache keys.
- Example: `ComputeGeometryTicket`, `CompGeomTicket`, `StabilityTicket`.

### Receipts

- Output artifact descriptions and metadata.
- Inherit from `streamline.analysis.contracts.Receipt`.
- Include `ticket_sha256`, `run_manifest`, optional artifacts and derived stats (e.g., total drag).
- Serve as cached results (in-memory and persisted to disk).

### Materializers

- Functions converting raw run result into a `Receipt`.
- Responsible for:
  - Writing artifacts to disk (`prepare_results_dir`, `dump_json`, etc.).
  - Recording manifest times, dependencies, derived metrics.
  - Updating results index (`append_result_entry`).
- Always run within atomic execution of job; failures surface as `AnalysisError`.

---

## Registering an Analysis

`AnalysisManager.register_analysis(...)` requires:

- `key`: unique identifier (string).
- `runner`: callable that executes the analysis. Signature typically `(vsp_module, ticket, **kwargs)`.
- `materializer`: optional callable to convert results into a Receipt.
- `default_kwargs`: static run parameters (merged with job runtime kwargs).
- `default_dependency_keys`: high-level cache invalidation groups (e.g., `vsp_model`, `configuration`).
- `description`: optional user-facing description.
- `uses_vsp_lock`: ensures exclusive VSP access (default `True`).
- `receipt_model`: Pydantic class for receipts (enables caching/persistence).

`register_analysis` also restores any deferred cache entries (when receipt models were not yet available).

### Example (comp geometry)

```python
manager.register_analysis(
    "comp_geom",
    run_comp_geom,
    materializer=_materialize_comp_geom,
    default_dependency_keys={"vsp_model", "configuration"},
    receipt_model=CompGeomReceipt,
    description="Run OpenVSP CompGeom surface intersection analysis",
)
```

---

## Submitting Jobs

`manager.submit(analysis_key, ticket, context_extras=None, runtime_kwargs=None, dependency_keys=None, wait_for=None, priority=0) -> job_id`

- Validates analysis key.
- Generates `AnalysisJob` with unique `job_id`.
- Computes dependency keys (default + provided).
- Enqueues job ID (FIFO queue by default).
- Emits event via `EventBus` (`JobSubmittedEvent`).

### Context data

- `context_extras`: extra metadata to attach (stored on job state and included in events).
- `runtime_kwargs`: per-job overrides merged with defaults.
- `dependency_keys`: additional cache invalidation tokens (e.g., `operating_point:<id>`).
- `wait_for`: set of job IDs that must complete before running.

---

## Execution Lifecycle

`AnalysisManager.run_next(block=False, timeout=None)`:

1. Dequeues job ID (`queue.get`).
2. `_execute_job(job_id)` checks dependencies via `_dependencies_satisfied`. If unresolved, requeues and returns.
3. Computes ticket SHA (`ticket.sha256(context_extras)`).
4. Cache lookup (`cache_entry`) by `(analysis_key, ticket_sha)`:
   - If present, mark job state as `cached`, emit events, return receipt.
5. Execute runner (with VSP lock if `uses_vsp_lock`):
   - If VSP not available (and required), raise `AnalysisError`.
   - Exceptions propagate and mark job as failed (emitting `JobFailedEvent`).
6. Materializer (if provided) or direct Receipt returned by runner.
7. Cache entry stored in memory + dependency index updated.
8. Result persisted (materializer handles artifacts and results index).
9. Events emitted: `JobCompletedEvent`, `ReceiptAddedEvent`.

### JobState Tracking

- `AnalysisManager.job_state(job_id)` returns `JobState` object (status, timestamps, receipt, errors).
- `pending_jobs()` enumerates jobs still in `pending` or `running`.
- `drain()` repeatedly runs until queue empty (non-blocking option).

---

## Cache & Persistence

### In-memory Cache

`self._cache` maps `analysis_key -> {ticket_sha: AnalysisCacheEntry}`:
- `AnalysisCacheEntry` stores receipt, timestamp, dependency keys.
- Accessed via `cache_entry`.
- `cache_summaries()` returns metadata for introspection (used by UI).

### Dependency Index

`DependencyIndex` records dependency keys per ticket SHA to support efficient invalidation:
- `record(ticket_sha, keys)`
- `invalidate(keys)`: returns set of affected ticket SHAs for removal.

### Persistence

- Results index (`results/index.json`) updated via `append_result_entry`.
- Cache store persisted to disk (`cache_store.py`) when needed:
  - `_persist_cache_locked`: serializes `CacheRecord` entries for analyses with receipt models.
  - `_load_persisted_cache_locked`: at startup, repopulates receipts (skipping if receipt model missing).

### Invalidation

`invalidate(keys: Iterable[str]) -> Set[str]`:
- Uses `DependencyIndex` to find impacted tickets.
- Removes cache entries and updates disk (if `drop_results=True`, `remove_result_entries` invoked).

---

## Events

The manager publishes typed events (see `EVENTS.md` for full list):
- `JobSubmittedEvent`, `JobStartedEvent`, `JobCompletedEvent`, `JobFailedEvent`, `ReceiptAddedEvent`.
- `CacheIndexUpdated` and `ResultsIndexUpdated` are typically fired by `ProjectSession` when synchronising state.

These keep the TUI and other listeners informed of job progress and results.

---

## Adding a New Analysis

1. **Define ticket and receipt models** (if necessary):
   ```python
   class MyAnalysisTicket(Ticket):
       parameter: float

   class MyAnalysisReceipt(Receipt):
       result_value: float
   ```

2. **Implement runner** (`run_my_analysis`):
   - Accepts `(vsp_module, ticket, **kwargs)`.
   - Should not mutate global state beyond VSP interactions.
   - Return raw result or direct Receipt.

3. **Implement materializer** (if runner returns raw data):
   ```python
   def _materialize_my_analysis(manager, job, ticket_sha, result, started_at, ended_at):
       results_root = manager.results_root
       # Use prepare_results_dir, dump_json, etc.
       receipt = MyAnalysisReceipt(
           ticket_sha256=ticket_sha,
           run_manifest=RunManifest(
               ticket=job.ticket.model_dump(),
               started_utc=started_at,
               ended_utc=ended_at,
           ),
           result_value=result["value"],
       )
       # append_result_entry(results_root, ResultIndexEntry(...))
       return receipt
   ```

4. **Register the analysis**:
   ```python
   manager.register_analysis(
       "my_analysis",
       run_my_analysis,
       materializer=_materialize_my_analysis,
       default_dependency_keys={"vsp_model", "configuration", "operating_point"},
       receipt_model=MyAnalysisReceipt,
       description="Compute custom aerodynamic metric",
   )
   ```

5. **Submit jobs**: `manager.submit("my_analysis", MyAnalysisTicket(parameter=1.23))`.

6. Ensure `receipt_model` is set to enable caching/persistence.

### Dependency Keys

- Use descriptive tokens: `vsp_model`, `configuration`, `operating_point`, etc.
- For fine-grained invalidation, append identifiers (e.g., `configuration:<config_id>`).
- `ProjectSession` handles invalidation when configurations or ops change.

---

## Advanced Topics

### Job Dependencies (`wait_for`)

Jobs can specify `wait_for` (set of job IDs). `_dependencies_satisfied` ensures:
- Pending/running dependencies postpone execution (job requeued).
- Failed/cancelled dependencies raise `AnalysisError`.

### Priority Queue

Currently `priority` is stored but queue is FIFO. Extending to a priority queue would entail replacing `Queue` with `PriorityQueue` and adjusting submission logic.

### Auto-Persistence on Shutdown

`AnalysisManager.shutdown()` currently logs a debug statement (placeholder). For background threads or async execution, extend this to join worker threads or flush cache.

### Partial Receipts / Deferred Loading

If an analysis is registered without `receipt_model`, cached `CacheRecord` entries are held in `_deferred_cache_records` and applied once the analysis is registered with a receipt model.

---

## Testing New Analyses

- Create tests in `tests/vsp/` or appropriate package to:
  - Register analysis.
  - Submit job (with stubbed VSP module if necessary).
  - Verify receipt contents, caching, and events.
- For VSP-dependent tests, use pytest markers (`pytest.mark.vsp`) and skip when runtime missing (`VSPSessionError`).

---

## Reference

- `streamline/analysis/manager.py`
- `streamline/vsp/analyses/*.py` (examples: `compute_geometry`, `comp_geom`, `stability`, `parasite_drag`)
- `streamline/analysis/contracts/*.py`
- `streamline/vsp/contracts/*.py` (examples: compute_geometry, etc.)
- `streamline/io/results_index.py`, `streamline/io/cache_store.py`
- `streamline/tui/events.py`, `streamline/tui/event_bus.py`

For event usage, see [`streamline/tui/EVENTS.md`](../tui/EVENTS.md).
