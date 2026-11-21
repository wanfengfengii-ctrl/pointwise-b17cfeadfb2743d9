from reports.store import ReportStore, StoredReport


def get_report(store: ReportStore, report_id: int) -> StoredReport | None:
    return store.read_report(report_id)


def get_handoff(store: ReportStore, report_id: int) -> bytes | None:
    if type(report_id) is not int or not 0 < report_id < 2**63:
        raise ValueError('Invalid report number')
    return store.read_handoff(report_id)
