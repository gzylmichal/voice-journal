import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import multiprocessing
import tempfile

import pytest

from pipeline.lock import PipelineLocked, pipeline_lock


# ---------------------------------------------------------------------------
# Worker functions — must be module-level for multiprocessing pickling.
# ---------------------------------------------------------------------------

def _worker_hold_lock(lock_dir_str, ready_event, release_event):
    """Acquire the lock, signal ready, then wait until told to release."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from pipeline.lock import pipeline_lock
    with pipeline_lock(Path(lock_dir_str), timeout_s=10, poll_s=0.05):
        ready_event.set()
        release_event.wait(timeout=10)


def _worker_try_lock(lock_dir_str, result_queue, timeout_s):
    """Try to acquire the lock and report 'acquired' or 'locked'."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from pipeline.lock import pipeline_lock, PipelineLocked
    try:
        with pipeline_lock(Path(lock_dir_str), timeout_s=timeout_s, poll_s=0.05):
            result_queue.put("acquired")
    except PipelineLocked:
        result_queue.put("locked")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_exclusive_lock_blocks_concurrent():
    """A second process cannot acquire the lock while the first holds it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_dir = Path(tmpdir)
        ctx = multiprocessing.get_context("fork")
        ready = ctx.Event()
        release = ctx.Event()
        result = ctx.Queue()

        holder = ctx.Process(target=_worker_hold_lock, args=(str(lock_dir), ready, release))
        holder.start()
        assert ready.wait(timeout=5), "holder never acquired lock"

        waiter = ctx.Process(target=_worker_try_lock, args=(str(lock_dir), result, 0.3))
        waiter.start()
        waiter.join(timeout=5)

        outcome = result.get_nowait()
        release.set()
        holder.join(timeout=5)

        assert outcome == "locked", f"expected 'locked', got {outcome!r}"


def test_lock_available_after_release():
    """After the holder exits, a new process can acquire the lock."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_dir = Path(tmpdir)
        ctx = multiprocessing.get_context("fork")
        ready = ctx.Event()
        release = ctx.Event()
        result = ctx.Queue()

        holder = ctx.Process(target=_worker_hold_lock, args=(str(lock_dir), ready, release))
        holder.start()
        assert ready.wait(timeout=5), "holder never acquired lock"
        release.set()
        holder.join(timeout=5)

        waiter = ctx.Process(target=_worker_try_lock, args=(str(lock_dir), result, 5))
        waiter.start()
        waiter.join(timeout=10)

        outcome = result.get_nowait()
        assert outcome == "acquired", f"expected 'acquired', got {outcome!r}"


def test_single_process_acquire_release(tmp_path):
    """Basic: lock acquisition and release works without error."""
    with pipeline_lock(tmp_path, timeout_s=1):
        pass  # acquired and released cleanly


def test_timeout_raises_pipeline_locked():
    """PipelineLocked is raised when the lock cannot be acquired in time."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_dir = Path(tmpdir)
        ctx = multiprocessing.get_context("fork")
        ready = ctx.Event()
        release = ctx.Event()

        holder = ctx.Process(target=_worker_hold_lock, args=(str(lock_dir), ready, release))
        holder.start()
        assert ready.wait(timeout=5), "holder never acquired lock"

        with pytest.raises(PipelineLocked):
            with pipeline_lock(lock_dir, timeout_s=0.2, poll_s=0.05):
                pass

        release.set()
        holder.join(timeout=5)
