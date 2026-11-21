from dataclasses import dataclass
from datetime import datetime, timezone

from station.markers import require_label


@dataclass(frozen=True)
class FirstReceipt:
    report_id: int
    signed_by: str
    signed_at: datetime


def make_first_receipt(
    report_id: int, signed_by: str, signed_at: datetime | None = None
) -> FirstReceipt:
    signer = require_label(signed_by, 'Signer')
    when = datetime.now(timezone.utc) if signed_at is None else signed_at
    if not isinstance(when, datetime) or when.utcoffset() is None:
        raise ValueError('Signature time must be a timezone-aware datetime')
    return FirstReceipt(report_id, signer, when.astimezone(timezone.utc))


def restore_first_receipt(report_id: int, signed_by: str, signed_at: str) -> FirstReceipt:
    return FirstReceipt(report_id, signed_by, datetime.fromisoformat(signed_at))
