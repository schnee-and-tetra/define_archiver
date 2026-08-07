import struct
import time
from collections.abc import Generator
from contextlib import contextmanager


class StorageLockTimeoutError(Exception):
    """Raised when the lock cannot be acquired within the timeout period."""


@contextmanager
def storage_lock(
    storage,
    lock_key: str,
    lock_ttl: float = 10.0,
    timeout: float = 5.0,
    retry_interval: float = 0.1,
) -> Generator[None, None, None]:
    """
    A high-performance pseudo-distributed lock for Dify using raw bytes comparison.

    Args:
        storage: The Dify session.storage object.
        lock_key: The storage key used for lock management.
        lock_ttl: Lock validity duration in seconds.
        timeout: Maximum duration to wait to acquire the lock.
        retry_interval: Time interval between retry attempts.
    """
    start_time = time.time()
    locked = False

    while time.time() - start_time < timeout:
        current_time = time.time()
        # Convert to millisecond integer timestamps
        current_ms = int(current_time * 1000)
        expires_at_ms = int((current_time + lock_ttl) * 1000)

        # '>q' packs signed 64-bit integer into 8 bytes (Big-Endian).
        # Big-Endian allows direct binary comparison (bytes1 > bytes2 works perfectly).
        current_ms_bytes = struct.pack(">q", current_ms)
        expires_at_bytes = struct.pack(">q", expires_at_ms)

        try:
            current_lock_bytes = storage.get(lock_key)
        except Exception:  # noqa: BLE001 (Dify storage throws generic Exception if key missing)
            current_lock_bytes = None

        # Check expiration using raw bytes comparison (No decode needed!)
        if current_lock_bytes is None or current_ms_bytes > current_lock_bytes:
            # Try to acquire the lock by storing the 8-byte timestamp
            storage.set(lock_key, expires_at_bytes)

            # Double-check for race conditions
            time.sleep(0.01)
            if storage.get(lock_key) == expires_at_bytes:
                locked = True
                break

        time.sleep(retry_interval)

    if not locked:
        raise StorageLockTimeoutError(
            f"Failed to acquire lock within {timeout} seconds."
        )

    try:
        yield
    finally:
        # Securely release the lock using bytes comparison
        current_lock_bytes = storage.get(lock_key)
        if current_lock_bytes == expires_at_bytes:
            storage.set(lock_key, b"")
