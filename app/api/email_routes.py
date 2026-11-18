"""Dedicated REST API routes for Email drafting, approval, sending, and history tracking."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.agents.email_agent import EmailAgent
from app.api.auth import require_user
from app.auth.schemas import AuthUser
from app.config import Settings, get_settings
from app.database.connection import Database
from app.llm.service import LLMService

logger = logging.getLogger(__name__)

email_router = APIRouter(prefix="/api/email", tags=["email"])

CurrentUserDep = Annotated[AuthUser, Depends(require_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available. Please verify connection and configuration.",
        )
    return database


def get_email_agent(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
    settings: SettingsDep,
) -> EmailAgent:
    llm: LLMService | None = getattr(request.app.state, "llm_service", None)
    return EmailAgent(database=database, settings=settings, llm_service=llm)


class DraftEmailRequest(BaseModel):
    prompt: str | None = Field(default=None, description="Natural language prompt describing what to email.")
    to: list[str] | None = Field(default=None, description="List of recipient email addresses.")
    subject: str | None = Field(default=None, description="Subject line for the email.")
    body: str | None = Field(default=None, description="Plain text email body.")
    body_html: str | None = Field(default=None, description="Optional rich HTML body.")
    cc: list[str] | None = Field(default=None, description="CC recipients.")
    bcc: list[str] | None = Field(default=None, description="BCC recipients.")


class SendEmailRequest(BaseModel):
    operation_id: str | None = Field(default=None, description="Optional unique client idempotency token.")


class RejectEmailRequest(BaseModel):
    reason: str = Field(default="", description="Reason for rejection.")


@email_router.post("/draft", status_code=status.HTTP_201_CREATED)
async def create_email_draft(
    payload: DraftEmailRequest,
    current_user: CurrentUserDep,
    agent: Annotated[EmailAgent, Depends(get_email_agent)],
) -> dict[str, Any]:
    """Parse instructions and create an email draft with status 'pending_approval'."""
    try:
        record = await agent.draft_email(
            user_id=current_user.id,
            prompt=payload.prompt,
            to=payload.to,
            subject=payload.subject,
            body=payload.body,
            body_html=payload.body_html,
            cc=payload.cc,
            bcc=payload.bcc,
        )
        return record.to_dict()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to create email draft: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@email_router.post("/{email_id}/approve")
async def approve_email_draft(
    email_id: str,
    current_user: CurrentUserDep,
    agent: Annotated[EmailAgent, Depends(get_email_agent)],
) -> dict[str, Any]:
    """Approve an email draft before delivery."""
    try:
        record = agent.approve_email(email_id=email_id, user_id=current_user.id)
        return record.to_dict()
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@email_router.post("/{email_id}/reject")
async def reject_email_draft(
    email_id: str,
    payload: RejectEmailRequest,
    current_user: CurrentUserDep,
    agent: Annotated[EmailAgent, Depends(get_email_agent)],
) -> dict[str, Any]:
    """Reject an email draft."""
    try:
        record = agent.reject_email(email_id=email_id, user_id=current_user.id, reason=payload.reason)
        return record.to_dict()
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@email_router.post("/{email_id}/send")
async def send_approved_email(
    email_id: str,
    payload: SendEmailRequest | None = None,
    current_user: CurrentUserDep = None,  # type: ignore[assignment]
    agent: Annotated[EmailAgent, Depends(get_email_agent)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Send an approved email via Gmail API (or outbox if EMAIL_MODE=outbox)."""
    op_id = payload.operation_id if payload else None
    try:
        record = await agent.send_email(email_id=email_id, user_id=current_user.id, operation_id=op_id)
        return record.to_dict()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Send execution error: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@email_router.get("/history")
async def get_email_history(
    current_user: CurrentUserDep,
    agent: Annotated[EmailAgent, Depends(get_email_agent)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    """Retrieve email sending history and status for current user."""
    records = agent.get_history(user_id=current_user.id, limit=limit)
    return [r.to_dict() for r in records]


@email_router.get("/{email_id}")
async def get_email_details(
    email_id: str,
    current_user: CurrentUserDep,
    agent: Annotated[EmailAgent, Depends(get_email_agent)],
) -> dict[str, Any]:
    """Retrieve details and status for a specific email."""
    record = agent.get_record(email_id=email_id, user_id=current_user.id)
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Email '{email_id}' not found.")
    return record.to_dict()
