# Event System Guide

Streamline’s Textual TUI uses a lightweight event bus (`EventBus`) and a collection of strongly-typed event dataclasses to decouple producers and consumers. This document explains the architecture, the key classes, and the workflow for adding new events.

## Overview

- **Event classes** live in [`streamline/tui/events.py`](./events.py). They are frozen `dataclass` definitions, grouped by concern (manager events, session events, configuration/catalog events, etc.).
- **EventBus** (`streamline/tui/event_bus.py`) is a thread-safe pub/sub dispatcher. Producers call `publish(event)` with an instance of an event class; consumers register callbacks via `subscribe(EventType, handler)` or `subscribe_any(handler)`.
- **Subscribers**: UI components (e.g., `streamline/app.py` handlers) subscribe to the events they care about and update their state in response.

Because events are now strictly typed (string-based APIs have been removed), all communication goes through dataclasses, providing richer payloads and compile-time hints.

## Core Concepts

### Event Classes

`events.py` defines a hierarchy of dataclasses:

- `Event`: base type (contains `type`, `payload`, `ts` but typically unused directly).
- `ManagerEvent`, `SessionEvent`: domain-specific bases.
- Specialisations (examples):
  - `JobSubmittedEvent`, `JobStartedEvent`, `JobCompletedEvent`, `JobFailedEvent`, `ReceiptAddedEvent`.
  - `ConfigurationCreatedEvent`, `ConfigurationUpdatedEvent`, `ConfigurationRemovedEvent`, `ConfigurationStaleEvent`.
  - `CatalogChangedEvent` (for config/op catalogs).
  - `ResultsIndexUpdated`, `CacheIndexUpdated`, `ProjectAssetsRefreshed`.
  - `LogMessageEvent` for logging channels.

Each dataclass defines fields with default values and ensures immutability (`frozen=True`). Instances can be safely passed across threads.

### EventBus

`EventBus` exposes:

```python
bus = EventBus()
subscription = bus.subscribe(ConfigurationCreatedEvent, handler)
subscription.cancel()  # detach later

bus.subscribe_any(handler)  # receives every event

bus.publish(ConfigurationCreatedEvent(config_id="demo", project="proj"))
```

`publish(event)`:
- Captures listeners whose registered type is a super-class of the emitted event (`issubclass(type(event), registered_type)`).
- Dispatches typed callbacks inside a lock-protected loop (exceptions are swallowed to isolate failure).
- Notifies “any” subscribers after typed listeners.

### Global Bus

`get_global_event_bus`/`set_global_event_bus` provide a singleton for app-wide usage:

```python
bus = EventBus()
set_global_event_bus(bus)

bus = get_global_event_bus()
bus.publish(LogMessageEvent(level="INFO", message="Hello"))
```

The TUI sets this up on startup (see `streamline/app.py`).

## Existing Usage Patterns

- **AnalysisManager** (`streamline/analysis/manager.py`): publishes `JobSubmittedEvent`, `JobStartedEvent`, `JobCompletedEvent`, `JobFailedEvent`, `ReceiptAddedEvent` when jobs transition states.
- **ProjectSession** (`streamline/tui/session.py`): publishes `ProjectAssetsRefreshed`, `CatalogChangedEvent`, configuration events, `CacheIndexUpdated`, `ResultsIndexUpdated`, and `ConfigurationStaleEvent` when session state changes. Also handles drift detection/invalidation.
- **Logging** (`streamline/app.py`): `EventBusLogHandler` publishes `LogMessageEvent`. The TUI’s `_handle_event` branch re-renders log widgets based on `LogMessageEvent`.

### Sample UI Handler (from `streamline/app.py`)

```python
def _handle_event(self, evt):
    if isinstance(evt, (JobSubmittedEvent, JobStartedEvent, JobCompletedEvent, JobFailedEvent, ReceiptAddedEvent)):
        self._mark_refresh('jobs')
        ...
        return

    if isinstance(evt, (CatalogChangedEvent, ConfigurationCreatedEvent, ConfigurationUpdatedEvent, ConfigurationRemovedEvent)):
        self._mark_refresh('configs')
        return

    if isinstance(evt, ConfigurationStaleEvent):
        if evt.config_id:
            self.configs_panel.stale_ids.add(evt.config_id)
        self._mark_refresh('configs')
        return

    if isinstance(evt, LogMessageEvent):
        self._schedule_log_append(evt.message, level=evt.level)
```

## How to Create a New Event

1. **Define the dataclass** in `events.py`:
   ```python
   @dataclass(frozen=True)
   class DerivedDataUpdatedEvent(ManagerEvent):
       project: str
       dataset: str
       row_count: int = 0
   ```

2. **Publish the event** from relevant logic:
   ```python
   bus.publish(DerivedDataUpdatedEvent(project=project_id, dataset="run_summary", row_count=42))
   ```

3. **Consume the event** by subscribing in UI/components:
   ```python
   bus.subscribe(DerivedDataUpdatedEvent, self._on_derived_data)

   def _on_derived_data(self, event: DerivedDataUpdatedEvent) -> None:
       self._derived_panel.update(event.dataset, event.row_count)
   ```

4. **Update documentation/tests** if the event has cross-cutting implications.

### Guidelines
- Use `dataclass(frozen=True)` for immutability.
- Prefer explicit typed fields instead of generic `payload` dictionaries.
- Keep event names descriptive and scoped (e.g., `ConfigurationStaleEvent` vs. `StaleEvent`).
- Group events logically in `events.py` (manager-level, configuration-level, etc.).

## Removing Legacy String Events

Now that only typed events remain, avoid calling `EventBus.emit` (it has been removed). The CLI/TUI should always work with `Event` subclasses. Any string-based logic should be migrated to dataclass definitions.

## Troubleshooting

### Event Not Delivered
- Ensure you’re publishing the correct event type (and not a base class if listeners expect a subclass).
- Verify your handler is subscribed before publishing (order matters if `subscribe` happens after `publish`).
- Check for exceptions in handlers; EventBus swallows them silently.

### Duplicate or Missing Handlers
- The bus uses the event type as the key; ensure you aren’t double-registering (subscribe returns a `Subscription` handle you can cancel).
- For cross-cutting listeners, use `subscribe_any`.

### Thread-safety
- EventBus operations acquire an `RLock`. Callbacks may run on whichever thread invoked `publish`. If you need to funnel work onto the UI thread, do so within your callback (e.g., schedule Textual updates via `call_from_thread`).

## Summary

1. Dataclasses define the event schema in `events.py`.
2. `EventBus` handles publication and typed subscriptions.
3. Producers emit dataclass instances (`bus.publish(EventSubclass(...))`).
4. Consumers subscribe via `subscribe/Event`.
5. New events follow the pattern: define dataclass, publish, subscribe, document.

For questions or updating patterns, refer to `streamline/app.py` and `streamline/tui/session.py` which demonstrate end-to-end usage of the event system.
