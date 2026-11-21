from dataclasses import dataclass

from intake.receipts import Admission


@dataclass(frozen=True)
class ParentEvidence:
    admission_id: int
    batch: str
    station: str
    revision: int
    issue_id: int
    received_from: str
    packet_sha256: str


def capture_parent_evidence(admissions: tuple[Admission, ...]) -> tuple[ParentEvidence, ...]:
    return tuple(
        ParentEvidence(
            item.admission_id, item.identity.batch, item.identity.station,
            item.identity.revision, item.identity.issue_id, item.received_from, item.packet_sha256,
        )
        for item in admissions
    )


def restore_parent_evidence(
    admission_id: int, batch: str, station: str, revision: int, issue_id: int,
    received_from: str, packet_sha256: str,
) -> ParentEvidence:
    return ParentEvidence(admission_id, batch, station, revision, issue_id, received_from, packet_sha256)
