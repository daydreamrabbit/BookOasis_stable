"""Selective v2.8.3 worker shutdown hook; launch options remain with the caller.

Gunicorn discovers this file from the application working directory. Run the
registered progress/core cleanup before Python waits for non-daemon request
threads (including ThreadPoolExecutor's interpreter-exit join).
"""
import atexit
import os
import sys
import threading

# entrypoint.sh allows 10s after signalling the web server; Dockerfile gives
# Gunicorn 15s graceful shutdown. Reserve at least 2s of the shorter window.
WORKER_EXIT_CLEANUP_TIMEOUT = 8


def worker_exit(server, worker):
    # Gunicorn can also call this hook in the master for an already dead worker.
    if os.getpid() != worker.pid or not getattr(worker, 'booted', False):
        return

    # Also respect a shorter Gunicorn grace period supplied by the launcher.
    # This budget starts at hook entry, not SIGTERM: time already spent draining
    # requests can still let the parent deadline win. It is not a flush guarantee.
    cleanup_timeout = WORKER_EXIT_CLEANUP_TIMEOUT
    graceful_timeout = getattr(getattr(worker, 'cfg', None), 'graceful_timeout', None)
    if isinstance(graceful_timeout, (int, float)) and graceful_timeout > 0:
        cleanup_timeout = min(cleanup_timeout, graceful_timeout / 2)
    watchdog = threading.Timer(cleanup_timeout, lambda: os._exit(0))
    watchdog.daemon = True
    watchdog.start()
    try:
        # Core registers progress flush -> scanner/scheduler stop -> pool close.
        # Use the registered hooks rather than importing core a second time.
        atexit._run_exitfuncs()
    except Exception as error:
        print(f"[Gunicorn] worker_exit cleanup failed: {error}", file=sys.stderr)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(0)
