"""Phase 9: explicit browser upload/import of local documents only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import document_service
from app.config import Settings, get_settings
from app.deps import get_db
from app.document_fts_service import rebuild_document_fts
from app.schemas_integrations import DocumentChunkRead, DocumentDeleteRequest, DocumentRead, DocumentWithChunks

router = APIRouter(tags=["documents"])


def _document_to_read(document) -> DocumentRead:
    return DocumentRead(
        id=document.id,
        domain_id=document.domain_id,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        sha256=document.sha256,
        size_bytes=document.size_bytes,
        page_count=document.page_count,
        status=document.status,
        error_detail=document.error_detail,
        chunk_count=len(document.chunks),
        created_at=document.created_at,
    )


@router.post("/api/documents", response_model=DocumentRead, status_code=201)
async def upload_document(
    domain_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentRead:
    data = await file.read()
    try:
        document = document_service.import_document(
            db, settings, domain_id=domain_id, original_filename=file.filename or "upload", data=data
        )
    except document_service.DocumentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _document_to_read(document)


@router.get("/api/documents", response_model=list[DocumentRead])
def list_documents(domain_id: str | None = None, db: Session = Depends(get_db)) -> list[DocumentRead]:
    documents = document_service.list_documents(db, domain_id=domain_id)
    return [_document_to_read(d) for d in documents]


@router.get("/api/documents/{document_id}", response_model=DocumentWithChunks)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentWithChunks:
    try:
        document = document_service.get_document_or_404(db, document_id)
    except document_service.DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentWithChunks(
        document=_document_to_read(document),
        chunks=[
            DocumentChunkRead(id=c.id, chunk_index=c.chunk_index, page_number=c.page_number, content=c.content)
            for c in document.chunks
        ],
    )


@router.post("/api/documents/{document_id}/delete", status_code=204, response_model=None)
def delete_document(
    document_id: str, payload: DocumentDeleteRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> None:
    try:
        document_service.permanently_delete_document(db, settings, document_id, confirm_filename=payload.confirm_filename)
    except document_service.DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")
    except document_service.DocumentPermanentDeletionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/documents-index/rebuild")
def rebuild_index(db: Session = Depends(get_db)) -> dict:
    count = rebuild_document_fts(db)
    return {"indexed_count": count}
