from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Claim, EvidenceTier


def create_account(client, email):
    response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "test-password-long-enough"},
    )
    assert response.status_code == 201
    return response.json()


def create_project(client, name="AURORA"):
    response = client.post("/api/projects", json={"name": name})
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


def propose_claim(client, project_id, source_id, claim_text, sensitivity="project"):
    source_response = client.get(f"/api/projects/{project_id}/sources/{source_id}")
    assert source_response.status_code == 200
    span = source_response.json()["spans"][0]
    response = client.post(
        f"/api/projects/{project_id}/claims",
        json={
            "category": "decision",
            "claim_text": claim_text,
            "sensitivity": sensitivity,
            "evidence": [{"source_span_id": span["id"], "quote": span["text"]}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def invite_user(owner, project_id, email, role):
    client = owner.__class__(owner.app)
    create_account(client, email)
    response = owner.post(
        f"/api/projects/{project_id}/members",
        json={"email": email, "role": role},
    )
    assert response.status_code == 201, response.text
    return client


def test_signup_authenticates_and_project_role_is_enforced(client):
    response = client.get("/api/projects")
    assert response.status_code == 401
    user = create_account(client, "owner@example.test")
    assert client.get("/api/auth/me").json() == user
    login = client.post(
        "/api/auth/login",
        json={"email": "OWNER@example.test", "password": "test-password-long-enough"},
    )
    assert login.status_code == 200
    invalid_login = client.post(
        "/api/auth/login",
        json={"email": "owner@example.test", "password": "wrong-password-long"},
    )
    assert invalid_login.status_code == 401

    project = create_project(client)
    assert project["role"] == "owner"
    assert client.get(f"/api/projects/{project['id']}/dashboard").status_code == 200

    member = invite_user(client, project["id"], "member@example.test", "member")
    assert member.get(f"/api/projects/{project['id']}/readiness").status_code == 403
    assert member.get(f"/api/projects/{project['id']}/dashboard").status_code == 200

    outsider = member.__class__(member.app)
    create_account(outsider, "outsider@example.test")
    denied = outsider.get(f"/api/projects/{project['id']}/dashboard")
    assert denied.status_code == 404
    assert denied.json() == {"detail": {"code": "project_not_found"}}


def test_member_acl_covers_private_data_and_privileged_workflows(client):
    create_account(client, "acl-owner@example.test")
    project_id = create_project(client, "ACL verification")["id"]
    public_source = upload_text(
        client,
        project_id,
        "public_status.md",
        b"The public project status is stable.",
    )
    private_source = upload_text(
        client,
        project_id,
        "classified_calibration.md",
        b"PRIVATE_CLASSIFIED_MARKER deployment key remains sealed.",
        sensitivity="restricted",
    )
    public_claim = propose_claim(
        client,
        project_id,
        public_source["id"],
        "The public project status is stable.",
    )
    private_claim = propose_claim(
        client,
        project_id,
        private_source["id"],
        "PRIVATE_CLASSIFIED_MARKER deployment key remains sealed.",
        sensitivity="restricted",
    )
    conflict = client.post(
        f"/api/projects/{project_id}/conflicts",
        json={
            "first_claim_id": public_claim["id"],
            "second_claim_id": private_claim["id"],
            "conflict_type": "private_conflict_marker",
        },
    )
    assert conflict.status_code == 201
    public_gap = client.post(
        f"/api/projects/{project_id}/missing-evidence",
        json={
            "description": "Public release notes are outstanding.",
            "why_it_matters": "The release state needs confirmation.",
        },
    )
    private_gap = client.post(
        f"/api/projects/{project_id}/missing-evidence",
        json={
            "description": "PRIVATE_CLASSIFIED_MARKER restricted gap.",
            "why_it_matters": "A sealed deployment detail remains unconfirmed.",
            "sensitivity": "restricted",
        },
    )
    assert public_gap.status_code == private_gap.status_code == 201

    member = invite_user(client, project_id, "acl-member@example.test", "member")
    sources = member.get(f"/api/projects/{project_id}/sources")
    assert sources.status_code == 200
    assert [source["id"] for source in sources.json()] == [public_source["id"]]
    assert "classified_calibration.md" not in sources.text
    assert member.get(
        f"/api/projects/{project_id}/sources/{private_source['id']}"
    ).status_code == 404

    claims = member.get(f"/api/projects/{project_id}/claims")
    assert claims.status_code == 200
    assert [claim["id"] for claim in claims.json()] == [public_claim["id"]]
    assert "PRIVATE_CLASSIFIED_MARKER" not in claims.text
    assert member.get(
        f"/api/projects/{project_id}/claims/{private_claim['id']}"
    ).status_code == 404
    assert member.get(
        f"/api/projects/{project_id}/search",
        params={"q": "PRIVATE_CLASSIFIED_MARKER"},
    ).json()["results"] == []
    assert member.get(f"/api/projects/{project_id}/conflicts").json() == []
    visible_gaps = member.get(f"/api/projects/{project_id}/missing-evidence")
    assert [item["id"] for item in visible_gaps.json()] == [public_gap.json()["id"]]
    assert "PRIVATE_CLASSIFIED_MARKER" not in visible_gaps.text

    reconstruction = member.post(f"/api/projects/{project_id}/reconstruction")
    assert reconstruction.status_code == 200
    assert reconstruction.json()["processed_span_count"] == 1
    dashboard = member.get(f"/api/projects/{project_id}/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["source_count"] == 1
    assert dashboard.json()["claim_count"] == 1
    assert dashboard.json()["open_conflict_count"] == 0
    assert dashboard.json()["missing_evidence_count"] == 1

    assert member.get(f"/api/projects/{project_id}/readiness").status_code == 403
    assert member.get(f"/api/projects/{project_id}/audit").status_code == 403
    denied_actions = (
        member.post(
            f"/api/projects/{project_id}/sources",
            files={"file": ("restricted.md", b"private upload", "text/markdown")},
            data={"sensitivity": "restricted"},
        ),
        member.post(
            f"/api/projects/{project_id}/claims",
            json={
                "category": "decision",
                "claim_text": "PRIVATE_CLASSIFIED_MARKER unauthorized proposal.",
                "sensitivity": "restricted",
            },
        ),
        member.post(
            f"/api/projects/{project_id}/claims/{private_claim['id']}/review",
            json={"action": "accept"},
        ),
        member.post(
            f"/api/projects/{project_id}/conflicts",
            json={
                "first_claim_id": public_claim["id"],
                "second_claim_id": private_claim["id"],
                "conflict_type": "unauthorized_conflict",
            },
        ),
        member.post(
            f"/api/projects/{project_id}/conflicts/{conflict.json()['id']}/resolve",
            json={"status": "dismissed", "rationale": "Unauthorized resolution."},
        ),
        member.post(
            f"/api/projects/{project_id}/missing-evidence",
            json={
                "description": "Unauthorized restricted gap.",
                "why_it_matters": "This must not be added.",
                "sensitivity": "restricted",
            },
        ),
        member.post(
            f"/api/projects/{project_id}/missing-evidence/{private_gap.json()['id']}/resolve"
        ),
        member.post(f"/api/projects/{project_id}/handovers/approve"),
        member.post(f"/api/projects/{project_id}/demo/aurora"),
        member.post(
            f"/api/projects/{project_id}/members",
            json={"email": "acl-member@example.test", "role": "owner"},
        ),
    )
    assert all(response.status_code == 403 for response in denied_actions)
    assert all("PRIVATE_CLASSIFIED_MARKER" not in response.text for response in denied_actions)

    assert client.post(
        f"/api/projects/{project_id}/conflicts/{conflict.json()['id']}/resolve",
        json={"status": "dismissed", "rationale": "The scopes differ."},
    ).status_code == 200
    for claim in (public_claim, private_claim):
        reviewed = client.post(
            f"/api/projects/{project_id}/claims/{claim['id']}/review",
            json={"action": "accept"},
        )
        assert reviewed.status_code == 200
    version = client.post(f"/api/projects/{project_id}/handovers/approve")
    assert version.status_code == 201
    preview = member.get(
        f"/api/projects/{project_id}/handovers/{version.json()['version']}/preview"
    )
    assert preview.status_code == 200
    assert [claim["id"] for claim in preview.json()["claims"]] == [public_claim["id"]]
    assert preview.json()["redaction"]["withheld_claim_count"] == 1
    assert "PRIVATE_CLASSIFIED_MARKER" not in preview.text
    assert member.post(
        f"/api/projects/{project_id}/handovers/{version.json()['version']}/acknowledgement",
        json={"note": "Not authorized for this role."},
    ).status_code == 403


def test_upload_citations_reviews_conflicts_and_readiness(client, test_engine):
    create_account(client, "reviewer@example.test")
    project = create_project(client)
    project_id = project["id"]
    source = upload_text(
        client,
        project_id,
        "synthetic_decision.md",
        b"The team chose proportional steering for the first robot prototype.",
    )
    assert source["span_count"] == 1

    claim = propose_claim(
        client,
        project_id,
        source["id"],
        "The team chose proportional steering for the first robot prototype.",
    )
    assert claim["evidence_tier"] == "Verified"
    assert claim["evidence"][0]["citation_valid"] is True
    assert claim["evidence"][0]["location"] == "lines 1-1"
    with Session(test_engine) as session:
        stored_tier = session.scalar(
            select(Claim.evidence_tier).where(Claim.id == UUID(claim["id"]))
        )
    assert stored_tier is EvidenceTier.VERIFIED

    invalid = client.post(
        f"/api/projects/{project_id}/claims",
        json={
            "category": "decision",
            "claim_text": "The controller uses machine learning.",
            "evidence": [{
                "source_span_id": claim["evidence"][0]["source_span_id"],
                "quote": "The controller uses machine learning.",
            }],
        },
    )
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": {"code": "quote_not_in_source_span"}}

    accepted = client.post(
        f"/api/projects/{project_id}/claims/{claim['id']}/review",
        json={"action": "accept"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    first_score = client.get(f"/api/projects/{project_id}/readiness").json()
    second_score = client.get(f"/api/projects/{project_id}/readiness").json()
    assert first_score == second_score
    assert first_score["state"] == "draft"
    assert sum(first_score["breakdown"].values()) == first_score["score"]
    assert first_score["breakdown"]["evidence_quality"] == 25

    second_source = upload_text(
        client,
        project_id,
        "synthetic_alternate_decision.md",
        b"The first robot prototype uses PID control.",
    )
    second = propose_claim(
        client,
        project_id,
        second_source["id"],
        "The first robot prototype uses PID control.",
    )
    conflict = client.post(
        f"/api/projects/{project_id}/conflicts",
        json={
            "first_claim_id": claim["id"],
            "second_claim_id": second["id"],
            "conflict_type": "technical_decision",
        },
    )
    assert conflict.status_code == 201
    assert client.get(f"/api/projects/{project_id}/claims").json()[0]["evidence_tier"] == "Conflicting"
    cannot_accept_conflicted_claim = client.post(
        f"/api/projects/{project_id}/claims/{claim['id']}/review",
        json={"action": "accept"},
    )
    assert cannot_accept_conflicted_claim.status_code == 409
    assert cannot_accept_conflicted_claim.json() == {
        "detail": {"code": "claim_has_unresolved_conflict"}
    }
    cannot_edit_conflicted_claim = client.post(
        f"/api/projects/{project_id}/claims/{claim['id']}/review",
        json={"action": "edit", "updated_text": claim["claim_text"]},
    )
    assert cannot_edit_conflicted_claim.status_code == 409
    blocked = client.post(f"/api/projects/{project_id}/handovers/approve")
    assert blocked.status_code == 409
    assert blocked.json() == {"detail": {"code": "unresolved_conflicts_block_approval"}}

    resolved = client.post(
        f"/api/projects/{project_id}/conflicts/{conflict.json()['id']}/resolve",
        json={"status": "accepted_as_ambiguity", "rationale": "The source record does not resolve this disagreement."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "accepted_as_ambiguity"


def test_restricted_source_claim_and_handover_are_filtered_before_return(client):
    create_account(client, "owner@example.test")
    project = create_project(client)
    project_id = project["id"]
    secret_phrase = "Restricted calibration tolerance is 0.18 line-widths."
    private_source = upload_text(
        client,
        project_id,
        "classified_calibration.md",
        secret_phrase.encode(),
        sensitivity="restricted",
    )
    restricted_claim = propose_claim(
        client,
        project_id,
        private_source["id"],
        secret_phrase,
        sensitivity="restricted",
    )
    public_source = upload_text(
        client,
        project_id,
        "synthetic_objective.md",
        b"The synthetic project is building a line-following robot.",
    )
    public_claim = propose_claim(
        client,
        project_id,
        public_source["id"],
        "The synthetic project is building a line-following robot.",
    )
    propagated_private_claim = propose_claim(
        client,
        project_id,
        private_source["id"],
        secret_phrase,
        sensitivity="project",
    )
    assert propagated_private_claim["sensitivity"] == "restricted"
    hidden_conflict = client.post(
        f"/api/projects/{project_id}/conflicts",
        json={
            "first_claim_id": public_claim["id"],
            "second_claim_id": restricted_claim["id"],
            "conflict_type": "restricted_test_only",
        },
    )
    assert hidden_conflict.status_code == 201

    reviewer = invite_user(client, project_id, "reviewer@example.test", "reviewer")
    assert len(reviewer.get(f"/api/projects/{project_id}/claims").json()) == 3
    downgraded = client.post(
        f"/api/projects/{project_id}/members",
        json={"email": "reviewer@example.test", "role": "member"},
    )
    assert downgraded.status_code == 201
    assert len(reviewer.get(f"/api/projects/{project_id}/claims").json()) == 1
    assert reviewer.get(
        f"/api/projects/{project_id}/sources/{private_source['id']}"
    ).status_code == 404

    recipient = invite_user(client, project_id, "incoming@example.test", "incoming_lead")
    assert recipient.get(f"/api/projects/{project_id}/sources").json()[0]["sensitivity"] == "project"
    sources = recipient.get(f"/api/projects/{project_id}/sources").json()
    assert all(item["filename"] != "classified_calibration.md" for item in sources)
    hidden_source = recipient.get(
        f"/api/projects/{project_id}/sources/{private_source['id']}"
    )
    assert hidden_source.status_code == 404
    assert "classified_calibration.md" not in hidden_source.text
    assert secret_phrase not in hidden_source.text

    claims = recipient.get(f"/api/projects/{project_id}/claims").json()
    assert [claim["id"] for claim in claims] == [public_claim["id"]]
    searched = recipient.get(
        f"/api/projects/{project_id}/claims",
        params={"search": "Restricted calibration tolerance"},
    )
    assert searched.json() == []
    source_search = recipient.get(
        f"/api/projects/{project_id}/search",
        params={"q": "Restricted calibration tolerance"},
    )
    assert source_search.json()["results"] == []
    hidden_claim = recipient.get(
        f"/api/projects/{project_id}/claims/{restricted_claim['id']}"
    )
    assert hidden_claim.status_code == 404
    assert secret_phrase not in hidden_claim.text
    assert "classified_calibration.md" not in hidden_claim.text
    dashboard = recipient.get(f"/api/projects/{project_id}/dashboard").json()
    assert dashboard["source_count"] == 1
    assert dashboard["claim_count"] == 1
    assert dashboard["source_span_count"] == 1
    assert dashboard["open_conflict_count"] == 0
    assert recipient.get(f"/api/projects/{project_id}/conflicts").json() == []

    public_gap = client.post(
        f"/api/projects/{project_id}/missing-evidence",
        json={
            "description": "Public project validation remains incomplete.",
            "why_it_matters": "The release state is not confirmed.",
            "sensitivity": "project",
        },
    )
    private_gap = client.post(
        f"/api/projects/{project_id}/missing-evidence",
        json={
            "description": "Private gap label secretphrase must not leak.",
            "why_it_matters": "Restricted test measurements are pending.",
            "suggested_question": "What is the sealed test threshold?",
            "sensitivity": "restricted",
        },
    )
    assert public_gap.status_code == 201
    assert private_gap.status_code == 201
    visible_gaps = recipient.get(f"/api/projects/{project_id}/missing-evidence")
    assert len(visible_gaps.json()) == 1
    assert visible_gaps.json()[0]["description"] == "Public project validation remains incomplete."
    assert "secretphrase" not in visible_gaps.text
    dashboard = recipient.get(f"/api/projects/{project_id}/dashboard").json()
    assert dashboard["missing_evidence_count"] == 1
    member_create_private_gap = recipient.post(
        f"/api/projects/{project_id}/missing-evidence",
        json={
            "description": "Should not be created by a member.",
            "why_it_matters": "The project data is private.",
            "sensitivity": "restricted",
        },
    )
    assert member_create_private_gap.status_code == 403

    resolved = client.post(
        f"/api/projects/{project_id}/conflicts/{hidden_conflict.json()['id']}/resolve",
        json={"status": "dismissed", "rationale": "These claims refer to different test contexts."},
    )
    assert resolved.status_code == 200
    for claim in (restricted_claim, propagated_private_claim, public_claim):
        reviewed = client.post(
            f"/api/projects/{project_id}/claims/{claim['id']}/review",
            json={"action": "accept"},
        )
        assert reviewed.status_code == 200
    version = client.post(f"/api/projects/{project_id}/handovers/approve")
    assert version.status_code == 201
    listed_versions = recipient.get(f"/api/projects/{project_id}/handovers").json()
    assert listed_versions[0]["claim_count"] == 1
    assert "classified_calibration.md" not in str(listed_versions)

    preview = recipient.get(
        f"/api/projects/{project_id}/handovers/{version.json()['version']}/preview"
    )
    assert preview.status_code == 200
    rendered = preview.json()
    assert [claim["id"] for claim in rendered["claims"]] == [public_claim["id"]]
    assert rendered["redaction"]["withheld_claim_count"] == 2
    assert rendered["redaction"]["withheld_evidence_count"] == 2
    serialized = preview.text
    assert secret_phrase not in serialized
    assert "classified_calibration.md" not in serialized
    assert restricted_claim["id"] not in serialized
    assert propagated_private_claim["id"] not in serialized

    acknowledgement = recipient.post(
        f"/api/projects/{project_id}/handovers/{version.json()['version']}/acknowledgement",
        json={"note": "Received and ready to continue."},
    )
    assert acknowledgement.status_code == 201
    assert "does not imply agreement" in acknowledgement.json()["meaning"]


def test_reconstruction_is_deterministic_idempotent_and_acl_filtered(client):
    create_account(client, "owner@example.test")
    project = create_project(client)
    project_id = project["id"]
    source = upload_text(
        client,
        project_id,
        "labeled_synthetic_notes.md",
        (
            b"Owner: Riley owns test calibration.\n"
            b"Decision: the team selected the reflectance array.\n"
            b"Risk: battery voltage sag may restart the controller.\n"
            b"Open question: the track reflectance is not measured.\n"
        ),
    )
    hidden = propose_claim(
        client,
        project_id,
        source["id"],
        "Owner: Riley owns test calibration.",
        sensitivity="restricted",
    )
    upload_text(
        client,
        project_id,
        "synthetic_restricted_notes.md",
        b"Risk: restricted unreleased safety threshold.",
        sensitivity="restricted",
    )

    member = invite_user(client, project_id, "member@example.test", "member")
    first = member.post(f"/api/projects/{project_id}/reconstruction")
    assert first.status_code == 200
    result = first.json()
    assert result["mode"] == "deterministic_rule_based"
    assert result["llm_used"] is False
    assert result["processed_span_count"] == 4
    assert result["created_claim_count"] == 4
    assert result["skipped_span_count"] == 0
    assert "restricted" not in first.text.lower()
    assert hidden["id"] not in str(member.get(f"/api/projects/{project_id}/claims").json())

    repeated = member.post(f"/api/projects/{project_id}/reconstruction")
    assert repeated.json()["created_claim_count"] == 0
    assert repeated.json()["skipped_span_count"] == 4
    member_claims = member.get(f"/api/projects/{project_id}/claims").json()
    assert {claim["category"] for claim in member_claims} == {
        "owner", "decision", "risk", "open_question",
    }

    source_search = member.get(
        f"/api/projects/{project_id}/search",
        params={"q": "restricted safety threshold"},
    )
    assert source_search.json()["results"] == []
