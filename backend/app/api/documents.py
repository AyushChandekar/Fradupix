"""
Document API Routes - Vectorless RAG (SRS Section 6.1, FR-800)
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Invoice
from app.schemas import (
    DocumentQueryRequest, DocumentQueryResponse, DocumentQueryResult,
    DocumentTOCResponse, TOCEntry,
)
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])


@router.post("/query", response_model=DocumentQueryResponse)
def query_document(
    request: DocumentQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    SRS FR-806: Vectorless RAG query.
    Returns exact page/section locations with extracted content snippets.
    """
    from app.services.rag_service import vectorless_rag_service

    rag_response = vectorless_rag_service.query_document(
        query=request.query,
        document_id=request.document_id,
        db=db,
        user_id=current_user.id,
    )

    # rag_response is a dict: {"query", "document_id", "total_matches", "results": [...]}
    raw_results = rag_response.get("results", [])

    query_results = []
    for r in raw_results:
        query_results.append(DocumentQueryResult(
            document_id=uuid.UUID(rag_response["document_id"]),
            page_number=r["page_number"],
            section_heading=r.get("section_heading"),
            content_preview=r.get("content_snippet", ""),
            relevance_score=r.get("relevance_score", 0),
        ))

    return DocumentQueryResponse(
        query=request.query,
        results=query_results,
        total_results=len(query_results),
    )


@router.get("/{document_id}/toc", response_model=DocumentTOCResponse)
def get_document_toc(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    SRS FR-802: Retrieve auto-generated table of contents for a document.
    """
    invoice = db.query(Invoice).filter(Invoice.id == document_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Document not found")

    from app.services.rag_service import vectorless_rag_service

    # get_toc returns a dict: {"document_id", "total_entries", "entries": [...dicts...]}
    toc_response = vectorless_rag_service.get_toc(document_id, db)
    raw_entries = toc_response.get("entries", [])

    toc_entries = [
        TOCEntry(
            id=uuid.UUID(e["id"]),
            entry_title=e["entry_title"],
            page_number=e["page_number"],
            level=e["level"],
        )
        for e in raw_entries
    ]

    return DocumentTOCResponse(
        document_id=document_id,
        entries=toc_entries,
    )
