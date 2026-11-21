import hashlib
from dataclasses import dataclass

from intake.decode import DecodedPacket, decode_packet
from intake.identity import VerifiedIdentity, verify_identity
from intake.inbox import InboxEntry, IntakeInbox
from station.markers import NamedPoints, require_label


@dataclass(frozen=True)
class Admission:
    admission_id: int
    identity: VerifiedIdentity
    packet: bytes
    received_from: str
    packet_sha256: str
    allow_flip: bool
    markers: NamedPoints
    probes: NamedPoints


def _admission(entry: InboxEntry, decoded: DecodedPacket) -> Admission:
    return Admission(
        entry.admission_id, entry.identity, entry.packet, entry.received_from,
        entry.packet_sha256, decoded.allow_flip, decoded.markers, decoded.probes,
    )


def receive_packet(inbox: IntakeInbox, packet: bytes, *, received_from: str) -> Admission:
    source = require_label(received_from, 'Intake source')
    decoded = decode_packet(packet)
    identity = verify_identity(decoded)
    digest = hashlib.sha256(packet).hexdigest()
    entry = inbox.append_admission(identity, packet, source, digest)
    return _admission(entry, decoded)


def load_admission(inbox: IntakeInbox, admission_id: int) -> Admission:
    if type(admission_id) is not int or not 0 < admission_id < 2**63:
        raise ValueError('Invalid admission number')
    entry = inbox.read_admission(admission_id)
    if entry is None:
        raise LookupError(f'Unknown admission {admission_id}')
    decoded = decode_packet(entry.packet)
    if verify_identity(decoded) != entry.identity:
        raise ValueError('Stored admission identity does not match the packet')
    return _admission(entry, decoded)
