from datetime import datetime
from fractions import Fraction

from intake.selection import SelectedAdmissions
from reports.lineage import capture_parent_evidence
from reports.store import ReportStore, StoredReport


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
