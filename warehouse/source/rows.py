from dataclasses import dataclass


@dataclass(frozen=True)
class RowIdentity:
    batch_id: str
    row_id: str


@dataclass(frozen=True)
class SourceRow:
    identity: RowIdentity
    origin: str
    liters: int


@dataclass(frozen=True)
class SealedManifest:
    batch_id: str
    station: str
    day: str
    rows: tuple[SourceRow, ...]


def encode_liters(liters: int) -> bytes:
    if type(liters) is not int or liters < 0:
        raise ValueError('liters must be a nonnegative integer')
    width = max(1, (liters.bit_length() + 7) // 8)
    return liters.to_bytes(width, 'big')


def decode_liters(encoded: bytes) -> int:
    if not isinstance(encoded, bytes) or not encoded:
        raise ValueError('invalid stored liters')
    return int.from_bytes(encoded, 'big')
