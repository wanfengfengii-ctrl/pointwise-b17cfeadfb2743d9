from datetime import datetime
from fractions import Fraction

from intake.selection import SelectedAdmissions
from reports.lineage import capture_parent_evidence
from reports.receipt import FirstReceipt
from reports.store import ReportStore, StoredReport
from review.handoff import HandoffDocument, encode_handoff
from review.placement import JointPlacement


def publish_review(
    store: ReportStore, selected: SelectedAdmissions, *, anchor_station: str,
    probes: tuple[tuple[str, str], tuple[str, str]], distances: tuple[Fraction, ...],
    signed_by: str, signed_at: datetime | None,
) -> StoredReport:
    parents = capture_parent_evidence(selected.admissions)
    return store.commit_report(
        batch=selected.batch, anchor_station=anchor_station, probes=probes,
        distances=distances, parents=parents, signed_by=signed_by, signed_at=signed_at,
    )


def publish_handoff(
    store: ReportStore, selected: SelectedAdmissions, *, anchor_station: str,
    probes: tuple[tuple[str, str], tuple[str, str]], distances: tuple[Fraction, ...],
    placements_by_distance: dict[Fraction, tuple[JointPlacement, ...]],
    signed_by: str, signed_at: datetime | None,
) -> StoredReport:
    parents = capture_parent_evidence(selected.admissions)
    stations = tuple(parent.station for parent in parents)
    evidence = tuple(
        tuple(
            tuple(joint[station] for station in stations)
            for joint in placements_by_distance[distance]
        )
        for distance in distances
    )

    def encode_document(report_id: int, receipt: FirstReceipt) -> bytes:
        document = HandoffDocument(
            report_id, selected.batch, anchor_station, probes, distances,
            parents, receipt, evidence,
        )
        return encode_handoff(document)

    return store.commit_handoff(
        batch=selected.batch, anchor_station=anchor_station, probes=probes,
        distances=distances, parents=parents, signed_by=signed_by,
        signed_at=signed_at, encode_document=encode_document,
    )
