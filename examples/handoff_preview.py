import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from intake.inbox import IntakeInbox
from intake.receipts import receive_packet
from issue.catalog import IssueCatalog
from issue.packet import issue_packet
from reports.retrieve import get_report
from reports.store import ReportStore
from review.request import ReviewRequest, sign_review
from station.ingest import ingest_scan
from station.source_store import SourceStore


def receive_scans(inbox, scans):
    packets = {}
    with closing(sqlite3.connect(":memory:")) as connection:
        source = SourceStore(connection)
        catalog = IssueCatalog(connection)
        source.initialize()
        catalog.initialize()
        for name, scan in scans.items():
            revision = ingest_scan(source, scan)
            packets[name] = issue_packet(
                source, catalog, batch=scan["batch"], station=scan["station"], revision=revision,
            ).packet
    return {
        name: receive_packet(inbox, packet, received_from=f"fixture/{name}").admission_id
        for name, packet in packets.items()
    }


def build_request(spec, admissions):
    numbers = tuple(admissions[name] for name in spec["parents"])
    probes = tuple(tuple(reference) for reference in spec["probes"])
    return ReviewRequest(numbers, spec["anchor"], probes)


def v1_preview(scenarios):
    result = {}
    when = datetime(2025, 3, 4, 20, tzinfo=timezone.utc)
    with closing(sqlite3.connect(":memory:")) as connection:
        inbox = IntakeInbox(connection)
        reports = ReportStore(connection)
        inbox.initialize()
        reports.initialize()
        for scenario_name, scenario in scenarios.items():
            admissions = receive_scans(inbox, scenario["scans"])
            summary = {}
            for name, spec in scenario["requests"].items():
                request = build_request(spec, admissions)
                report = sign_review(inbox, reports, request, signed_by="Bench lead", signed_at=when)
                distances = [str(distance) for distance in report.distances]
                parents = [parent.admission_id for parent in report.parents]
                if distances != spec["distances"] or parents != list(request.admission_ids):
                    raise AssertionError(f"{scenario_name}/{name}: {distances=}, {parents=}")
                if get_report(reports, report.report_id) != report:
                    raise AssertionError(f"{scenario_name}/{name}: V1 readback differs")
                summary[name] = {"anchor": report.anchor_station, "distances": distances, "parents": parents}
            result[scenario_name] = summary
    return result


def main():
    fixture = Path(__file__).with_name("handoff.json")
    scenarios = json.loads(fixture.read_text(encoding="utf-8"))
    print(json.dumps(v1_preview(scenarios), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
