import json
import urllib.request
from types import SimpleNamespace

from pydantic import SecretStr

from app.openrouter import (
    ClaimCandidate,
    OpenRouterError,
    SourceLine,
    extract_claim_candidates,
)
from app.routes import reconstruction


def create_account(client, email):
    response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "test-password-long-enough"},
    )
    assert response.status_code == 201
    return response.json()


def create_project(client):
    response = client.post("/api/projects", json={"name": "OpenRouter test"})
    assert response.status_code == 201
    return response.json()


def upload_text(client, project_id, filename, content, sensitivity="project"):
    response = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": (filename, content, "text/markdown")},
        data={"sensitivity": sensitivity},
    )
    assert response.status_code == 201, response.text
    return response.json()


def invite_user(owner, project_id, email, role):
    member = owner.__class__(owner.app)
    create_account(member, email)
    response = owner.post(
        f"/api/projects/{project_id}/members",
        json={"email": email, "role": role},
    )
    assert response.status_code == 201
    return member


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        del exception_type, exception, traceback
        return None

    def read(self, limit: int) -> bytes:
        del limit
        return self.body


def test_openrouter_request_parses_structured_candidates_without_sending_source_identity(monkeypatch):
    candidate = {
        "source_ref": 0,
        "claim_title": "Selected field test configuration",
        "exact_quote": "Decision: the team selected the left drive configuration.",
        "source_line_start": 17,
        "source_line_end": 17,
        "category": "Project Decision",
        "confidence_reason": "Quote copied from line 17.",
        "has_conflict": False,
    }
    response_body = json.dumps(
        {"choices": [{"message": {"content": json.dumps({"claim_candidates": [candidate]})}}]}
    ).encode()
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(response_body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    lines = [
        SourceLine(
            source_ref=0,
            line_start=17,
            line_end=17,
            text="Decision: the team selected the left drive configuration.",
        )
    ]
    result = extract_claim_candidates(lines, "test-openrouter-key", "mock/provider-model")

    assert result[0].exact_quote == lines[0].text
    assert captured["timeout"] == 45
    assert captured["request"].full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["request"].get_header("Authorization") == "Bearer test-openrouter-key"
    request_payload = json.loads(captured["request"].data)
    assert request_payload["model"] == "mock/provider-model"
    assert request_payload["response_format"] == {"type": "json_object"}
    request_text = captured["request"].data.decode()
    assert "public_decision.md" not in request_text
    assert "test-openrouter-key" not in repr(result)


def test_openrouter_invalid_structured_data_is_an_explicit_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        del request, timeout
        return FakeResponse(b'{"choices":[]}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    try:
        extract_claim_candidates(
            [SourceLine(source_ref=0, line_start=1, line_end=1, text="A factual source line.")],
            "test-key",
            "mock/provider-model",
        )
    except OpenRouterError as error:
        assert "invalid structured data" in str(error)
    else:
        raise AssertionError("Invalid provider content must not silently fall back.")


def test_reconstruction_persists_only_exact_visible_provider_citations(client, monkeypatch):
    create_account(client, "openrouter-owner@example.test")
    project_id = create_project(client)["id"]
    public = upload_text(
        client,
        project_id,
        "public_decision.md",
        b"Decision: the team selected the left drive configuration.",
    )
    upload_text(
        client,
        project_id,
        "restricted.md",
        b"Decision: PRIVATE_TEST_SECRET must remain restricted.",
        sensitivity="restricted",
    )
    member = invite_user(client, project_id, "openrouter-member@example.test", "member")
    provider_candidates = [
        ClaimCandidate(
            source_ref=0,
            claim_title="Selected field configuration",
            exact_quote="Decision: the team selected the left drive configuration.",
            source_line_start=1,
            source_line_end=1,
            category="Project Decision",
            confidence_reason="Provider reasons are replaced with a deterministic citation.",
            has_conflict=True,
        ),
        ClaimCandidate(
            source_ref=0,
            claim_title="Invented claim",
            exact_quote="The team deployed the robot.",
            source_line_start=1,
            source_line_end=1,
            category="Project Decision",
            confidence_reason="Invented.",
            has_conflict=False,
        ),
        ClaimCandidate(
            source_ref=4,
            claim_title="Unrecognized source",
            exact_quote="Decision: hidden data.",
            source_line_start=1,
            source_line_end=1,
            category="Project Decision",
            confidence_reason="Unrecognized source.",
            has_conflict=False,
        ),
    ]

    def fake_extract(lines, api_key, model):
        assert api_key == "unit-test-openrouter-key"
        assert model == "mock/provider-model"
        assert len(lines) == 1
        assert lines[0].text == "Decision: the team selected the left drive configuration."
        assert lines[0].source_ref == 0
        return provider_candidates

    monkeypatch.setattr(
        reconstruction,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key=SecretStr("unit-test-openrouter-key"),
            openrouter_model="mock/provider-model",
        ),
    )
    monkeypatch.setattr(reconstruction, "extract_claim_candidates", fake_extract)
    response = member.post(f"/api/projects/{project_id}/reconstruction")

    assert response.status_code == 200
    result = response.json()
    assert result["llm_used"] is True
    assert result["mode"] == "openrouter_claim_extraction"
    assert result["created_claim_count"] == 1
    assert result["rejected_candidate_count"] == 2
    assert result["omitted_span_count"] == 0
    assert result["candidates"] == [
        {
            "claim_title": "Selected field configuration",
            "exact_quote": "Decision: the team selected the left drive configuration.",
            "source_line_start": 1,
            "source_line_end": 1,
            "category": "Project Decision",
            "confidence_reason": "Exact quote verified in public_decision.md, line 1.",
            "has_conflict": True,
        }
    ]
    claims = member.get(f"/api/projects/{project_id}/claims")
    assert claims.status_code == 200
    assert [claim["claim_text"] for claim in claims.json()] == [
        "Decision: the team selected the left drive configuration."
    ]
    evidence = claims.json()[0]["evidence"][0]
    assert evidence["source_id"] == public["id"]
    assert evidence["citation_valid"] is True
    assert "PRIVATE_TEST_SECRET" not in response.text


def test_openrouter_provider_failure_does_not_create_deterministic_claims(
    client,
    test_engine,
    monkeypatch,
):
    create_account(client, "openrouter-failure@example.test")
    project_id = create_project(client)["id"]
    upload_text(
        client,
        project_id,
        "decision.md",
        b"Decision: the field-test configuration is ready.",
    )
    monkeypatch.setattr(
        reconstruction,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key=SecretStr("unit-test-openrouter-key"),
            openrouter_model="mock/provider-model",
        ),
    )

    def fail_provider(source_lines, api_key, model):
        del source_lines, api_key, model
        raise OpenRouterError("The mock provider failed.")

    monkeypatch.setattr(reconstruction, "extract_claim_candidates", fail_provider)
    response = client.post(f"/api/projects/{project_id}/reconstruction")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "claim_extraction_provider_error"
    assert response.json()["detail"]["message"] == "The mock provider failed."
    assert "unit-test-openrouter-key" not in response.text
    with test_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM claims").scalar_one() == 0
        assert connection.exec_driver_sql("SELECT count(*) FROM claim_evidence").scalar_one() == 0
