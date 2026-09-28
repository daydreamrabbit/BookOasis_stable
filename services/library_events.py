"""Cross-process change notifications; no periodic database revision reads."""
import json
import threading
import time

CHANNEL = 'bookoasis:library-changed'
# Gunicorn currently has 12 threads: reserve capacity for ordinary requests.
STREAM_SLOTS = threading.BoundedSemaphore(4)


def publish_library_change(db_type, revision):
    from utils.redis_helper import get_redis_client
    client = get_redis_client()
    if client is not None:
        client.publish(CHANNEL, json.dumps({'type': db_type, 'revision': str(revision)}))


def library_event_stream(client):
    from services.series_service import _read_shared_books_cache_epoch
    kinds = ('general', 'adult', 'audiobook', 'video')
    subscription = client.pubsub()
    try:
        subscription.subscribe(CHANNEL)
        # Wait for subscribe acknowledgement BEFORE reading snapshot; avoid a lost event.
        subscription.get_message(timeout=5)
        revisions = {kind: str(_read_shared_books_cache_epoch(kind) or '') for kind in kinds}
        yield 'retry: 30000\nevent: snapshot\ndata: ' + json.dumps(revisions) + '\n\n'
        started = time.monotonic()
        while time.monotonic() - started < 600:
            message = subscription.get_message(ignore_subscribe_messages=True, timeout=15)
            if message and message['type'] == 'message':
                event = json.loads(message['data'])
                if event.get('type') in kinds:
                    yield 'event: changed\ndata: ' + json.dumps(event) + '\n\n'
            else:
                yield ': keepalive\n\n'
    finally:
        subscription.close()
