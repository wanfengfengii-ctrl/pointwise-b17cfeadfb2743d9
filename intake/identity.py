from dataclasses import dataclass

from intake.decode import DecodedPacket


@dataclass(frozen=True)
class VerifiedIdentity:
    batch: str
    station: str
    revision: int
    issue_id: int


def verify_identity(decoded: DecodedPacket) -> VerifiedIdentity:
    if decoded.outer != decoded.inner:
        raise ValueError('Packet envelope identity does not match the body identity')
    identity = decoded.inner
    return VerifiedIdentity(identity.batch, identity.station, identity.revision, identity.issue_id)
