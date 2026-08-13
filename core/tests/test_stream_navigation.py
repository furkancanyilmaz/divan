import io
import json
from unittest import mock

from support import HTTPTestCase, app


class _ProviderStream:

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _DisconnectAfterHeaders(io.BytesIO):
    """Let HTTP headers through, then model a client closing the SSE socket."""

    def __init__(self):
        super().__init__()
        self.write_count = 0

    def write(self, data):
        self.write_count += 1
        if self.write_count > 1:
            raise BrokenPipeError("mobile view left the stream")
        return super().write(data)


class BackgroundAnswerPersistenceTests(HTTPTestCase):

    def test_chat_answer_is_saved_after_the_sse_client_disconnects(self):
        conv_id = self.conversation(title="Arka plan yanıtı")
        payload = json.dumps({
            "conv_id": conv_id,
            "message": "Ben ana konuşma ekranından ayrılıyorum.",
        }, ensure_ascii=False).encode("utf-8")
        handler = object.__new__(app.Handler)
        handler.path = "/api/chat"
        handler.command = "POST"
        handler.request_version = "HTTP/1.1"
        handler.requestline = "POST /api/chat HTTP/1.1"
        handler.client_address = ("127.0.0.1", 0)
        handler.server = None
        handler.close_connection = False
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "Host": "127.0.0.1:{}".format(app.PORT),
        }
        handler.rfile = io.BytesIO(payload)
        handler.wfile = _DisconnectAfterHeaders()

        deltas = iter([
            ("message", "birinci"),
            ("message", "ikinci"),
            ("message", "bitti"),
        ])

        def provider_delta(_event_name, chunk, _provider):
            if chunk == "birinci":
                return "text", "Yanıt "
            if chunk == "ikinci":
                return "text", "arka planda tamamlandı."
            return "done", ""

        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "test"})), \
                mock.patch.object(
                    app, "open_provider_url",
                    return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events",
                    return_value=deltas), \
                mock.patch.object(
                    app, "provider_stream_delta",
                    side_effect=provider_delta):
            handler.do_POST()

        messages = self.rows(
            "SELECT role,content FROM messages WHERE conv=? ORDER BY id",
            (conv_id,),
        )
        self.assertEqual(
            [(row["role"], row["content"]) for row in messages],
            [
                ("user", "Ben ana konuşma ekranından ayrılıyorum."),
                ("assistant", "Yanıt arka planda tamamlandı."),
            ],
        )
        self.assertGreaterEqual(handler.wfile.write_count, 2)

