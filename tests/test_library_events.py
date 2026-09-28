from unittest.mock import Mock


def test_subscription_snapshot_change_and_cleanup(monkeypatch):
    from services.library_events import library_event_stream, CHANNEL
    monkeypatch.setattr('services.series_service._read_shared_books_cache_epoch', lambda kind:'1')
    client=Mock(); subscription=client.pubsub.return_value
    subscription.get_message.side_effect=[{'type':'subscribe'}, {'type':'message','data':'{"type":"general","revision":"2"}'}, None]
    stream=library_event_stream(client)
    assert 'event: snapshot' in next(stream)
    subscription.subscribe.assert_called_once_with(CHANNEL)
    assert 'event: changed' in next(stream)
    assert next(stream)==': keepalive\n\n'
    stream.close(); subscription.close.assert_called_once()


def test_publish_cross_process_notification(monkeypatch):
    from services.library_events import publish_library_change, CHANNEL
    client=Mock(); monkeypatch.setattr('utils.redis_helper.get_redis_client',lambda:client)
    publish_library_change('general','2')
    client.publish.assert_called_once_with(CHANNEL, '{"type": "general", "revision": "2"}')
