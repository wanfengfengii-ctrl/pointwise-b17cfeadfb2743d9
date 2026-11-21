from reports.store import ReportStore, StoredReport


def get_report(store: ReportStore, report_id: int) -> StoredReport | None:
    return store.read_report(report_id)
