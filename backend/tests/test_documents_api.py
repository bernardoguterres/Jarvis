from __future__ import annotations

from fastapi.testclient import TestClient


def _domain_id(client: TestClient, slug: str) -> str:
    domains = client.get("/api/domains").json()
    return next(d["id"] for d in domains if d["slug"] == slug)


def test_upload_list_get_delete_document(client: TestClient) -> None:
    body_id = _domain_id(client, "body")

    upload_resp = client.post(
        "/api/documents",
        data={"domain_id": body_id},
        files={"file": ("note.txt", b"Some knee history notes.", "text/plain")},
    )
    assert upload_resp.status_code == 201
    document = upload_resp.json()
    assert document["status"] == "ready"
    assert document["chunk_count"] == 1

    list_resp = client.get("/api/documents", params={"domain_id": body_id})
    assert list_resp.status_code == 200
    assert any(d["id"] == document["id"] for d in list_resp.json())

    detail_resp = client.get(f"/api/documents/{document['id']}")
    assert detail_resp.status_code == 200
    assert len(detail_resp.json()["chunks"]) == 1

    wrong_confirm = client.post(f"/api/documents/{document['id']}/delete", json={"confirm_filename": "wrong.txt"})
    assert wrong_confirm.status_code == 400

    delete_resp = client.post(f"/api/documents/{document['id']}/delete", json={"confirm_filename": "note.txt"})
    assert delete_resp.status_code == 204

    missing_resp = client.get(f"/api/documents/{document['id']}")
    assert missing_resp.status_code == 404


def test_upload_rejects_duplicate_over_http(client: TestClient) -> None:
    body_id = _domain_id(client, "body")
    client.post("/api/documents", data={"domain_id": body_id}, files={"file": ("a.txt", b"duplicate content", "text/plain")})
    resp = client.post("/api/documents", data={"domain_id": body_id}, files={"file": ("b.txt", b"duplicate content", "text/plain")})
    assert resp.status_code == 400
