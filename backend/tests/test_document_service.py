"""Local document import: MIME/content sniffing (never trusting the
extension), size/count limits, SHA-256 dedup, DOCX zip-bomb/macro guards,
encrypted-PDF handling, safe filenames, and preview/delete."""

from __future__ import annotations

import io
import zipfile

import docx
import pytest
from sqlalchemy.orm import Session

from app import document_service
from app.config import Settings
from app.models import Domain
from app.models_integrations import Document


def _body_domain(db_session: Session) -> Domain:
    return db_session.query(Domain).filter_by(slug="body").one()


def _valid_docx_bytes(text: str = "Hello from a valid docx.") -> bytes:
    buf = io.BytesIO()
    document = docx.Document()
    document.add_paragraph(text)
    document.save(buf)
    return buf.getvalue()


def test_import_plain_text(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    doc = document_service.import_document(
        db_session, memory_settings, domain_id=domain.id, original_filename="note.txt", data=b"Some plain text content."
    )
    assert doc.status == "ready"
    assert doc.mime_type == "text/plain"
    assert len(doc.chunks) == 1


def test_mime_is_sniffed_from_content_not_extension(db_session: Session, memory_settings: Settings) -> None:
    """A file named *.pdf but containing plain text must be classified by
    its actual bytes, not trusted by extension."""
    domain = _body_domain(db_session)
    doc = document_service.import_document(
        db_session, memory_settings, domain_id=domain.id, original_filename="fake.pdf", data=b"just plain text, not a real pdf"
    )
    assert doc.mime_type == "text/plain"  # sniffed correctly despite the .pdf name


def test_duplicate_content_rejected(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    document_service.import_document(db_session, memory_settings, domain_id=domain.id, original_filename="a.txt", data=b"same content")
    with pytest.raises(document_service.DocumentValidationError):
        document_service.import_document(db_session, memory_settings, domain_id=domain.id, original_filename="b.txt", data=b"same content")


def test_size_limit_enforced(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    oversized = b"x" * (document_service.MAX_FILE_SIZE_BYTES + 1)
    with pytest.raises(document_service.DocumentValidationError):
        document_service.import_document(db_session, memory_settings, domain_id=domain.id, original_filename="big.txt", data=oversized)


def test_valid_docx_imports_successfully(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    doc = document_service.import_document(
        db_session, memory_settings, domain_id=domain.id, original_filename="report.docx", data=_valid_docx_bytes()
    )
    assert doc.status == "ready"
    assert "wordprocessingml" in doc.mime_type
    assert len(doc.chunks) >= 1


def test_docx_with_macro_is_rejected(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    base = _valid_docx_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as src, zipfile.ZipFile(buf, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("word/vbaProject.bin", b"fake macro bytes")

    with pytest.raises(document_service.DocumentValidationError, match="macro"):
        document_service.import_document(
            db_session, memory_settings, domain_id=domain.id, original_filename="macro.docx", data=buf.getvalue()
        )


def test_docx_zip_bomb_like_content_rejected(db_session: Session, memory_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_service, "MAX_DOCX_UNCOMPRESSED_BYTES", 1000)  # force a tiny limit for this test
    domain = _body_domain(db_session)
    doc = document_service.import_document(
        db_session, memory_settings, domain_id=domain.id, original_filename="bomb.docx", data=_valid_docx_bytes("x" * 5000)
    )
    assert doc.status == "unsupported"
    assert "zip bomb" in (doc.error_detail or "").lower()


def test_corrupt_zip_claiming_to_be_docx_rejected(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    with pytest.raises(document_service.DocumentValidationError):
        document_service.import_document(
            db_session, memory_settings, domain_id=domain.id, original_filename="broken.docx", data=b"PK\x03\x04not a real zip"
        )


def test_binary_garbage_rejected(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    with pytest.raises(document_service.DocumentValidationError):
        document_service.import_document(
            db_session, memory_settings, domain_id=domain.id, original_filename="mystery.bin", data=bytes(range(256))
        )


def test_stored_filename_is_safe_and_confined(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    doc = document_service.import_document(
        db_session,
        memory_settings,
        domain_id=domain.id,
        original_filename="../../etc/passwd.txt",
        data=b"path traversal attempt in the filename",
    )
    assert "/" not in doc.stored_relative_path
    assert ".." not in doc.stored_relative_path
    stored_path = (memory_settings.documents_dir / doc.stored_relative_path).resolve()
    assert memory_settings.documents_dir.resolve() in stored_path.parents


def test_unknown_domain_rejected(db_session: Session, memory_settings: Settings) -> None:
    with pytest.raises(document_service.DocumentValidationError):
        document_service.import_document(
            db_session, memory_settings, domain_id="not-a-real-domain", original_filename="a.txt", data=b"x"
        )


def test_permanent_delete_requires_exact_filename(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    doc = document_service.import_document(db_session, memory_settings, domain_id=domain.id, original_filename="delete-me.txt", data=b"content")
    with pytest.raises(document_service.DocumentPermanentDeletionError):
        document_service.permanently_delete_document(db_session, memory_settings, doc.id, confirm_filename="wrong-name.txt")
    assert db_session.get(Document, doc.id) is not None


def test_permanent_delete_removes_document_and_file(db_session: Session, memory_settings: Settings) -> None:
    domain = _body_domain(db_session)
    doc = document_service.import_document(db_session, memory_settings, domain_id=domain.id, original_filename="delete-me.txt", data=b"content")
    stored_path = memory_settings.documents_dir / doc.stored_relative_path
    assert stored_path.exists()

    document_service.permanently_delete_document(db_session, memory_settings, doc.id, confirm_filename="delete-me.txt")
    assert db_session.get(Document, doc.id) is None
    assert not stored_path.exists()

    # A pre-delete rollback backup must have been created.
    pre_delete_dir = memory_settings.backups_dir / "pre_delete"
    assert pre_delete_dir.exists() and any(pre_delete_dir.iterdir())
