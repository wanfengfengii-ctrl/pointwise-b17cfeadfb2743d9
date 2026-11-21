from dataclasses import dataclass

from intake.inbox import IntakeInbox
from intake.receipts import Admission, load_admission


@dataclass(frozen=True)
class SelectedAdmissions:
    batch: str
    admissions: tuple[Admission, ...]


def select_admissions(inbox: IntakeInbox, admission_ids: tuple[int, ...]) -> SelectedAdmissions:
    if not isinstance(admission_ids, (list, tuple)) or not 2 <= len(admission_ids) <= 3:
        raise ValueError('A review must specify two or three admission numbers')
    admissions = tuple(load_admission(inbox, number) for number in admission_ids)
    identities = tuple(admission.identity for admission in admissions)
    if len({identity.station for identity in identities}) != len(admissions):
        raise ValueError('A station may be selected only once')
    batch = identities[0].batch
    if any(identity.batch != batch for identity in identities):
        raise ValueError('All admissions in a review must have the same batch')
    return SelectedAdmissions(batch, admissions)
