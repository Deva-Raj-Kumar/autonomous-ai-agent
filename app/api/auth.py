"""Authentication endpoints and the dependencies that protect every other endpoint.

How a protected request works:
  1. The client sends   Authorization: Bearer <access token>
  2. get_current_user   verifies the token's signature and expiry (no DB needed for that),
                        then loads the user: a deactivated account is refused at once.
  3. require_user       binds the user to this request (app/auth/context.py), so every
                        store reads and writes only that user's data.
main.py attaches require_user to whole routers, so no endpoint can forget it.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.auth.context import bind_user
from app.auth.schemas import AuthUser, RefreshRequest, RegisterRequest, TokenPair
from app.auth.security import InvalidTokenError, decode_access_token, password_problem
from app.auth.service import AuthService, EmailAlreadyRegistered, RefreshTokenReused, UserDeactivated
from app.auth.throttle import LoginThrottle
from app.config import Settings, get_settings

auth_router = APIRouter(prefix="/auth", tags=["auth"])

# tokenUrl tells Swagger UI (/docs) where its "Authorize" button logs in.
# auto_error=False: we raise our own 401 with a consistent message.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}  # RFC 6750: tells clients HOW to authenticate


def _unauthorized(detail: str = "Not authenticated.") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers=_UNAUTHORIZED)


def get_auth_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Accounts need a working database (check DATABASE_URL and run: alembic upgrade head).",
        )
    return service


def get_login_throttle(request: Request) -> LoginThrottle:
    return request.app.state.login_throttle


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    service: AuthServiceDep, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> AuthUser:
    if not token:
        raise _unauthorized()
    try:
        user_id = decode_access_token(token, service.config)
    except InvalidTokenError:
        raise _unauthorized("Invalid or expired token.") from None
    user = await service.get_active_user(user_id)
    if user is None:  # deleted or deactivated since the token was issued
        raise _unauthorized("Invalid or expired token.")
    return user


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]


async def require_user(user: CurrentUser) -> AuthUser:
    """Router-level guard. MUST be `async def`: a sync dependency runs in a worker thread,
    and a ContextVar set there would not be visible to the endpoint."""
    bind_user(user.id)
    return user


async def require_admin(user: Annotated[AuthUser, Depends(require_user)]) -> AuthUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin only.")
    return user


# ------------------------------------------------------------------ endpoints
@auth_router.post("/register", response_model=AuthUser, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, service: AuthServiceDep, settings: Annotated[Settings, Depends(get_settings)]
) -> AuthUser:
    """Create an account. Passwords: 10-128 characters, not an obvious one."""
    if not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Registration is closed.")
    try:
        return await service.register(str(body.email), body.username, body.password)
    except EmailAlreadyRegistered:
        # 409 does reveal that the email has an account. Accepted here (a friendlier
        # sign-up); the alternative is "check your inbox" flows for every outcome.
        raise HTTPException(status.HTTP_409_CONFLICT, detail="An account with this email already exists.") from None


LoginForm = Annotated[OAuth2PasswordRequestForm, Depends()]
ThrottleDep = Annotated[LoginThrottle, Depends(get_login_throttle)]


async def _check_password(request: Request, form: OAuth2PasswordRequestForm, service: AuthService,
                          throttle: LoginThrottle) -> AuthUser:
    """Shared by both login styles: throttle, verify, same error for every failure."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"{form.username.strip().lower()}|{client_ip}"
    wait = throttle.retry_after(key)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed logins. Try again later.",
            headers={"Retry-After": str(wait)},
        )
    user = await service.authenticate(form.username, form.password[:1024])
    if user is None:
        throttle.record_failure(key)
        raise _unauthorized("Incorrect email or password.")  # never say which one
    throttle.reset(key)
    return user


@auth_router.post("/login", response_model=TokenPair)
async def login(request: Request, form: LoginForm, service: AuthServiceDep, throttle: ThrottleDep) -> TokenPair:
    """OAuth2 password flow (form fields `username` = your EMAIL, and `password`).
    Returns a short-lived access token and a refresh token (for scripts and /docs)."""
    user = await _check_password(request, form, service, throttle)
    return await service.issue_tokens(user.id)


