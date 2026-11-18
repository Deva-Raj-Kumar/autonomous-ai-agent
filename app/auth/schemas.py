"""Request/response models for authentication."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.auth.security import MAX_PASSWORD_LENGTH, password_problem
from app.timeutils import UTCDateTime


class RegisterRequest(BaseModel):
    email: EmailStr  # validated AND normalised by email-validator
    username: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9 ._-]+$")
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @model_validator(mode="after")
    def _strong_password(self) -> "RegisterRequest":
        problem = password_problem(self.password, str(self.email), self.username)
        if problem:
            raise ValueError(problem)
        return self


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class TokenPair(BaseModel):
    """OAuth2-style token response (Swagger's Authorize button understands it)."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - a scheme name, not a secret
    expires_in: int  # seconds until the access token expires


class AuthUser(BaseModel):
    """The logged-in user as the API sees it. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    is_admin: bool = False
    is_active: bool = True
    created_at: UTCDateTime | None = None
    last_login_at: UTCDateTime | None = None
