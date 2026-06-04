"""Adapter: PostService ``.dispatch(Event)`` → the core EventBus (S47.1).

``PostService`` emits ``content.changed`` by calling
``event_dispatcher.dispatch(Event(name, data))``. The plugin-facing pub/sub
seam is the core ``EventBus`` (``subscribe``/``publish``), which is what the
prerender writer listens on. This thin adapter bridges the two — exposing the
``.dispatch(Event)`` method PostService expects and forwarding to
``event_bus.publish(event.name, event.data)`` — so the writer (and any future
content subscriber) receives the event without changing PostService.
"""
from vbwd.events.bus import event_bus


class ContentEventPublisher:
    """Publishes a PostService ``Event`` onto the core EventBus."""

    def __init__(self, bus=None) -> None:
        self._bus = bus or event_bus

    def dispatch(self, event):
        """Forward ``event.name`` + ``event.data`` to the bus."""
        self._bus.publish(event.name, event.data or {})
        return event
