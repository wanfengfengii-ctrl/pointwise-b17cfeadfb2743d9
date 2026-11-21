"""Version 2 handoff documents and offline combined fixturing.

A handoff document freezes every exact squared probe distance together with
every complete permitted joint placement that realizes it. Offline combination
works only from these documents: shared admissions hook the pieces together and
each piece keeps only the placements already signed at the center.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Optional

from reports.lineage import ParentEvidence
from reports.receipt import FirstReceipt
from review.rigid import RigidPlacement, compose, inverse
from station.coordinates import parse_rational
from station.markers import require_label

HANDOFF_VERSION = 2
_PARENT_FIELDS = (
    'admission_id', 'batch', 'station', 'revision', 'issue_id',
    'received_from', 'packet_sha256',
)
_RECEIPT_FIELDS = ('report_id', 'signed_by', 'signed_at')
_DOCUMENT_FIELDS = {
    'version', 'report_id', 'batch', 'anchor_station', 'probes',
    'distances', 'parents', 'receipt', 'evidence',
}
_EVIDENCE_PLACEMENT_FIELDS = ('cosine', 'sine', 'tx', 'ty', 'reflected')


@dataclass(frozen=True)
class HandoffDocument:
    report_id: int
    batch: str
    anchor_station: str
    probes: tuple[tuple[str, str], tuple[str, str]]
    distances: tuple[Fraction, ...]
    parents: tuple[ParentEvidence, ...]
    receipt: FirstReceipt
    # One entry per distance; each entry lists every complete joint placement
    # that realizes the distance, and every joint placement lists one rigid
    # placement per parent in parent order.
    evidence: tuple[tuple[tuple[RigidPlacement, ...], ...], ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate handoff field {key!r}')
        result[key] = value
    return result


def _exact_object(value: object, keys: set[str], role: str) -> dict:
    if not isinstance(value, dict) or set(value.keys()) != keys:
        raise ValueError(f'Invalid fields in {role}')
    return value


def _positive_int(value: object, role: str) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError(f'{role} must be a positive integer')
    return value


def _exact_rational_string(value: object, role: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f'{role} must be an exact rational string')
    try:
        parsed = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f'{role} must be an exact rational string') from error
    if str(parsed) != value:
        raise ValueError(f'{role} must use the canonical rational spelling')
    return value


def _decode_parent(value: object, index: int, batch: str) -> ParentEvidence:
    data = _exact_object(value, set(_PARENT_FIELDS), f'handoff parent {index}')
    parent_batch = require_label(data['batch'], 'Parent batch')
    if parent_batch != batch:
        raise ValueError('Handoff parents must share the document batch')
    return ParentEvidence(
        _positive_int(data['admission_id'], 'Admission number'),
        parent_batch,
        require_label(data['station'], 'Parent station'),
        _positive_int(data['revision'], 'Revision number'),
        _positive_int(data['issue_id'], 'Issue number'),
        require_label(data['received_from'], 'First receipt source'),
        _decode_sha256(data['packet_sha256']),
    )


def _decode_sha256(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError('Packet digest must be a 64 character hexadecimal SHA-256')
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError('Packet digest must be a 64 character hexadecimal SHA-256') from error
    return value.lower()


def _decode_probes(value: object) -> tuple[tuple[str, str], tuple[str, str]]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('Handoff probes must contain exactly two references')
    probes = []
    for reference in value:
        if not isinstance(reference, (list, tuple)) or len(reference) != 2:
            raise ValueError('A handoff probe reference must contain a station and a name')
        probes.append((
            require_label(reference[0], 'Probe station'),
            require_label(reference[1], 'Probe name'),
        ))
    return probes[0], probes[1]


def _decode_placement(value: object, role: str) -> RigidPlacement:
    data = _exact_object(value, set(_EVIDENCE_PLACEMENT_FIELDS), role)
    cosine = parse_rational(data['cosine'])
    sine = parse_rational(data['sine'])
    tx = parse_rational(data['tx'])
    ty = parse_rational(data['ty'])
    if type(data['reflected']) is not bool:
        raise ValueError('Evidence reflection flag must be a boolean')
    if cosine * cosine + sine * sine != 1:
        raise ValueError('Evidence rotation coefficients must describe a unit rotation')
    return RigidPlacement(cosine, sine, (tx, ty), data['reflected'])


def _decode_receipt(value: object, report_id: int) -> FirstReceipt:
    data = _exact_object(value, set(_RECEIPT_FIELDS), 'handoff receipt')
    if _positive_int(data['report_id'], 'Receipt report number') != report_id:
        raise ValueError('Handoff receipt report number does not match the document')
    signed_by = require_label(data['signed_by'], 'Signer')
    if not isinstance(data['signed_at'], str):
        raise ValueError('Handoff signing time must be an ISO 8601 string')
    try:
        signed_at = datetime.fromisoformat(data['signed_at'])
    except ValueError as error:
        raise ValueError('Handoff signing time must be an ISO 8601 string') from error
    if signed_at.utcoffset() is None or signed_at.utcoffset().total_seconds() != 0:
        raise ValueError('Handoff signing time must be a UTC ISO 8601 timestamp')
    return FirstReceipt(report_id, signed_by, signed_at)


def decode_handoff(document: object) -> HandoffDocument:
    """Strictly decode and self-check a handoff document object.

    Raises ``ValueError`` for malformed documents, V1 packets and documents
    whose evidence is not internally consistent.
    """
    if not isinstance(document, dict):
        raise ValueError('Handoff document must be a JSON object')
    envelope = _exact_object(document, _DOCUMENT_FIELDS, 'handoff document')
    if type(envelope['version']) is not int:
        raise ValueError('Handoff version must be an integer')
    if envelope['version'] != HANDOFF_VERSION:
        if envelope['version'] == 1:
            raise ValueError('V1 station packets are not handoff documents')
        raise ValueError('Unsupported handoff version')
    report_id = _positive_int(envelope['report_id'], 'Report number')
    batch = require_label(envelope['batch'], 'Batch')
    anchor_station = require_label(envelope['anchor_station'], 'Anchor station')
    probes = _decode_probes(envelope['probes'])

    raw_distances = envelope['distances']
    if not isinstance(raw_distances, (list, tuple)):
        raise ValueError('Handoff distances must be an array of rational strings')
    distances: list[Fraction] = []
    for raw in raw_distances:
        text = _exact_rational_string(raw, 'Handoff distance')
        distance = Fraction(text)
        if distance < 0:
            raise ValueError('Handoff distances must be nonnegative')
        distances.append(distance)
    if any(left >= right for left, right in zip(distances, distances[1:])):
        raise ValueError('Handoff distances must be strictly ascending and unique')

    raw_parents = envelope['parents']
    if not isinstance(raw_parents, (list, tuple)) or len(raw_parents) not in (2, 3):
        raise ValueError('Handoff parents must list two or three admissions')
    parents = tuple(_decode_parent(raw, index, batch) for index, raw in enumerate(raw_parents))
    stations = [parent.station for parent in parents]
    if len(set(stations)) != len(stations):
        raise ValueError('Handoff parent stations must be unique')
    admissions = [parent.admission_id for parent in parents]
    if len(set(admissions)) != len(admissions):
        raise ValueError('Handoff parent admission numbers must be unique')
    anchor_index = next(
        (index for index, parent in enumerate(parents) if parent.station == anchor_station), None,
    )
    if anchor_index is None:
        raise ValueError('Anchor station must be one of the handoff parents')
    for station, _name in probes:
        if station not in stations:
            raise ValueError('Handoff probe station must be one of the parents')

    receipt = _decode_receipt(envelope['receipt'], report_id)

    raw_evidence = envelope['evidence']
    if not isinstance(raw_evidence, (list, tuple)) or len(raw_evidence) != len(distances):
        raise ValueError('Handoff evidence must align one-to-one with its distances')
    evidence: list[tuple[tuple[RigidPlacement, ...], ...]] = []
    for distance_index, joint_branches in enumerate(raw_evidence):
        if not isinstance(joint_branches, (list, tuple)) or not joint_branches:
            raise ValueError('Each distance must have at least one complete evidence placement')
        branches: list[tuple[RigidPlacement, ...]] = []
        for branch_index, branch in enumerate(joint_branches):
            if not isinstance(branch, (list, tuple)) or len(branch) != len(parents):
                raise ValueError('Each evidence branch must place every parent once')
            placements = tuple(
                _decode_placement(
                    raw,
                    f'evidence distance {distance_index} branch {branch_index} placement {index}',
                )
                for index, raw in enumerate(branch)
            )
            anchor = placements[anchor_index]
            if anchor != RigidPlacement(reflected=anchor.reflected):
                raise ValueError(
                    'Anchor evidence must use zero translation and an identity rotation'
                )
            branches.append(placements)
        evidence.append(tuple(branches))

    return HandoffDocument(
        report_id, batch, anchor_station, probes, tuple(distances), parents, receipt,
        tuple(evidence),
    )


def decode_handoff_bytes(packet: bytes) -> HandoffDocument:
    if not isinstance(packet, bytes):
        raise ValueError('Handoff document must be UTF-8 bytes')
    try:
        data = json.loads(packet.decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Malformed handoff document') from error
    return decode_handoff(data)


def _placement_object(placement: RigidPlacement) -> dict:
    return {
        'cosine': str(placement.cosine),
        'sine': str(placement.sine),
        'tx': str(placement.translation[0]),
        'ty': str(placement.translation[1]),
        'reflected': placement.reflected,
    }


def _parent_object(parent: ParentEvidence) -> dict:
    return {field: getattr(parent, field) for field in _PARENT_FIELDS}


def encode_handoff(document: HandoffDocument) -> bytes:
    payload = {
        'version': HANDOFF_VERSION,
        'report_id': document.report_id,
        'batch': document.batch,
        'anchor_station': document.anchor_station,
        'probes': [[station, name] for station, name in document.probes],
        'distances': [str(distance) for distance in document.distances],
        'parents': [_parent_object(parent) for parent in document.parents],
        'receipt': {
            'report_id': document.receipt.report_id,
            'signed_by': document.receipt.signed_by,
            'signed_at': document.receipt.signed_at.isoformat(),
        },
        'evidence': [
            [
                [_placement_object(placement) for placement in branch]
                for branch in joint_branches
            ]
            for joint_branches in document.evidence
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _selected_distance(document: HandoffDocument, distance: Fraction) -> tuple[RigidPlacement, ...]:
    try:
        index = document.distances.index(distance)
    except ValueError as miss:
        raise _DistanceAbsent(distance) from miss
    return document.evidence[index]


class _DistanceAbsent(LookupError):
    pass


def _cross_check_documents(
    documents: tuple[HandoffDocument, ...]
) -> tuple[dict[int, set[int]], dict[str, int], dict[int, ParentEvidence]]:
    batch = documents[0].batch
    if any(document.batch != batch for document in documents[1:]):
        raise ValueError('Combined handoffs must belong to the same batch')
    station_admissions: dict[str, int] = {}
    provenance: dict[int, ParentEvidence] = {}
    for document in documents:
        for parent in document.parents:
            seen_station = station_admissions.get(parent.station)
            if seen_station is not None and seen_station != parent.admission_id:
                raise ValueError(
                    f'Station {parent.station!r} uses different receipt numbers across handoffs'
                )
            station_admissions[parent.station] = parent.admission_id
            prior = provenance.get(parent.admission_id)
            if prior is not None and prior != parent:
                raise ValueError(
                    f'Admission {parent.admission_id} has inconsistent provenance across handoffs'
                )
            provenance[parent.admission_id] = parent
    # Connectivity over pieces, linked through shared receipt numbers.
    adjacency: dict[int, set[int]] = {index: set() for index in range(len(documents))}
    for index, document in enumerate(documents):
        own = {parent.admission_id for parent in document.parents}
        for other_index, other in enumerate(documents[index + 1:], start=index + 1):
            if own & {parent.admission_id for parent in other.parents}:
                adjacency[index].add(other_index)
                adjacency[other_index].add(index)
    reached = {0}
    pending = [0]
    while pending:
        index = pending.pop()
        for neighbor in adjacency[index] - reached:
            reached.add(neighbor)
            pending.append(neighbor)
    if len(reached) != len(documents):
        raise ValueError('Handoff pieces must form one connected group through shared receipts')
    return adjacency, station_admissions, provenance


def combine_handoffs(
    selections: list | tuple,
) -> Optional[tuple[tuple[RigidPlacement, ...], ...]]:
    """Find one common fixturing for ordered handoff distance selections.

    Each selection is ``(handoff_bytes, squared_distance)``. Structural faults
    raise ``ValueError``; a structurally valid group with no common placement,
    or with a selected distance missing from a piece, returns ``None``.
    """
    if not isinstance(selections, (list, tuple)) or len(selections) < 2:
        raise ValueError('At least two handoff selections are required')
    selections = tuple(selections)
    documents: list[HandoffDocument] = []
    distances: list[Fraction] = []
    for index, selection in enumerate(selections):
        if not isinstance(selection, (list, tuple)) or len(selection) != 2:
            raise ValueError(f'Selection {index} must be a document and a distance')
        packet, raw_distance = selection
        distance = parse_rational(raw_distance)
        if distance < 0:
            raise ValueError('Selected squared distances must be nonnegative')
        documents.append(decode_handoff_bytes(packet))
        distances.append(distance)
    docs = tuple(documents)
    adjacency, _, _ = _cross_check_documents(docs)

    branches: list[tuple[RigidPlacement, ...]] = []
    missing = False
    for document, distance in zip(docs, distances):
        try:
            branches.append(_selected_distance(document, distance))
        except _DistanceAbsent:
            missing = True
    if missing:
        return None

    # Visit pieces in a breadth-first order rooted at the first selection, so
    # every later piece shares at least one already placed receipt.
    order = [0]
    reached = {0}
    cursor = 0
    while cursor < len(order):
        current = order[cursor]
        cursor += 1
        for neighbor in sorted(adjacency[current] - reached):
            reached.add(neighbor)
            order.append(neighbor)

    first = docs[0]
    first_anchor = next(
        index for index, parent in enumerate(first.parents)
        if parent.station == first.anchor_station
    )

    def visit(order_index: int, assigned: dict[int, RigidPlacement]):
        if order_index == len(order):
            return assigned
        piece_index = order[order_index]
        document = docs[piece_index]
        candidate_branches = branches[piece_index]
        if piece_index == 0:
            # The anchor fixes the common frame: zero translation and an
            # identity rotation; the signed face branch keeps the actual face.
            def normalized(candidate):
                globalizer = inverse(candidate[first_anchor])
                return {
                    parent.admission_id: compose(placement, globalizer)
                    for parent, placement in zip(document.parents, candidate)
                }
            trials = (normalized(candidate) for candidate in candidate_branches)
            for trial in trials:
                result = visit(order_index + 1, trial)
                if result is not None:
                    return result
            return None

        anchor_index = next(
            index for index, parent in enumerate(document.parents)
            if parent.admission_id in assigned
        )
        fixed = assigned[document.parents[anchor_index].admission_id]
        for candidate in candidate_branches:
            # The change of basis onto the shared receipt may carry the face
            # already signed into the evidence; the feasibility test is that
            # every shared receipt ends up with one identical final placement.
            transform = compose(inverse(candidate[anchor_index]), fixed)
            trial = dict(assigned)
            for parent, local in zip(document.parents, candidate):
                final = compose(local, transform)
                existing = trial.get(parent.admission_id)
                if existing is not None and existing != final:
                    break
                trial[parent.admission_id] = final
            else:
                result = visit(order_index + 1, trial)
                if result is not None:
                    return result
        return None

    solution = visit(0, {})
    if solution is None:
        return None
    return tuple(
        tuple(solution[parent.admission_id] for parent in document.parents)
        for document in docs
    )
