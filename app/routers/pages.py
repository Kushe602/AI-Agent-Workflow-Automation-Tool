"""Public pages: landing for anonymous visitors, dashboard for signed-in users."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_optional_user
from app.models import Run, User
from app.web import templates

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    if user is None:
        return templates.TemplateResponse(request, "landing.html", {})
    result = await db.execute(
        select(Run).where(Run.owner_id == user.id).order_by(Run.created_at.desc()).limit(50)
    )
    runs = result.scalars().all()
    return templates.TemplateResponse(request, "index.html", {"user": user, "runs": runs})


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
