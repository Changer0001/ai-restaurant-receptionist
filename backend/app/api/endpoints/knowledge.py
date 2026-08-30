"""Restaurant knowledge-base (RAG document) endpoints."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_restaurant_access, require_restaurant_roles
from app.core.config import settings
from app.db.models import User, UserRoleEnum
from app.db.session import get_db_session
from app.providers.embedding import get_embedding_provider
from app.providers.embedding.base import EmbeddingProvider
from app.rag.vector_db import VectorDB, get_vector_db
from app.schemas.knowledge import KnowledgeDocumentRead
from app.services import knowledge_service

router = APIRouter()

_EDITOR_ROLES = (UserRoleEnum.RESTAURANT_OWNER, UserRoleEnum.RESTAURANT_MANAGER)


@router.get("/{restaurant_id}/knowledge", response_model=list[KnowledgeDocumentRead])
async def list_knowledge_documents(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_access),
):
    return await knowledge_service.list_documents(db, restaurant_id)


@router.post("/{restaurant_id}/knowledge/upload", response_model=KnowledgeDocumentRead, status_code=201)
async def upload_knowledge_document(
    restaurant_id: str,
    file: UploadFile = File(...),
    title: str = Form(...),
    document_type: str = Form(default="general"),
    source: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db_session),
    vector_db: VectorDB = Depends(get_vector_db),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
    _: User = Depends(require_restaurant_roles(*_EDITOR_ROLES)),
):
    """
    Upload a plain-text knowledge document (.txt, .md — UTF-8). Richer
    formats (PDF, DOCX) are not parsed in this MVP; see docs/roadmap.md.
    """
    raw = await file.read()
    if len(raw) > settings.MAX_KNOWLEDGE_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.MAX_KNOWLEDGE_UPLOAD_BYTES} byte limit",
        )

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be UTF-8 encoded plain text (e.g. .txt, .md)",
        ) from exc

    return await knowledge_service.create_document(
        db, vector_db, embedder, restaurant_id, title, content, document_type, source
    )


@router.delete("/{restaurant_id}/knowledge/{document_id}", status_code=204)
async def delete_knowledge_document(
    restaurant_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db_session),
    vector_db: VectorDB = Depends(get_vector_db),
    _: User = Depends(require_restaurant_roles(*_EDITOR_ROLES)),
):
    await knowledge_service.delete_document(db, vector_db, restaurant_id, document_id)


@router.post("/{restaurant_id}/knowledge/{document_id}/reindex", response_model=KnowledgeDocumentRead)
async def reindex_knowledge_document(
    restaurant_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db_session),
    vector_db: VectorDB = Depends(get_vector_db),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
    _: User = Depends(require_restaurant_roles(*_EDITOR_ROLES)),
):
    return await knowledge_service.reindex_document(db, vector_db, embedder, restaurant_id, document_id)
