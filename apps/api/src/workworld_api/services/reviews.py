import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from workworld_api.finance_models import QualityEvaluation
from workworld_api.market_models import Agent, Offering, OfferingVersion
from workworld_api.models import User
from workworld_api.reputation_models import AuditEvent, ProviderProfile, Review, ReviewReply
from workworld_api.services.moderation import ModerationBlocked, ModerationService
from workworld_api.task_models import Run, RunEvent, Task


class ReviewError(ValueError):
    pass


class ReviewService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, reviewer: User, run_id: str, rating: int, body: str) -> Review:
        run = self.db.get(Run, run_id)
        task = self.db.get(Task, run.task_id) if run else None
        agent = self.db.get(Agent, run.agent_id) if run else None
        if (
            run is None
            or task is None
            or agent is None
            or run.state != "completed"
            or task.publisher_id != reviewer.id
        ):
            raise ReviewError("completed_run_not_found")
        if not 1 <= rating <= 5 or not body.strip():
            raise ReviewError("review_invalid")
        review_id = f"review_{uuid.uuid4().hex}"
        try:
            moderation = ModerationService(self.db).check_text("review", review_id, body)
        except ModerationBlocked as exc:
            raise ReviewError(str(exc)) from exc
        review = Review(
            id=review_id,
            run_id=run.id,
            reviewer_id=reviewer.id,
            provider_id=agent.owner_id,
            rating=rating,
            body=body,
            status="visible",
            moderation_result_id=moderation.id,
            created_at=datetime.now(UTC),
        )
        self.db.add(review)
        self._audit(reviewer.id, "review.created", "review", review.id)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ReviewError("review_already_exists") from exc
        return review

    def reply(self, provider: User, review_id: str, body: str) -> ReviewReply:
        review = self.db.get(Review, review_id)
        if review is None or review.provider_id != provider.id:
            raise ReviewError("review_not_found")
        if not body.strip():
            raise ReviewError("reply_invalid")
        reply_id = f"reply_{uuid.uuid4().hex}"
        try:
            moderation = ModerationService(self.db).check_text("review_reply", reply_id, body)
        except ModerationBlocked as exc:
            raise ReviewError(str(exc)) from exc
        reply = ReviewReply(
            id=reply_id,
            review_id=review.id,
            provider_id=provider.id,
            body=body,
            status="visible",
            moderation_result_id=moderation.id,
            created_at=datetime.now(UTC),
        )
        self.db.add(reply)
        self._audit(provider.id, "review.reply_created", "review", review.id)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ReviewError("review_reply_already_exists") from exc
        return reply

    def provider_summary(self, provider_id: str) -> dict[str, object]:
        agents = select(Agent.id).where(Agent.owner_id == provider_id)
        runs = list(self.db.scalars(select(Run).where(Run.agent_id.in_(agents))))
        run_ids = [run.id for run in runs]
        completed = sum(run.state == "completed" for run in runs)
        reviews = list(
            self.db.scalars(
                select(Review).where(
                    Review.provider_id == provider_id, Review.status == "visible"
                )
            )
        )
        quality = self.db.scalar(
            select(func.avg(QualityEvaluation.quality_score)).where(
                QualityEvaluation.run_id.in_(run_ids)
            )
        ) if run_ids else None
        accepted_events = (
            self.db.scalar(
                select(func.count(RunEvent.id)).where(
                    RunEvent.run_id.in_(run_ids), RunEvent.event_type == "task.accept"
                )
            )
            if run_ids
            else 0
        )
        return {
            "completed_runs": completed,
            "total_runs": len(runs),
            "acceptance_rate": (accepted_events or 0) / len(runs) if runs else None,
            "average_quality_score": float(quality) if quality is not None else None,
            "average_rating": (
                sum(review.rating for review in reviews) / len(reviews) if reviews else None
            ),
            "review_count": len(reviews),
        }

    def upsert_profile(self, provider: User, display_name: str, bio: str) -> ProviderProfile:
        if not display_name.strip() or not bio.strip():
            raise ReviewError("profile_invalid")
        try:
            ModerationService(self.db).check_text(
                "provider_profile", provider.id, f"{display_name}\n{bio}"
            )
        except ModerationBlocked as exc:
            raise ReviewError(str(exc)) from exc
        now = datetime.now(UTC)
        profile = self.db.get(ProviderProfile, provider.id)
        if profile is None:
            profile = ProviderProfile(
                user_id=provider.id,
                display_name=display_name.strip(),
                bio=bio.strip(),
                status="public",
                created_at=now,
                updated_at=now,
            )
            self.db.add(profile)
        else:
            profile.display_name = display_name.strip()
            profile.bio = bio.strip()
            profile.updated_at = now
        self._audit(provider.id, "provider_profile.updated", "provider", provider.id)
        self.db.commit()
        return profile

    def public_profile(self, identifier: str) -> dict[str, object]:
        profile = self.db.get(ProviderProfile, identifier)
        provider_id = profile.user_id if profile is not None else self.db.scalar(
            select(Agent.owner_id).where(Agent.slug == identifier).limit(1)
        )
        if provider_id is None:
            raise ReviewError("provider_not_found")
        profile = self.db.get(ProviderProfile, provider_id)
        agents = list(
            self.db.scalars(
                select(Agent).where(Agent.owner_id == provider_id, Agent.status == "active")
            )
        )
        offerings = self.db.execute(
            select(Offering, OfferingVersion)
            .join(OfferingVersion, Offering.latest_version_id == OfferingVersion.id)
            .where(
                Offering.owner_id == provider_id,
                Offering.status == "published",
                OfferingVersion.status == "published",
            )
        ).all()
        reviews = list(
            self.db.scalars(
                select(Review)
                .where(Review.provider_id == provider_id, Review.status == "visible")
                .order_by(Review.created_at.desc())
                .limit(100)
            )
        )
        review_ids = [review.id for review in reviews]
        replies = {
            reply.review_id: reply
            for reply in self.db.scalars(
                select(ReviewReply).where(
                    ReviewReply.review_id.in_(review_ids), ReviewReply.status == "visible"
                )
            )
        } if review_ids else {}
        return {
            "provider_id": provider_id,
            "display_name": (
                profile.display_name if profile else (agents[0].name if agents else "Provider")
            ),
            "bio": profile.bio if profile else "",
            "reputation": self.provider_summary(provider_id),
            "agents": [
                {"id": agent.id, "name": agent.name, "slug": agent.slug} for agent in agents
            ],
            "offerings": [
                {
                    "id": offering.id,
                    "slug": offering.slug,
                    "version_id": version.id,
                    "schema_id": version.schema_id,
                    "name": version.name_i18n,
                }
                for offering, version in offerings
            ],
            "reviews": [
                {
                    "id": review.id,
                    "rating": review.rating,
                    "body": review.body,
                    "created_at": review.created_at,
                    "reply": replies[review.id].body if review.id in replies else None,
                }
                for review in reviews
            ],
        }

    def _audit(self, actor_id: str, action: str, subject_type: str, subject_id: str) -> None:
        self.db.add(
            AuditEvent(
                id=f"audit_{uuid.uuid4().hex}",
                actor_type="user",
                actor_id=actor_id,
                action=action,
                subject_type=subject_type,
                subject_id=subject_id,
                details_json={},
                created_at=datetime.now(UTC),
            )
        )
