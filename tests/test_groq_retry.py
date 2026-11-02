import httpx
import pytest

from landrisk import extract


class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=httpx.Request("POST", "x"), response=self)


OK = FakeResponse(200, {"choices": [{"message": {"content": '{"fields": {"lessor": {"value": "A"}}}'}}]})


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(extract, "GROQ_API_KEY", "test")
    monkeypatch.setattr(extract.time, "sleep", lambda s: None)


def _scripted(monkeypatch, outcomes):
    calls = iter(outcomes)
    def post(*a, **k):
        o = next(calls)
        if isinstance(o, Exception):
            raise o
        return o
    monkeypatch.setattr(extract.httpx, "post", post)


def test_timeouts_and_server_errors_are_retried(monkeypatch, no_sleep):
    _scripted(monkeypatch, [httpx.ReadTimeout("slow"), FakeResponse(503), httpx.ConnectError("down"), OK])
    assert extract.call_groq("text") == {"lessor": {"value": "A"}}


def test_persistent_failure_raises_after_retries(monkeypatch, no_sleep):
    _scripted(monkeypatch, [httpx.ReadTimeout("slow")] * 6)
    with pytest.raises(extract.ExtractionError):
        extract.call_groq("text", retries=6)


def test_client_errors_are_not_retried(monkeypatch, no_sleep):
    _scripted(monkeypatch, [FakeResponse(401)])
    with pytest.raises(httpx.HTTPStatusError):
        extract.call_groq("text")


def test_a_failing_lease_is_skipped_and_the_run_continues(monkeypatch, tmp_path, no_sleep):
    from landrisk import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")
    monkeypatch.setattr(extract, "connect", db.connect)
    monkeypatch.setattr(extract, "init_raw", db.init_raw)
    for name in ("EDG-0001", "EDG-0002"):
        (tmp_path / f"{name}.pdf").write_bytes(b"")
    monkeypatch.setattr(extract, "pdf_text", lambda p: ("short lease text", 1))
    def fake_groq(text, **k):
        if fake_groq.calls == 0:
            fake_groq.calls += 1
            raise extract.ExtractionError("timed out")
        return {"lessor": {"value": "A", "confidence": 0.9, "evidence": "short lease text"}}
    fake_groq.calls = 0
    monkeypatch.setattr(extract, "call_groq", fake_groq)
    with pytest.raises(SystemExit):
        extract.extract_all(provider="groq", pdf_dir=tmp_path)
    import duckdb
    done = duckdb.connect(str(tmp_path / "t.duckdb")).execute(
        "select distinct document_id from raw.lease_extraction_fields").fetchall()
    assert done == [("EDG-0002",)]
