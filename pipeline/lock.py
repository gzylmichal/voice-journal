"""pipeline/lock.py — fcntl.flock-based exclusive pipeline lock.

Prevents concurrent upload processes from racing on the same buffer JSON.
"""

import fcntl
import logging
import time
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)


class PipelineLocked(Exception):
    """Raised when the pipeline lock cannot be acquired within the timeout."""


@contextmanager
def pipeline_lock(lock_dir: Path, timeout_s: float = 120, poll_s: float = 3):
    """Exclusive flock around the pipeline body; retries every poll_s up to timeout_s.

    The lock file is lock_dir/.pipeline.lock.  lock_dir is created if absent.
    Raises PipelineLocked on timeout so callers can exit cleanly, leaving inbox
    files untouched for the next trigger.
    """
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / ".pipeline.lock"
    deadline = time.monotonic() + timeout_s
    fh = open(lock_path, "w")
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PipelineLocked(
                        f"Could not acquire pipeline lock within {timeout_s:.0f}s"
                    )
                time.sleep(min(poll_s, remaining))
        yield
    finally:
        if acquired:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
