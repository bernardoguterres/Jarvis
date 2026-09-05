"""Imported documents and normalized integration caches survive a full
backend restart."""

from __future__ import annotations


def test_document_survives_restart(restart_client_factory) -> None:
    client1 = restart_client_factory()
    body_id = next(d["id"] for d in client1.get("/api/domains").json() if d["slug"] == "body")

    upload_resp = client1.post(
        "/api/documents", data={"domain_id": body_id}, files={"file": ("restart-test.txt", b"Persist across restart.", "text/plain")}
    )
    document_id = upload_resp.json()["id"]

    client2 = restart_client_factory()
    detail_resp = client2.get(f"/api/documents/{document_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["document"]["status"] == "ready"
    assert len(detail_resp.json()["chunks"]) == 1
