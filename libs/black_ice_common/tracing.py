"""Distributed tracing across the Kafka pipeline. HTTP gets trace context for free
from the FastAPI instrumentor; a Kafka hop doesn't, so ingest/detect/embed/match
each inject/extract the W3C traceparent through message headers by hand — this is
the part that actually explains what "distributed" means once GPU inference and
queueing are involved (spec: "p99 latency, distributed tracing")."""
import os

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_initialized_for: str | None = None


def init_tracing(service_name: str) -> trace.Tracer:
    global _initialized_for
    if _initialized_for != service_name:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
        trace.set_tracer_provider(provider)
        _initialized_for = service_name
    return trace.get_tracer(service_name)


def inject_kafka_headers() -> list[tuple[str, bytes]]:
    """Call while the producing span is current; returns headers for Producer.produce()."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return [(k, v.encode("utf-8")) for k, v in carrier.items()]


def extract_kafka_context(headers: list[tuple[str, bytes]] | None):
    """Reconstructs the parent context from a consumed message's headers, to pass
    as `context=` into tracer.start_as_current_span on the consuming side."""
    carrier = {k: v.decode("utf-8") for k, v in (headers or [])}
    return propagate.extract(carrier)
