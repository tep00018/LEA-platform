"""Short Redis locks around read-modify-write updates of shared learner state.

Two browser tabs (or, later, two API requests) for the same learner can otherwise load the
same mastery or progress record, change it independently and overwrite each other's update.
A lock is held only while state is read, changed and written back, never across an LLM call.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Iterator

logger = logging.getLogger(__name__)

LOCK_PREFIX = "lock:"


class LockBusy(RuntimeError):
    """Another request is still updating the same state."""


def raw_connection(client):
    """The redis-py connection behind a LEARedisClient (or the connection itself)."""
    if client is None:
        return None
    if hasattr(client, "get_redis"):
        return client.get_redis()
    return client if hasattr(client, "lock") else None


@contextlib.contextmanager
def redis_lock(client, name: str, *, timeout: float = 30, wait: float = 10,
               keep_alive: bool = False) -> Iterator[None]:
    """Hold ``lock:<name>`` for the block.

    ``timeout`` is how long the lock survives if the holder dies; ``wait`` is how long to
    wait for it. With ``keep_alive`` a background thread renews the lock every
    ``timeout / 3`` seconds while the block runs, so slow work (model calls) never outlives
    it, yet a crashed process releases it within ``timeout``. Without Redis (file-backed
    tests) this is a no-op.
    """
    conn = raw_connection(client)
    if conn is None:
        yield
        return
    # thread_local=False: the renewal thread must see the token this thread acquired with
    lock = conn.lock(LOCK_PREFIX + name, timeout=timeout, blocking_timeout=wait, thread_local=False)
    if not lock.acquire():
        raise LockBusy(f"{name} is busy")
    stop = threading.Event()
    renewer = None
    if keep_alive:
        def renew():
            while not stop.wait(timeout / 3):
                try:
                    lock.reacquire()
                except Exception as e:
                    logger.warning("Could not renew lock %s: %s", name, e)
                    return
        renewer = threading.Thread(target=renew, name=f"lock-renew-{name}", daemon=True)
        renewer.start()
    try:
        yield
    finally:
        stop.set()
        if renewer is not None:
            renewer.join(timeout=1)
        try:
            lock.release()
        except Exception as e:  # expired while held: the update still completed
            logger.warning("Lock %s expired before release: %s", name, e)
