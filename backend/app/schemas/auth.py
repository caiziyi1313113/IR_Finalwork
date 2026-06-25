from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.user import User

IDENTITY_OPTIONS = {"本科生", "研究生", "教师", "访客"}


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    identity: str = Field(default="本科生", max_length=30)
    college: str = Field(default="", max_length=100)
    major: str = Field(default="", max_length=100)
    interest_tags: list[str] = Field(default_factory=list)
    search_need_text: str = Field(default="", max_length=500)

    @field_validator("identity")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        normalized = value.strip() or "本科生"
        if normalized not in IDENTITY_OPTIONS:
            raise ValueError("invalid identity")
        return normalized

    @field_validator("college", "major", "search_need_text")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("interest_tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        tags: list[str] = []
        for item in values:
            normalized = item.strip()
            if normalized and normalized not in tags:
                tags.append(normalized)
        return tags[:12]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class ProfileUpdateRequest(BaseModel):
    identity: str = Field(default="本科生", max_length=30)
    college: str = Field(default="", max_length=100)
    major: str = Field(default="", max_length=100)
    interest_tags: list[str] = Field(default_factory=list)
    search_need_text: str = Field(default="", max_length=500)

    @field_validator("identity")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        normalized = value.strip() or "本科生"
        if normalized not in IDENTITY_OPTIONS:
            raise ValueError("invalid identity")
        return normalized

    @field_validator("college", "major", "search_need_text")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("interest_tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        tags: list[str] = []
        for item in values:
            normalized = item.strip()
            if normalized and normalized not in tags:
                tags.append(normalized)
        return tags[:12]


class UserProfileOut(BaseModel):
    id: int
    username: str
    identity: str
    college: str
    major: str
    interest_tags: list[str]
    search_need_text: str
    profile_completed: bool

    @classmethod
    def from_user(cls, user: User) -> "UserProfileOut":
        return cls(
            id=user.id,
            username=user.username,
            identity=user.identity or "本科生",
            college=user.college or "",
            major=user.major or "",
            interest_tags=user.get_interest_tags(),
            search_need_text=user.search_need_text or "",
            profile_completed=user.profile_completed,
        )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    needs_profile_setup: bool = False
    user: UserProfileOut
