from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select

from database import AuditLog, Intervention, PaymentEvent, RecoveryCase
from db_session import SessionLocal


VALID_BATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete one exact RecoverIQ demo batch")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    batch_id = args.batch_id.strip()
    if batch_id.lower() == "all" or batch_id == "*" or not VALID_BATCH_ID.fullmatch(batch_id):
        parser.error("--batch-id must be one exact, non-empty batch identifier")
    with SessionLocal() as db:
        case_ids = list(db.scalars(select(RecoveryCase.id).where(RecoveryCase.batch_id == batch_id)))
        demo_marker = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.recovery_case_id.in_(case_ids), AuditLog.action == "DEMO_BATCH_CASE_CREATED")) if case_ids else 0
        if case_ids and demo_marker != len(case_ids):
            raise SystemExit("Refusing reset: selected batch contains records without demo markers")
        event_count = db.scalar(select(func.count()).select_from(PaymentEvent).where(PaymentEvent.batch_id == batch_id)) or 0
        print(f"Batch {batch_id}: {len(case_ids)} cases and {event_count} events will be removed.")
        if not args.confirm:
            print("Dry run only. Add --confirm to delete this exact demo batch.")
            return 0
        try:
            if case_ids:
                db.execute(delete(AuditLog).where(AuditLog.recovery_case_id.in_(case_ids)))
                db.execute(delete(Intervention).where(Intervention.recovery_case_id.in_(case_ids)))
            db.execute(delete(PaymentEvent).where(PaymentEvent.batch_id == batch_id))
            db.execute(delete(RecoveryCase).where(RecoveryCase.batch_id == batch_id))
            db.commit()
        except Exception:
            db.rollback()
            raise
    print(f"Reset complete: removed {len(case_ids)} cases and {event_count} events.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
