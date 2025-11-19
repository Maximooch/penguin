import json
import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Context variables for trace propagation
_current_trace_id = ContextVar("current_trace_id", default=None)
_current_span_id = ContextVar("current_span_id", default=None)
_current_parent_span_id = ContextVar("current_parent_span_id", default=None)

class SpanStatus(Enum):
    OK = "ok"
    ERROR = "error"

@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    start_time: float
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: list = field(default_factory=list)
    status: SpanStatus = SpanStatus.OK
    end_time: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "end_time": datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            "duration_ms": (self.end_time - self.start_time) * 1000 if self.end_time else None,
            "status": self.status.value,
            "attributes": self.attributes,
            "events": self.events,
        }

class Tracer:
    def __init__(self, service_name: str = "penguin"):
        self.service_name = service_name

    def start_trace(self, name: str) -> "SpanContext":
        trace_id = str(uuid.uuid4())
        return self.start_span(name, trace_id=trace_id)

    def start_span(self, name: str, trace_id: Optional[str] = None, parent_span_id: Optional[str] = None) -> "SpanContext":
        if trace_id is None:
            trace_id = _current_trace_id.get() or str(uuid.uuid4())
        
        if parent_span_id is None:
            parent_span_id = _current_span_id.get()

        span_id = str(uuid.uuid4())
        
        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            start_time=time.time(),
        )
        
        return SpanContext(span)

class SpanContext:
    def __init__(self, span: Span):
        self.span = span
        self._token_trace = None
        self._token_span = None
        self._token_parent = None

    def __enter__(self):
        self._token_trace = _current_trace_id.set(self.span.trace_id)
        self._token_span = _current_span_id.set(self.span.span_id)
        self._token_parent = _current_parent_span_id.set(self.span.parent_span_id)
        
        # Log span start
        logger.debug(f"Span started: {self.span.name} [trace_id={self.span.trace_id} span_id={self.span.span_id}]")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.span.end_time = time.time()
        if exc_type:
            self.span.status = SpanStatus.ERROR
            self.span.attributes["error.type"] = exc_type.__name__
            self.span.attributes["error.message"] = str(exc_val)
        
        # Reset context vars
        _current_trace_id.reset(self._token_trace)
        _current_span_id.reset(self._token_span)
        _current_parent_span_id.reset(self._token_parent)
        
        # Log span completion (structured)
        log_payload = json.dumps(self.span.to_dict())
        logger.info(f"TRACE_EVENT: {log_payload}")

    def set_attribute(self, key: str, value: Any):
        self.span.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        event = {
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "attributes": attributes or {}
        }
        self.span.events.append(event)

# Global tracer instance
tracer = Tracer()
