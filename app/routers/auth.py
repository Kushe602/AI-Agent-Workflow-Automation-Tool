"""Registration, login, and logout — form posts that set an httpOnly JWT cookie."""
from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.security import COOKIE_NAME, create_access_token, hash_password, verify_password
from app.web import templates

router = APIRouter(tags=["auth"])
_COOKIE_MAX_AGE = 7 * 24 * 3600


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_access_token(user_id),
        httponly=True,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {})


@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    email = email.strip().lower()
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Password must be at least 8 characters.", "email": email},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "That email is already registered.", "email": email},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user = User(email=email, hashed_password=hash_password(password))
    db.add(user)
    await db.commit()
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, user.id)
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password.", "email": email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, user.id)
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response
