"""Shared infrastructure for all microservices."""
from shared.event_bus import EventBus, get_event_bus, init_event_bus
from shared.event_schemas import *