@auth_router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, service: AuthServiceDep) -> TokenPair:
    """Swap a refresh token for a NEW pair. The old refresh token stops working."""
    try:
        return await service.refresh(body.refresh_token)
    except RefreshTokenReused:
        raise _unauthorized("Refresh token reuse detected: all sessions of this login were ended.") from None
    except InvalidTokenError:
        raise _unauthorized("Invalid or expired refresh token.") from None


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, service: AuthServiceDep) -> Response:
    """End this login: its refresh tokens are revoked. (Access tokens are stateless and
    simply expire within minutes: the reason they are short-lived.)"""
    await service.logout(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.get("/me", response_model=AuthUser)
async def me(user: Annotated[AuthUser, Depends(require_user)]) -> AuthUser:
    return user


# ------------------------------------------------------- browser sessions (Phase 13)
# Browsers use these instead. The refresh token travels ONLY in a cookie that page
# JavaScript can't read (httpOnly), so injected script (XSS) can't steal the long-lived
# token. The short-lived access token is returned in the body and kept in memory.
#   SameSite=Strict  -> the browser never attaches it to requests started by other sites
#                       (no cross-site request forgery of /refresh or /logout).
#   Path             -> sent ONLY to these endpoints, not with every API call.
#   Secure           -> HTTPS only, in production (local development runs on http).
REFRESH_COOKIE = "refresh_token"
SESSION_COOKIE_PATH = "/auth/session"


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - a scheme name, not a secret
    expires_in: int


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE, token, max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True, samesite="strict", secure=settings.environment == "production",
        path=SESSION_COOKIE_PATH,
    )


def _session_ended(detail: str) -> JSONResponse:
    """401 that ALSO deletes the cookie (an HTTPException would drop cookie changes)."""
    response = JSONResponse({"detail": detail}, status_code=401, headers=_UNAUTHORIZED)
    response.delete_cookie(REFRESH_COOKIE, path=SESSION_COOKIE_PATH)
    return response


SettingsDep = Annotated[Settings, Depends(get_settings)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


@auth_router.post("/session", response_model=AccessToken)
async def start_session(
    request: Request, response: Response, form: LoginForm, service: AuthServiceDep,
    throttle: ThrottleDep, settings: SettingsDep,
) -> AccessToken:
    """Browser login: access token in the body, refresh token in an httpOnly cookie."""
    user = await _check_password(request, form, service, throttle)
    pair = await service.issue_tokens(user.id)
    _set_refresh_cookie(response, pair.refresh_token, settings)
    return AccessToken(access_token=pair.access_token, expires_in=pair.expires_in)


@auth_router.post("/session/refresh", response_model=AccessToken)
async def refresh_session(
    response: Response, service: AuthServiceDep, settings: SettingsDep, refresh_token: RefreshCookie = None
):
    """New access token from the cookie (rotated: a new cookie replaces the old one).
    The dashboard calls this on page load ("am I still logged in?") and when the access
    token expires."""
    if not refresh_token:
        return _session_ended("Not logged in.")
    try:
        pair = await service.refresh(refresh_token)
    except RefreshTokenReused:
        return _session_ended("Refresh token reuse detected: all sessions of this login were ended.")
    except InvalidTokenError:
        return _session_ended("Session expired. Please log in again.")
    _set_refresh_cookie(response, pair.refresh_token, settings)
    return AccessToken(access_token=pair.access_token, expires_in=pair.expires_in)


@auth_router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(service: AuthServiceDep, refresh_token: RefreshCookie = None) -> Response:
    """Browser logout: revoke this login's refresh tokens and delete the cookie."""
    if refresh_token:
        await service.logout(refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(REFRESH_COOKIE, path=SESSION_COOKIE_PATH)
    return response


class GoogleAuthRequest(BaseModel):
    email: str | None = None
    username: str | None = None


class ResetPasswordRequest(BaseModel):
    email: str
    new_password: str


@auth_router.post("/google", response_model=AccessToken)
async def google_login(
    response: Response,
    body: GoogleAuthRequest,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> AccessToken:
    """Seamless Google Sign-in for local & SaaS workflows."""
    email = (body.email or "").strip().lower()
    if not email:
        users = service.list_users()
        google_users = [u for u in users if "@gmail.com" in u.email]
        if google_users:
            email = google_users[0].email
        elif users:
            email = users[0].email
        else:
            email = "user@gmail.com"
    try:
        user = await service.get_or_create_google_user(email, body.username)
    except UserDeactivated:
        raise HTTPException(status_code=403, detail="Account is deactivated.") from None
    pair = await service.issue_tokens(user.id)
    _set_refresh_cookie(response, pair.refresh_token, settings)
    return AccessToken(access_token=pair.access_token, expires_in=pair.expires_in)


@auth_router.post("/reset-password", response_model=AccessToken)
async def reset_password_endpoint(
    response: Response,
    body: ResetPasswordRequest,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> AccessToken:
    """Reset account password and issue fresh session tokens."""
    email = body.email.strip().lower()
    problem = password_problem(body.new_password, email=email)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    success = await service.reset_password(email, body.new_password)
    if not success:
        raise HTTPException(status_code=404, detail="No account registered with this email address.")

    user = await service.authenticate(email, body.new_password)
    if not user:
        raise HTTPException(status_code=400, detail="Password updated, but could not start session.")
    pair = await service.issue_tokens(user.id)
    _set_refresh_cookie(response, pair.refresh_token, settings)
    return AccessToken(access_token=pair.access_token, expires_in=pair.expires_in)
