from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user_optional
from app.db.database import get_db
from app.models.user import User
from app.schemas.search import ClickRequest, ClickResponse, RecommendationList, SearchResponse, SuggestionResponse
from app.services.search.ai_behavior_profile import ai_behavior_ready, refresh_ai_behavior_profile
from app.services.search.search_service import SearchService
from app.services.snapshot.storage import read_snapshot_text

router = APIRouter()

SNAPSHOT_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; "
        "img-src https: http: data: blob:; "
        "style-src 'unsafe-inline' https: http:; "
        "font-src https: http: data:; "
        "media-src https: http: data:; "
        "script-src 'none'; "
        "connect-src 'none'; "
        "object-src 'none'; "
        "frame-src https: http:; "
        "form-action 'none'; "
        "base-uri 'self' https: http:;"
    ),
    "X-Content-Type-Options": "nosniff",
}


def _schedule_profile_refresh(
    background_tasks: BackgroundTasks,
    current_user: User | None,
    reason: str,
    force: bool = False,
) -> None:
    if current_user and ai_behavior_ready():
        background_tasks.add_task(refresh_ai_behavior_profile, current_user.id, reason, force)


@router.get("/search", response_model=SearchResponse)
async def search_endpoint(
    background_tasks: BackgroundTasks,
    q: str = Query(..., min_length=1, description="用户输入的原始查询"),
    mode: str = Query(default="normal", description="normal/document/phrase/wildcard"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=30),
    slop: int = Query(default=0, ge=0, le=5),
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> SearchResponse:
    service = SearchService(db=db)
    response = await service.search(
        query=q,
        mode=mode,
        page=page,
        size=size,
        phrase_slop=slop,
        current_user=current_user,
    )
    _schedule_profile_refresh(background_tasks, current_user, reason="search")
    return response


@router.get("/history", response_model=list[str])
def history_endpoint(
    limit: int = Query(default=50, ge=1, le=50),
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> list[str]:
    if not current_user:
        return []
    service = SearchService(db=db)
    return service.get_recent_queries(current_user.id, limit)


@router.get("/suggestions", response_model=SuggestionResponse)
async def suggestion_endpoint(
    q: str = Query(default="", description="前缀输入"),
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> SuggestionResponse:
    service = SearchService(db=db)
    return await service.suggest(prefix=q, current_user=current_user)


@router.get("/recommendations", response_model=RecommendationList)
async def recommendation_endpoint(
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> RecommendationList:
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录后查看个性化推荐")
    service = SearchService(db=db)
    return await service.recommend(current_user=current_user)


@router.post("/click", response_model=ClickResponse)
def click_endpoint(
    payload: ClickRequest,
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> ClickResponse:
    service = SearchService(db=db)
    return service.record_click(payload=payload, current_user=current_user)


@router.get("/snapshot/{doc_id}", response_class=HTMLResponse)
async def snapshot_endpoint(doc_id: str) -> HTMLResponse:
    snapshot = await read_snapshot_text(doc_id=doc_id)
    return HTMLResponse(snapshot, headers=SNAPSHOT_HEADERS)
