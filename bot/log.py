"""Debug logging to stderr. Off unless POKERBOT_DEBUG=1; errors are always logged. Never raises.

The engine keeps 64 KB of stderr per leg; we stop at 48 KB so the first traceback is never lost.
"""
import os
import sys
import traceback

CAP_BYTES = 48 * 1024
MAX_TRACEBACKS = 10          # full tracebacks per process; later errors get one line each
DEBUG = os.environ.get("POKERBOT_DEBUG") == "1"

_used = 0
_errors = 0


def _write(text):
    global _used
    try:
        if _used >= CAP_BYTES:
            return
        if not text.endswith("\n"):
            text += "\n"
        data = text.encode("utf-8", "replace")[:CAP_BYTES - _used]
        _used += len(data)
        sys.stderr.write(data.decode("utf-8", "ignore"))
        sys.stderr.flush()
    except Exception:
        pass


def log(*parts):
    """Debug line (only with POKERBOT_DEBUG=1)."""
    if DEBUG:
        try:
            _write(" ".join(str(p) for p in parts))
        except Exception:
            pass


def warn(*parts):
    """Always-on line for things that indicate a bug (notices, protocol defects)."""
    try:
        _write(" ".join(str(p) for p in parts))
    except Exception:
        pass


def log_exc(where):
    """Log the current exception: a full traceback for the first few, then one line each."""
    global _errors
    try:
        _errors += 1
        if _errors <= MAX_TRACEBACKS:
            _write(f"[error {_errors} in {where}]\n" + traceback.format_exc())
        else:
            e = sys.exc_info()[1]
            _write(f"[error {_errors} in {where}] {type(e).__name__}: {e}"[:300])
    except Exception:
        pass
