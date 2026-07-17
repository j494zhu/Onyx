import json

from routes.common import (
    publish_user_event, format_sse, user_event_channel,
    EVENT_ENTRY_CREATED,
)


def test_publish_unknown_event_rejected(app, fake_redis):
    ok = publish_user_event(1, 'made_up_event', {'x': 1})
    assert ok is False
    assert fake_redis.published == []


def test_publish_skipped_when_redis_unavailable(app):
    # 测试环境下 REDIS_URL 不可达，app.redis_client 应为 None
    assert app.redis_client is None
    assert publish_user_event(1, EVENT_ENTRY_CREATED, {'id': 1}) is False


def test_publish_known_event(app, fake_redis):
    payload = {'id': 5, 'desc': 'x', 'start_time': '10:00',
               'end_time': '11:00', 'timestamp': None}
    ok = publish_user_event(42, EVENT_ENTRY_CREATED, payload)
    assert ok is True

    channel, message = fake_redis.published[0]
    assert channel == 'onyx:user:42'
    body = json.loads(message)
    assert body['event'] == EVENT_ENTRY_CREATED
    assert body['data'] == payload
    assert 'sent_at' in body


def test_user_event_channel_uses_prefix(app):
    assert user_event_channel(7) == 'onyx:user:7'


def test_format_sse_wire_format():
    out = format_sse('heartbeat', {'ts': 1})
    assert out == 'event: heartbeat\ndata: {"ts": 1}\n\n'


def test_entry_mutations_publish_events(auth_client, fake_redis):
    # 创建和删除记录都应发布对应的 SSE 事件
    auth_client.post('/', data={
        'desc': 'x', 'start_time': '10:00', 'end_time': '11:00',
    })
    assert len(fake_redis.published) == 1
    created = json.loads(fake_redis.published[0][1])
    assert created['event'] == 'entry_created'
    entry_id = created['data']['id']

    auth_client.post(f'/api/entries/{entry_id}')
    deleted = json.loads(fake_redis.published[1][1])
    assert deleted['event'] == 'entry_deleted'
    assert deleted['data'] == {'id': entry_id}


def test_sse_stream_requires_login(client):
    resp = client.get('/api/events')
    assert resp.status_code == 302


def test_sse_stream_degrades_without_redis(auth_client):
    resp = auth_client.get('/api/events')
    assert resp.status_code == 200
    assert resp.mimetype == 'text/event-stream'
    assert 'redis_unavailable' in resp.get_data(as_text=True)
