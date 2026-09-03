from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from black_ice_common.tracing import extract_kafka_context, inject_kafka_headers


def test_trace_context_survives_a_kafka_hop():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("producer.publish") as producer_span:
        producer_trace_id = producer_span.get_span_context().trace_id
        headers = inject_kafka_headers()

    ctx = extract_kafka_context(headers)
    with tracer.start_as_current_span("consumer.process", context=ctx) as consumer_span:
        consumer_trace_id = consumer_span.get_span_context().trace_id

    assert consumer_trace_id == producer_trace_id, "consumer span should join the producer's trace, not start a new one"

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert spans["consumer.process"].parent.span_id == spans["producer.publish"].get_span_context().span_id


def test_extract_with_no_headers_does_not_crash():
    ctx = extract_kafka_context(None)
    assert ctx is not None
