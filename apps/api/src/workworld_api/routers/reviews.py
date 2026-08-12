from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from workworld_api.dependencies import CurrentUser, Database
from workworld_api.reputation_models import Review, ReviewReply
from workworld_api.services.reviews import ReviewError, ReviewService

router = APIRouter(prefix="/v1", tags=["reviews"])


class ReviewBody(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: str = Field(min_length=1, max_length=5000)


class ReplyBody(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ProfileBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    bio: str = Field(min_length=1, max_length=5000)


def review_view(review: Review) -> dict[str, object]:
    return {
        "id": review.id,
        "run_id": review.run_id,
        "provider_id": review.provider_id,
        "rating": review.rating,
        "body": review.body,
        "created_at": review.created_at,
    }


@router.post("/runs/{run_id}/review", status_code=201)
def create_review(
    run_id: str, body: ReviewBody, user: CurrentUser, db: Database
) -> dict[str, object]:
    try:
        return review_view(ReviewService(db).create(user, run_id, body.rating, body.body))
    except ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reviews/{review_id}/reply", status_code=201)
def reply(
    review_id: str, body: ReplyBody, user: CurrentUser, db: Database
) -> dict[str, object]:
    try:
        row: ReviewReply = ReviewService(db).reply(user, review_id, body.body)
    except ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": row.id, "review_id": row.review_id, "body": row.body}


@router.get("/providers/{provider_id}/reputation")
def reputation(provider_id: str, db: Database) -> dict[str, object]:
    return ReviewService(db).provider_summary(provider_id)


@router.put("/profile")
def update_profile(
    body: ProfileBody, user: CurrentUser, db: Database
) -> dict[str, object]:
    try:
        profile = ReviewService(db).upsert_profile(user, body.display_name, body.bio)
    except ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "provider_id": profile.user_id,
        "display_name": profile.display_name,
        "bio": profile.bio,
    }


@router.get("/profile/{provider_slug}")
def profile(provider_slug: str, db: Database) -> dict[str, object]:
    try:
        return ReviewService(db).public_profile(provider_slug)
    except ReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
