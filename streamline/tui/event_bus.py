from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, Type, TypeVar

from .events import Event

EventT = TypeVar("EventT", bound=Event)

_GLOBAL_EVENT_BUS = None  # singleton holder


def get_global_event_bus():  # pragma: no cover - trivial accessor
    return _GLOBAL_EVENT_BUS


def set_global_event_bus(bus):  # pragma: no cover - trivial accessor
    global _GLOBAL_EVENT_BUS
    _GLOBAL_EVENT_BUS = bus


@dataclass
class Subscription:
    """Handle returned when registering a callback with the event bus."""

    token: str
    event_type: Type[Event]
    callback: Callable[[Event], None]
    _bus: "EventBus"

    def cancel(self) -> None:
        """Remove this subscription from the event bus."""

        self._bus.unsubscribe(self)


class EventBus:
    """Simple, threadsafe pub/sub dispatcher for TUI events."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: Dict[Type[Event], Dict[str, Callable[[Event], None]]] = {}
        self._any_subscribers: Dict[str, Callable[[Event], None]] = {}

    def publish(self, event: Event) -> None:
        """Send *event* to all interested subscribers."""

        listeners: Dict[str, Callable[[Event], None]] = {}
        event_type = type(event)
        with self._lock:
            for registered_type, callbacks in self._subscribers.items():
                if issubclass(event_type, registered_type):
                    listeners.update(callbacks)
            any_callbacks = list(self._any_subscribers.values())
        for callback in listeners.values():
            try:
                callback(event)
            except Exception:
                pass
        for callback in any_callbacks:
            try:
                callback(event)
            except Exception:
                pass

    def subscribe(self, event_type: Type[EventT], callback: Callable[[EventT], None]) -> Subscription:
        """Register *callback* for *event_type* and return a subscription handle."""

        token = uuid.uuid4().hex
        with self._lock:
            callbacks = self._subscribers.setdefault(event_type, {})
            callbacks[token] = callback  # type: ignore[assignment]
        return Subscription(token=token, event_type=event_type, callback=callback, _bus=self)

    def subscribe_any(self, callback: Callable[[Event], None]) -> Subscription:
        token = uuid.uuid4().hex
        with self._lock:
            self._any_subscribers[token] = callback
        return Subscription(token=token, event_type=Event, callback=callback, _bus=self)

    def unsubscribe(self, subscription: Subscription) -> None:
        """Detach *subscription* from the bus."""

        with self._lock:
            callbacks = self._subscribers.get(subscription.event_type)
            if callbacks:
                callbacks.pop(subscription.token, None)
                if not callbacks:
                    self._subscribers.pop(subscription.event_type, None)
            if subscription.event_type is Event:
                self._any_subscribers.pop(subscription.token, None)

    def clear(self, *, event_types: Optional[Iterable[Type[Event]]] = None) -> None:
        """Remove subscriptions, optionally limited to *event_types*."""

        with self._lock:
            if event_types is None:
                self._subscribers.clear()
                return
            for event_type in event_types:
                self._subscribers.pop(event_type, None)
