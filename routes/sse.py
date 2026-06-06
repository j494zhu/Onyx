import json
import time
from datetime import datetime, timezone

import gevent
from flask import Blueprint, Response, stream_with_context
from flask import current_app
from flask_login import login_required, current_user

from routes.common import (
    format_sse, user_event_channel,
    SSE_EVENT_NAMES, EVENT_HEARTBEAT,
)

bp = Blueprint('sse', __name__)


@bp.route('/api/events', methods=['GET'])
@login_required
def stream_events():
    user_id = current_user.id
    channel = user_event_channel(user_id)
    sse_heartbeat_seconds = current_app.config.get('SSE_HEARTBEAT_SECONDS', 25)
    redis_client = getattr(current_app, 'redis_client', None)

    @stream_with_context
    def event_stream():
        pubsub = None
        last_heartbeat = time.monotonic()
        current_app.logger.info('SSE connect user_id=%s channel=%s', user_id, channel)
        try:
            if redis_client is None:
                current_app.logger.warning('SSE stream unavailable: Redis unavailable user_id=%s', user_id)
                yield format_sse(EVENT_HEARTBEAT, {'status': 'redis_unavailable'})
                return

            pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(channel)

            while True:
                message = pubsub.get_message(timeout=1.0)
                if message and message.get('type') == 'message':
                    try:
                        payload = json.loads(message.get('data') or '{}')
                    except Exception:
                        payload = {}

                    event_name = payload.get('event')
                    event_data = payload.get('data', {})
                    if event_name in SSE_EVENT_NAMES:
                        yield format_sse(event_name, event_data)
                        last_heartbeat = time.monotonic()

                if time.monotonic() - last_heartbeat >= sse_heartbeat_seconds:
                    yield format_sse(EVENT_HEARTBEAT, {'ts': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')})
                    last_heartbeat = time.monotonic()
                gevent.sleep(0.01)
        except GeneratorExit:
            current_app.logger.info('SSE disconnect user_id=%s channel=%s reason=client_closed', user_id, channel)
        except Exception as e:
            current_app.logger.exception('SSE stream error user_id=%s error=%s', user_id, str(e))
        finally:
            if pubsub is not None:
                try:
                    pubsub.unsubscribe(channel)
                    pubsub.close()
                except Exception:
                    pass
            current_app.logger.info('SSE cleanup user_id=%s channel=%s', user_id, channel)

    response = Response(event_stream(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response
