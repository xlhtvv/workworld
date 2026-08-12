import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from workworld_api.finance_models import (
    DailyGrantClaim,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    TokenPolicyVersion,
)
from workworld_api.ids import new_id
from workworld_api.models import User

SIGNUP_GRANT = 100_000
DAILY_GRANT = 10_000
BALANCE_CAP = 500_000
TOKEN_POLICY_ID = "token_policy_v1"
NONNEGATIVE_ACCOUNTS = {"user_available", "user_held", "provider_available"}


class LedgerError(ValueError):
    pass


def seed_token_policy(db: Session) -> int:
    if db.get(TokenPolicyVersion, TOKEN_POLICY_ID) is not None:
        return 0
    LedgerService(db)._policy()
    db.commit()
    return 1


class LedgerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def account(self, account_key: str, owner_id: str | None, account_type: str) -> LedgerAccount:
        row = self.db.scalar(select(LedgerAccount).where(LedgerAccount.account_key == account_key))
        if row is not None:
            if row.owner_id != owner_id or row.account_type != account_type:
                raise LedgerError("ledger_account_key_conflict")
            return row
        row = LedgerAccount(
            id=new_id("account"),
            account_key=account_key,
            owner_id=owner_id,
            account_type=account_type,
            created_at=datetime.now(UTC),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def user_accounts(self, user_id: str) -> dict[str, LedgerAccount]:
        return {
            kind: self.account(f"user:{user_id}:{kind}", user_id, kind)
            for kind in ("user_available", "user_held", "provider_available")
        }

    def platform_account(self, kind: str) -> LedgerAccount:
        if kind not in {"platform_faucet", "platform_adjustment"}:
            raise LedgerError("platform_account_type_invalid")
        return self.account(f"platform:{kind}", None, kind)

    def balance(self, account: LedgerAccount) -> int:
        return int(
            self.db.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                    LedgerEntry.account_id == account.id
                )
            )
            or 0
        )

    def balances(self, user_id: str) -> dict[str, int]:
        return {
            kind: self.balance(account)
            for kind, account in self.user_accounts(user_id).items()
        }

    def signup_grant(self, user: User, *, commit: bool = True) -> LedgerTransaction:
        policy = self._policy()
        accounts = self.user_accounts(user.id)
        faucet = self.platform_account("platform_faucet")
        return self._post(
            "signup_grant",
            f"signup:{user.id}",
            "user",
            user.id,
            {
                accounts["user_available"]: int(policy.definition_json["signup_grant"]),
                faucet: -int(policy.definition_json["signup_grant"]),
            },
            metadata={"token_policy_version_id": policy.id},
            commit=commit,
        )

    def claim_daily(
        self, user: User, claim_date: date | None = None
    ) -> LedgerTransaction:
        day = claim_date or datetime.now(UTC).date()
        idempotency_key = f"daily:{user.id}:{day.isoformat()}"
        existing_transaction = self.db.scalar(
            select(LedgerTransaction).where(
                LedgerTransaction.idempotency_key == idempotency_key
            )
        )
        if existing_transaction is not None:
            return existing_transaction
        policy = self._policy()
        accounts = self.user_accounts(user.id)
        faucet = self.platform_account("platform_faucet")
        available = self.balance(accounts["user_available"])
        grant = min(
            int(policy.definition_json["daily_grant"]),
            int(policy.definition_json["balance_cap"]) - available,
        )
        if grant <= 0:
            raise LedgerError("daily_grant_balance_cap_reached")
        transaction = self._post(
            "daily_grant",
            idempotency_key,
            "daily_grant",
            f"{user.id}:{day.isoformat()}",
            {accounts["user_available"]: grant, faucet: -grant},
            metadata={"token_policy_version_id": policy.id},
            commit=False,
        )
        existing = self.db.scalar(
            select(DailyGrantClaim).where(
                DailyGrantClaim.user_id == user.id,
                DailyGrantClaim.claim_date == day,
            )
        )
        if existing is None:
            self.db.add(
                DailyGrantClaim(
                    id=new_id("claim"),
                    user_id=user.id,
                    claim_date=day,
                    transaction_id=transaction.id,
                    created_at=datetime.now(UTC),
                )
            )
        self.db.commit()
        return transaction

    def hold(
        self,
        user_id: str,
        task_id: str,
        amount: int,
        *,
        increase: bool = False,
        operation_id: str | None = None,
    ) -> LedgerTransaction:
        if amount <= 0:
            raise LedgerError("hold_amount_invalid")
        accounts = self.user_accounts(user_id)
        return self._post(
            "task_hold_increase" if increase else "task_hold",
            f"task:{task_id}:{operation_id or ('increase' if increase else 'hold')}",
            "task",
            task_id,
            {
                accounts["user_available"]: -amount,
                accounts["user_held"]: amount,
            },
            commit=False,
        )

    def settle(
        self,
        user_id: str,
        provider_id: str,
        task_id: str,
        settled_amount: int,
        *,
        partial: bool = False,
    ) -> LedgerTransaction:
        user_accounts = self.user_accounts(user_id)
        provider_accounts = self.user_accounts(provider_id)
        held = self.task_held(user_accounts["user_held"], task_id)
        if settled_amount < 0 or settled_amount > held:
            raise LedgerError("settlement_amount_invalid")
        refund = held - settled_amount
        entries = {
            user_accounts["user_held"]: -held,
            provider_accounts["provider_available"]: settled_amount,
            user_accounts["user_available"]: refund,
        }
        return self._post(
            "task_partial_settlement" if partial else "task_settlement",
            f"task:{task_id}:{'partial' if partial else 'settle'}",
            "task",
            task_id,
            entries,
            commit=False,
        )

    def refund(self, user_id: str, task_id: str) -> LedgerTransaction:
        accounts = self.user_accounts(user_id)
        held = self.task_held(accounts["user_held"], task_id)
        if held <= 0:
            raise LedgerError("task_has_no_held_balance")
        return self._post(
            "task_refund",
            f"task:{task_id}:refund",
            "task",
            task_id,
            {accounts["user_held"]: -held, accounts["user_available"]: held},
            commit=False,
        )

    def admin_adjust(
        self, user_id: str, amount: int, idempotency_key: str, reason: str
    ) -> LedgerTransaction:
        if amount == 0 or not reason.strip():
            raise LedgerError("admin_adjustment_invalid")
        accounts = self.user_accounts(user_id)
        adjustment = self.platform_account("platform_adjustment")
        return self._post(
            "admin_adjustment",
            idempotency_key,
            "user",
            user_id,
            {accounts["user_available"]: amount, adjustment: -amount},
            commit=True,
        )

    def task_held(self, held_account: LedgerAccount, task_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount), 0))
                .join(
                    LedgerTransaction,
                    LedgerTransaction.id == LedgerEntry.transaction_id,
                )
                .where(
                    LedgerEntry.account_id == held_account.id,
                    LedgerTransaction.reference_type == "task",
                    LedgerTransaction.reference_id == task_id,
                )
            )
            or 0
        )

    def _post(
        self,
        transaction_type: str,
        idempotency_key: str,
        reference_type: str,
        reference_id: str,
        entries: dict[LedgerAccount, int],
        *,
        metadata: dict[str, object] | None = None,
        commit: bool,
    ) -> LedgerTransaction:
        combined: dict[str, int] = defaultdict(int)
        for account, amount in entries.items():
            combined[account.id] += amount
        combined = {account_id: amount for account_id, amount in combined.items() if amount}
        if not combined or sum(combined.values()) != 0:
            raise LedgerError("ledger_transaction_unbalanced")
        locked = list(
            self.db.scalars(
                select(LedgerAccount)
                .where(LedgerAccount.id.in_(sorted(combined)))
                .order_by(LedgerAccount.id)
                .with_for_update()
            )
        )
        existing = self.db.scalar(
            select(LedgerTransaction).where(
                LedgerTransaction.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing
        if len(locked) != len(combined):
            raise LedgerError("ledger_account_missing")
        for account in locked:
            if (
                account.account_type in NONNEGATIVE_ACCOUNTS
                and self.balance(account) + combined[account.id] < 0
            ):
                raise LedgerError("insufficient_balance")
        now = datetime.now(UTC)
        transaction = LedgerTransaction(
            id=new_id("transaction"),
            transaction_type=transaction_type,
            idempotency_key=idempotency_key,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata_json=metadata or {},
            created_at=now,
        )
        self.db.add(transaction)
        self.db.flush()
        for account_id, amount in combined.items():
            self.db.add(
                LedgerEntry(
                    id=new_id("entry"),
                    transaction_id=transaction.id,
                    account_id=account_id,
                    amount=amount,
                    memo=transaction_type,
                    created_at=now,
                )
            )
        self.db.flush()
        if commit:
            self.db.commit()
        return transaction

    def _policy(self) -> TokenPolicyVersion:
        policy = self.db.get(TokenPolicyVersion, TOKEN_POLICY_ID)
        if policy is not None:
            return policy
        definition = {
            "signup_grant": SIGNUP_GRANT,
            "daily_grant": DAILY_GRANT,
            "balance_cap": BALANCE_CAP,
            "withdrawable": False,
        }
        encoded = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
        now = datetime.now(UTC)
        policy = TokenPolicyVersion(
            id=TOKEN_POLICY_ID,
            version="1.0",
            definition_json=definition,
            content_sha256=hashlib.sha256(encoded).hexdigest(),
            status="published",
            created_at=now,
            published_at=now,
        )
        self.db.add(policy)
        self.db.flush()
        return policy
