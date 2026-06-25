from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    get_current_user_required,
    get_password_hash,
    verify_password,
)
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    TokenResponse,
    UserProfileOut,
)
from app.services.search.ai_behavior_profile import (
    ai_behavior_ready,
    has_cached_ai_profile,
    refresh_ai_behavior_profile,
)

router = APIRouter()


def _build_token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        needs_profile_setup=not user.profile_completed,
        user=UserProfileOut.from_user(user),
    )


def _schedule_profile_refresh(
    background_tasks: BackgroundTasks,
    user: User,
    reason: str,
    force: bool = False,
) -> None:
    if ai_behavior_ready():
        background_tasks.add_task(refresh_ai_behavior_profile, user.id, reason, force)


@router.post("/register", response_model=TokenResponse)
def register(
    payload: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TokenResponse:
    existing = db.scalar(select(User).where(User.username == payload.username))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在，请直接登录")

    user = User(
        username=payload.username.strip(),
        password_hash=get_password_hash(payload.password),
        identity=payload.identity,
        college=payload.college,
        major=payload.major,
        search_need=payload.search_need_text,
        search_need_text=payload.search_need_text,
    )
    user.set_interest_tags(payload.interest_tags)
    db.add(user)
    db.commit()
    db.refresh(user)

    # 注册或显式画像更新时直接刷新一次，后续再转为每 5 次查询刷新。
    _schedule_profile_refresh(background_tasks, user, reason="register", force=True)
    return _build_token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在，请先注册")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="密码错误，请重试")

    # 只有缓存画像为空时才在登录后补一次。
    if not has_cached_ai_profile(user):
        _schedule_profile_refresh(background_tasks, user, reason="login")
    return _build_token_response(user)


@router.get("/profile", response_model=UserProfileOut)
def get_profile(current_user: User = Depends(get_current_user_required)) -> UserProfileOut:
    return UserProfileOut.from_user(current_user)


@router.put("/profile", response_model=UserProfileOut)
def update_profile(
    payload: ProfileUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
) -> UserProfileOut:
    current_user.identity = payload.identity
    current_user.college = payload.college
    current_user.major = payload.major
    current_user.set_interest_tags(payload.interest_tags)
    current_user.search_need = payload.search_need_text
    current_user.search_need_text = payload.search_need_text

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    _schedule_profile_refresh(background_tasks, current_user, reason="profile_update", force=True)
    return UserProfileOut.from_user(current_user)
