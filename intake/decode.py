import json
from dataclasses import dataclass

from station.markers import NamedPoints, collect_named_points, require_label


@dataclass(frozen=True)
class PacketIdentity:
    batch: str
    station: str
    revision: int
    issue_id: int


@dataclass(frozen=True)
class DecodedPacket:
    outer: PacketIdentity
    inner: PacketIdentity
    allow_flip: bool
    markers: NamedPoints
    probes: NamedPoints


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate packet field {key!r}')
        result[key] = value
    return result


def _fields(value: object, keys: set[str], role: str) -> dict:
    if not isinstance(value, dict) or value.keys() != keys:
        raise ValueError(f'Invalid fields in {role}')
    return value


def _identity(value: object) -> PacketIdentity:
    data = _fields(value, {'batch', 'station', 'revision', 'issue_id'}, 'packet identity')
    batch = require_label(data['batch'], 'Batch')
    station = require_label(data['station'], 'Station')
    revision, issue_id = data['revision'], data['issue_id']
    if any(type(number) is not int or not 0 < number < 2**63 for number in (revision, issue_id)):
        raise ValueError('Invalid revision or issue number in packet')
    return PacketIdentity(batch, station, revision, issue_id)


def _decode_points(value: object) -> NamedPoints:
    if not isinstance(value, dict):
        raise ValueError('Packet point catalog must be a JSON object')
    return collect_named_points(list(value.items()))


def decode_packet(packet: bytes) -> DecodedPacket:
    if not isinstance(packet, bytes):
        raise ValueError('Packet must be UTF-8 bytes')
    try:
        data = json.loads(packet.decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Malformed station packet') from error
    envelope = _fields(data, {'version', 'identity', 'body'}, 'packet envelope')
    if type(envelope['version']) is not int or envelope['version'] != 1:
        raise ValueError('Unsupported packet version')
    body = _fields(envelope['body'], {'identity', 'allow_flip', 'markers', 'probes'}, 'packet body')
    if type(body['allow_flip']) is not bool:
        raise ValueError('Packet face permission must be a boolean')
    return DecodedPacket(
        _identity(envelope['identity']), _identity(body['identity']), body['allow_flip'],
        _decode_points(body['markers']), _decode_points(body['probes']),
    )
