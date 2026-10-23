import json
import hashlib
import asyncio
from typing import Any, Dict, Tuple, Optional


def get_canonical_bytes(obj: Any) -> bytes:
    """
    Recursively sorts dictionary keys and serializes compact JSON without whitespace.
    Ensures UTF-8 encoding.
    """
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def get_canonical_hash(obj: Any) -> str:
    """
    Computes SHA-256 hash of canonical JSON bytes.
    """
    return hashlib.sha256(get_canonical_bytes(obj)).hexdigest()


class InFlightManager:
    """
    Coordinates concurrent identical requests so that only one executes
    while others await its completion and retrieve the committed result.
    """
    def __init__(self):
        self._locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def get_lock(self, principal: str, message_id: str) -> asyncio.Lock:
        key = (principal, message_id)
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    async def release_lock(self, principal: str, message_id: str):
        key = (principal, message_id)
        async with self._global_lock:
            if key in self._locks and not self._locks[key].locked():
                del self._locks[key]


in_flight_manager = InFlightManager()
