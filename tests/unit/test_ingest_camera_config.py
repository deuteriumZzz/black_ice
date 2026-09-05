"""_resolve_config's retry/hard-fail logic, tested against a mocked HTTP
server — fast and deterministic. This does NOT prove ingest's real HTTP
contract with match matches (schema drift between them can't be caught by
mocks); that's covered separately by a live test against a real match
container (see the plan for Milestone 2 — mocks alone would have been the
wrong tool here given Milestone 1's lesson about sqlite hiding real bugs)."""
import pytest
import requests.exceptions
import responses

from black_ice_common.config import settings
from services.ingest.main import _resolve_config


@pytest.fixture(autouse=True)
def _match_api_url(monkeypatch):
    monkeypatch.setattr(settings, "match_api_url", "http://match-test")


@responses.activate
def test_resolve_config_returns_source_and_fps():
    responses.get("http://match-test/cameras/cam-0/config", json={"source": "rtsp://cam0", "ingest_fps": 8.0}, status=200)
    source, fps = _resolve_config("cam-0")
    assert source == "rtsp://cam0"
    assert fps == 8.0


@responses.activate
def test_resolve_config_raises_on_404_without_retrying():
    responses.get("http://match-test/cameras/missing/config", status=404)
    with pytest.raises(RuntimeError, match="not registered"):
        _resolve_config("missing")
    assert len(responses.calls) == 1, "a 404 (camera doesn't exist) must not be retried"


@responses.activate
def test_resolve_config_raises_on_403_without_retrying():
    responses.get("http://match-test/cameras/disabled/config", json={"detail": "camera is disabled"}, status=403)
    with pytest.raises(RuntimeError, match="disabled"):
        _resolve_config("disabled")
    assert len(responses.calls) == 1


@responses.activate
def test_resolve_config_raises_on_401_without_retrying():
    """A wrong/missing INGEST_API_KEY is a distinct failure from a disabled
    camera (see rbac.ROLES's "ingest" role) — both are now possible on this
    call, and neither should be silently retried."""
    responses.get("http://match-test/cameras/cam-0/config", json={"detail": "invalid API key"}, status=401)
    with pytest.raises(RuntimeError, match="invalid API key"):
        _resolve_config("cam-0")
    assert len(responses.calls) == 1


@responses.activate
def test_resolve_config_sends_ingest_api_key(monkeypatch):
    monkeypatch.setattr(settings, "ingest_api_key", "test-ingest-key")
    responses.get("http://match-test/cameras/cam-0/config", json={"source": "0", "ingest_fps": 5.0}, status=200)
    _resolve_config("cam-0")
    assert responses.calls[0].request.headers["X-API-Key"] == "test-ingest-key"


@responses.activate
def test_resolve_config_retries_transient_failures_then_succeeds():
    responses.get("http://match-test/cameras/cam-1/config", body=requests.exceptions.ConnectionError("refused"))
    responses.get("http://match-test/cameras/cam-1/config", body=requests.exceptions.ConnectionError("refused"))
    responses.get("http://match-test/cameras/cam-1/config", json={"source": "0", "ingest_fps": 5.0}, status=200)

    source, fps = _resolve_config("cam-1")
    assert source == "0"
    assert fps == 5.0
    assert len(responses.calls) == 3


@responses.activate
def test_resolve_config_gives_up_after_exhausting_retries():
    for _ in range(3):
        responses.get("http://match-test/cameras/cam-2/config", body=requests.exceptions.ConnectionError("refused"))
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        _resolve_config("cam-2")
