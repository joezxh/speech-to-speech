"""ULIDs: 48-bit millisecond timestamp + 80 random bits, Crockford base32.

Used for voice ids because they sort by creation time without a second column
(spec §3.11.3). One function, no dependency: the console image should not grow
a package for sixteen lines of bit shuffling.
"""

from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))
