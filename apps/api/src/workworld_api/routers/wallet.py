from fastapi import APIRouter, HTTPException
from workworld_api.dependencies import CurrentUser, Database
from workworld_api.services.ledger import LedgerError, LedgerService

router = APIRouter(prefix="/v1/wallet", tags=["wallet"])


@router.get("")
def wallet(user: CurrentUser, db: Database) -> dict[str, object]:
    return {"unit": "test_token", "balances": LedgerService(db).balances(user.id)}


@router.post("/daily-grant")
def daily_grant(user: CurrentUser, db: Database) -> dict[str, object]:
    try:
        transaction = LedgerService(db).claim_daily(user)
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "transaction_id": transaction.id,
        "balances": LedgerService(db).balances(user.id),
    }
