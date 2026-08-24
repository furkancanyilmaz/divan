import hashlib
import json
import re
import struct
import unittest
from pathlib import Path
from unittest import mock

from support import HTTPTestCase, PROJECT_DIR, app


IMAGERY_DIR = Path(PROJECT_DIR, "assets", "imagery")
MANIFEST_PATH = IMAGERY_DIR / "manifest.json"
CARD_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_CARD_BYTES = 500 * 1024
MAX_DECK_BYTES = 8 * 1024 * 1024


def webp_chunks(raw):
    """Return RIFF chunks while rejecting truncation and trailing data."""
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
        raise AssertionError("not a WebP RIFF container")
    if struct.unpack("<I", raw[4:8])[0] + 8 != len(raw):
        raise AssertionError("WebP RIFF length does not match the file")
    chunks = []
    offset = 12
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise AssertionError("truncated WebP chunk header")
        kind = raw[offset:offset + 4]
        size = struct.unpack("<I", raw[offset + 4:offset + 8])[0]
        start = offset + 8
        end = start + size
        if end > len(raw):
            raise AssertionError("truncated WebP chunk body")
        chunks.append((kind, raw[start:end]))
        offset = end + (size & 1)
    if offset != len(raw):
        raise AssertionError("invalid WebP padding")
    return chunks


def lossy_webp_size(payload):
    if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
        raise AssertionError("invalid VP8 key frame")
    width = struct.unpack("<H", payload[6:8])[0] & 0x3FFF
    height = struct.unpack("<H", payload[8:10])[0] & 0x3FFF
    return width, height


class FreudImageryManifestTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.cards = cls.manifest["cards"]

    def test_manifest_is_an_exact_bounded_24_card_allowlist(self):
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["source_kind"], "ai_generated_local")
        self.assertEqual(self.manifest["therapist_allowlist"], ["freud"])
        self.assertEqual(self.manifest["card_count"], 24)
        self.assertEqual(len(self.cards), 24)

        ids = [card["id"] for card in self.cards]
        files = [card["file"] for card in self.cards]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(files), len(set(files)))
        self.assertTrue(all(CARD_ID_RE.fullmatch(card_id) for card_id in ids))
        self.assertEqual(files, [card_id + ".webp" for card_id in ids])
        self.assertEqual(
            set(files),
            {path.name for path in IMAGERY_DIR.glob("*.webp")},
        )
        self.assertFalse(any(path.is_symlink() for path in IMAGERY_DIR.iterdir()))

        policy = self.manifest["presentation_policy"]
        self.assertEqual(policy, {
            "descriptions_are_literal": True,
            "psychological_labels": False,
            "max_model_suggestions": 3,
            "suggestions_are_never_selected": True,
            "explicit_user_selection_required": True,
        })
        self.assertEqual(self.manifest["visual_policy"], {
            "people_or_faces": False,
            "text_or_logos": False,
            "violence_or_sexuality": False,
            "horror_or_threat": False,
        })

    def test_every_card_hash_size_mime_dimensions_and_metadata_are_exact(self):
        total = 0
        for card in self.cards:
            with self.subTest(card=card["id"]):
                self.assertEqual(set(card), {
                    "id", "file", "category", "title", "description",
                    "alt", "mime", "width", "height", "bytes", "sha256",
                })
                self.assertEqual(card["mime"], "image/webp")
                self.assertEqual((card["width"], card["height"]), (768, 512))
                self.assertTrue(SHA256_RE.fullmatch(card["sha256"]))
                self.assertGreater(card["bytes"], 1000)
                self.assertLessEqual(card["bytes"], MAX_CARD_BYTES)

                raw = (IMAGERY_DIR / card["file"]).read_bytes()
                self.assertEqual(len(raw), card["bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), card["sha256"])
                chunks = webp_chunks(raw)
                self.assertEqual(
                    [kind for kind, _ in chunks],
                    [b"VP8 "],
                    "EXIF/XMP/ICC/animation or an unexpected chunk was packaged",
                )
                self.assertEqual(
                    lossy_webp_size(chunks[0][1]),
                    (card["width"], card["height"]),
                )
                total += len(raw)
        self.assertLessEqual(total, MAX_DECK_BYTES)

    def test_card_copy_is_literal_accessible_and_non_diagnostic(self):
        forbidden = (
            "bastırılmış", "bilinçdışı", "istismar", "travma", "tanı",
            "teşhis", "kişilik testi", "projektif", "rorschach",
            "gizli anlam", "psikolojik anlam", "işaret eder",
        )
        for card in self.cards:
            with self.subTest(card=card["id"]):
                for field in ("category", "title", "description", "alt"):
                    value = card[field]
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())
                    self.assertEqual(value, value.strip())
                self.assertGreaterEqual(len(card["alt"]), 12)
                self.assertLessEqual(len(card["alt"]), 180)
                self.assertLessEqual(len(card["description"]), 300)
                folded = app._safety_fold(" ".join(
                    card[field] for field in
                    ("title", "description", "alt")))
                for marker in forbidden:
                    self.assertNotIn(
                        app._safety_fold(marker), folded,
                        "card copy must describe only visible content",
                    )
                self.assertNotIn("http://", folded)
                self.assertNotIn("https://", folded)


class FreudImageryHTTPContractTests(HTTPTestCase):
    """Clinical, consent, privacy and lifecycle acceptance for the deck."""

    def post(self, path, **payload):
        return self.request("POST", path, payload)

    def imagery(self, conv_id):
        status, body, headers = self.request(
            "GET", "/api/freud-imagery?conv_id={}".format(conv_id))
        return status, body, headers

    def ready_freud(self):
        conv_id = self.conversation(mode="terapi", therapist="freud")
        status, body, _ = self.post(
            "/api/session-meta",
            conv_id=conv_id,
            precheck_done=True,
            safety_ok=True,
            anxiety_start=3,
            intensity_limit=8,
        )
        self.assertEqual(status, 200, body)
        method = next(
            row for row in app.method_records("freud")
            if row["node_id"] == "freud:method:free-association")
        status, body, _ = self.post(
            "/api/technique-run",
            conv_id=conv_id,
            action="propose",
            method_key=method["key"],
            intensity=3,
        )
        self.assertEqual(status, 200, body)
        run = body["run"]
        status, body, _ = self.post(
            "/api/technique-run",
            conv_id=conv_id,
            id=run["id"],
            action="consent",
            confirmed=True,
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["run"]["status"], "active")
        return conv_id, body["run"]

    def consent_deck(self, conv_id, request_id="deck-consent-0001",
                     stop_signal="DUR"):
        status, body, headers = self.post(
            "/api/freud-imagery/selection",
            action="consent",
            conv_id=conv_id,
            request_id=request_id,
            orientation_confirmed=True,
            frame_confirmed=True,
            reality_confirmed=True,
            stop_signal=stop_signal,
        )
        return status, body, headers

    def select_card(self, conv_id, revision, request_id="deck-select-0001",
                    card_id="doorway", association="Açık bir geçidi anımsattı."):
        return self.post(
            "/api/freud-imagery/selection",
            action="select",
            conv_id=conv_id,
            request_id=request_id,
            revision=revision,
            card_id=card_id,
            association=association,
        )

    def add_user_message(self, conv_id, content):
        with app.db() as connection:
            connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user',?,?)",
                (conv_id, content, app.now()),
            )

    def test_deck_requires_an_explicit_open_and_explicit_frame_consent(self):
        conv_id = self.conversation(mode="terapi", therapist="freud")
        with mock.patch.object(
                app, "generate_freud_imagery_suggestions",
                side_effect=AssertionError("opening must not call a model")):
            status, body, _ = self.imagery(conv_id)
        self.assertEqual(status, 200, body)
        deck = body["imagery"]
        self.assertFalse(deck["available"])
        self.assertEqual(deck["blocked_reason"], "free_association_required")
        self.assertEqual(deck["cards"], [])
        self.assertIsNone(deck["session"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_sessions")["n"], 0)

        conv_id, _ = self.ready_freud()
        for _ in range(2):
            status, body, _ = self.imagery(conv_id)
            self.assertEqual(status, 200, body)
            deck = body["imagery"]
            self.assertTrue(deck["available"])
            self.assertEqual(len(deck["cards"]), 24)
            self.assertIsNone(deck["session"])
            self.assertIsNone(deck["selection"])
            self.assertTrue(deck["capabilities"]["consent"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_sessions")["n"], 0)

        status, body, _ = self.post(
            "/api/freud-imagery/selection",
            action="consent",
            conv_id=conv_id,
            request_id="deck-consent-reject-0001",
            orientation_confirmed=True,
            frame_confirmed=False,
            reality_confirmed=True,
            stop_signal="DUR",
        )
        self.assertEqual(status, 409, body)
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_sessions")["n"], 0)

        status, body, _ = self.consent_deck(conv_id)
        self.assertEqual(status, 200, body)
        deck = body["imagery"]
        self.assertEqual(deck["session"]["status"], "active")
        self.assertTrue(deck["session"]["orientation_confirmed"])
        self.assertTrue(deck["session"]["frame_confirmed"])
        self.assertTrue(deck["session"]["reality_confirmed"])
        self.assertEqual(deck["session"]["stop_signal"], "DUR")
        self.assertFalse(deck["capabilities"]["consent"])

    def test_only_open_freud_main_therapy_is_in_scope(self):
        out_of_scope = [
            self.conversation(mode="ders", therapist="freud"),
            self.conversation(mode="terapi", therapist="jung"),
            self.conversation(
                mode="terapi", therapist="freud", submode="pratik"),
            self.conversation(mode="terapi", therapist="freud", ended=1),
        ]
        archived = self.conversation(mode="terapi", therapist="freud")
        guest = self.conversation(mode="terapi", therapist="freud")
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET archived_at=? WHERE id=?",
                (app.now(), archived),
            )
            connection.execute(
                "UPDATE conversations SET is_guest=1 WHERE id=?", (guest,))
        out_of_scope.extend((archived, guest))
        for conv_id in out_of_scope:
            with self.subTest(conv_id=conv_id):
                status, body, _ = self.imagery(conv_id)
                self.assertEqual(status, 404, body)

        normal, _ = self.ready_freud()
        app.set_setting("guest_mode", "1")
        status, body, _ = self.imagery(normal)
        self.assertEqual(status, 404, body)

    def test_static_assets_are_allowlisted_verified_and_pin_gated(self):
        card = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["cards"][0]
        path = "/assets/imagery/{}".format(card["file"])
        status, _, headers = self.request("GET", path)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/webp")
        self.assertEqual(headers["Content-Length"], str(card["bytes"]))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "private, max-age=86400")

        for suffix in (
                "manifest.json", "../manifest.json",
                "%2e%2e%2fmanifest.json", "%2Fetc%2Fpasswd",
                card["file"] + "/extra", "unknown.webp"):
            with self.subTest(suffix=suffix):
                status, body, _ = self.request(
                    "GET", "/assets/imagery/" + suffix)
                self.assertEqual(status, 404, body)

        pin = "imagery-lock-pin"
        app.set_setting("pin_hash", app.pin_hash(pin))
        status, body, _ = self.request("GET", path)
        self.assertEqual(status, 423, body)
        cookie = self.unlock_cookie(pin)
        status, _, _ = self.request(
            "GET", path, headers={"Cookie": cookie})
        self.assertEqual(status, 200)

    def test_consent_and_selection_replays_are_idempotent_and_collision_safe(self):
        first, _ = self.ready_freud()
        request_id = "global-consent-0001"
        status, first_body, _ = self.consent_deck(first, request_id)
        self.assertEqual(status, 200, first_body)
        first_revision = first_body["imagery"]["session"]["revision"]

        status, replay, _ = self.consent_deck(first, request_id)
        self.assertEqual(status, 200, replay)
        self.assertEqual(
            replay["imagery"]["session"]["revision"], first_revision)
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_sessions")["n"], 1)

        status, body, _ = self.consent_deck(
            first, request_id, stop_signal="BEKLE")
        self.assertEqual(status, 409, body)

        second, _ = self.ready_freud()
        status, body, _ = self.consent_deck(second, request_id)
        self.assertEqual(status, 409, body)
        self.assertNotEqual(status, 500)
        self.assertIsNone(self.row(
            "SELECT id FROM freud_imagery_sessions WHERE conv=?", (second,)))

        status, selected, _ = self.select_card(
            first, first_revision, request_id="global-select-0001")
        self.assertEqual(status, 200, selected)
        selected_revision = selected["imagery"]["session"]["revision"]
        status, replay, _ = self.select_card(
            first, first_revision, request_id="global-select-0001")
        self.assertEqual(status, 200, replay)
        self.assertEqual(
            replay["imagery"]["session"]["revision"], selected_revision)
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_steps")["n"], 1)

        status, body, _ = self.select_card(
            first, first_revision,
            request_id="global-select-0001",
            association="Aynı kimlikle değiştirilmiş içerik.")
        self.assertEqual(status, 409, body)
        self.assertEqual(
            self.row("SELECT association FROM freud_imagery_steps")
            ["association"],
            "Açık bir geçidi anımsattı.",
        )

    def test_undo_and_stop_physically_redact_selection_and_replay_safely(self):
        conv_id, _ = self.ready_freud()
        status, body, _ = self.consent_deck(conv_id)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        private_text = "SADECE-KULLANICIYA-AIT-CAGRISIM"
        status, body, _ = self.select_card(
            conv_id, revision, association=private_text)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        self.assertTrue(body["imagery"]["capabilities"]["undo"])

        undo_payload = {
            "action": "undo", "conv_id": conv_id,
            "request_id": "deck-undo-0001", "revision": revision,
        }
        status, body, _ = self.request(
            "POST", "/api/freud-imagery/selection", undo_payload)
        self.assertEqual(status, 200, body)
        undo_revision = body["imagery"]["session"]["revision"]
        self.assertIsNone(body["imagery"]["selection"])
        step = self.row("SELECT * FROM freud_imagery_steps WHERE conv=?",
                        (conv_id,))
        self.assertEqual(step["card_id"], "")
        self.assertEqual(step["association"], "")
        self.assertEqual(step["status"], "undone")
        self.assertTrue(step["cleared_at"])

        status, replay, _ = self.request(
            "POST", "/api/freud-imagery/selection", undo_payload)
        self.assertEqual(status, 200, replay)
        self.assertEqual(
            replay["imagery"]["session"]["revision"], undo_revision)

        status, exported, _ = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200, exported)
        self.assertNotIn(private_text, json.dumps(exported, ensure_ascii=False))

        status, body, _ = self.select_card(
            conv_id, undo_revision,
            request_id="deck-select-after-undo-0001",
            card_id="lantern",
            association="Bir ışık gördüm.",
        )
        self.assertEqual(status, 200, body)
        stop_revision = body["imagery"]["session"]["revision"]
        stop_payload = {
            "action": "stop", "conv_id": conv_id,
            "request_id": "deck-stop-0001", "revision": stop_revision,
        }
        status, stopped, _ = self.request(
            "POST", "/api/freud-imagery/selection", stop_payload)
        self.assertEqual(status, 200, stopped)
        self.assertFalse(stopped["imagery"]["available"])
        self.assertEqual(stopped["imagery"]["blocked_reason"],
                         "session_stopped")
        self.assertIsNone(stopped["imagery"]["session"])
        self.assertIsNone(stopped["imagery"]["selection"])
        self.assertEqual(stopped["imagery"]["cards"], [])
        stopped_row = self.row(
            "SELECT * FROM freud_imagery_sessions WHERE conv=?", (conv_id,))
        self.assertEqual(stopped_row["stop_request_id"], "deck-stop-0001")
        step = self.row("SELECT * FROM freud_imagery_steps WHERE conv=?",
                        (conv_id,))
        self.assertEqual((step["card_id"], step["association"]), ("", ""))
        self.assertEqual(step["status"], "cleared")

        status, replay, _ = self.request(
            "POST", "/api/freud-imagery/selection", stop_payload)
        self.assertEqual(status, 200, replay)
        self.assertEqual(
            self.row("SELECT revision FROM freud_imagery_sessions WHERE conv=?",
                     (conv_id,))["revision"],
            stopped_row["revision"],
        )

    def test_safety_hold_redacts_the_entire_deck_surface_and_blocks_model(self):
        conv_id, _ = self.ready_freud()
        status, body, _ = self.consent_deck(conv_id)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        status, body, _ = self.select_card(
            conv_id, revision, association="Özel bir çağrışım metni.")
        self.assertEqual(status, 200, body)
        held_revision = body["imagery"]["session"]["revision"]
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (conv_id,),
            )

        status, body, _ = self.imagery(conv_id)
        self.assertEqual(status, 200, body)
        deck = body["imagery"]
        self.assertFalse(deck["available"])
        self.assertEqual(deck["blocked_reason"], "safety_hold")
        self.assertEqual(deck["cards"], [])
        self.assertIsNone(deck["session"])
        self.assertIsNone(deck["selection"])
        self.assertEqual(deck["suggestions"], [])
        self.assertTrue(deck["safety_hold"])
        self.assertFalse(any(deck["capabilities"].values()))

        status, held_mutation, _ = self.select_card(
            conv_id, held_revision,
            request_id="held-select-0001",
            card_id="forest-clearing",
            association="Ekranda kalmaması gereken yeni çağrışım.",
        )
        self.assertEqual(status, 409, held_mutation)
        self.assertEqual(
            held_mutation.get("error_code"), "safety_hold", held_mutation)
        self.assertIs(held_mutation.get("safety_hold"), True, held_mutation)

        with mock.patch.object(
                app, "generate_freud_imagery_suggestions") as generate:
            status, body, _ = self.post(
                "/api/freud-imagery/suggest",
                conv_id=conv_id,
                revision=2,
                request_id="held-suggest-0001",
                model_consent=True,
            )
        self.assertEqual(status, 409, body)
        self.assertEqual(body.get("error_code"), "safety_hold", body)
        self.assertIs(body.get("safety_hold"), True, body)
        generate.assert_not_called()

    def test_crisis_text_sets_hold_stops_work_and_is_never_saved_as_a_step(self):
        conv_id, _ = self.ready_freud()
        status, body, _ = self.consent_deck(conv_id)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        crisis_text = "Kendimi öldürmeyi düşünüyorum ve bir planım var."
        status, body, _ = self.select_card(
            conv_id, revision,
            request_id="crisis-select-0001",
            association=crisis_text,
        )
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"], "safety_hold")
        self.assertTrue(body["safety_hold"])
        self.assertEqual(self.conversation_row(conv_id)["safety_hold"], 1)
        session = self.row(
            "SELECT * FROM freud_imagery_sessions WHERE conv=?", (conv_id,))
        self.assertEqual(session["status"], "stopped")
        self.assertIsNone(self.row(
            "SELECT id FROM freud_imagery_steps WHERE conv=?", (conv_id,)))

        status, deck, _ = self.imagery(conv_id)
        self.assertEqual(status, 200, deck)
        self.assertEqual(deck["imagery"]["cards"], [])
        self.assertIsNone(deck["imagery"]["session"])
        self.assertNotIn(crisis_text, json.dumps(deck, ensure_ascii=False))

    def test_model_suggestions_need_opt_in_are_literal_bounded_and_never_select(self):
        conv_id, _ = self.ready_freud()
        status, body, _ = self.consent_deck(conv_id)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        self.add_user_message(conv_id, "ESKI-MESAJ-MODELE-GITMEMELI")
        self.add_user_message(conv_id, "Pencereli sakin bir yer düşünüyorum.")

        with mock.patch.object(app, "ds_complete") as complete:
            status, rejected, _ = self.post(
                "/api/freud-imagery/suggest",
                conv_id=conv_id,
                revision=revision,
                request_id="suggest-without-optin-0001",
                model_consent=False,
            )
            self.assertEqual(status, 400, rejected)
            complete.assert_not_called()

            complete.return_value = json.dumps({
                "card_ids": ["open-window", "doorway", "lantern"],
            })
            status, suggested, _ = self.post(
                "/api/freud-imagery/suggest",
                conv_id=conv_id,
                revision=revision,
                request_id="suggest-valid-0001",
                model_consent=True,
            )
        self.assertEqual(status, 200, suggested)
        self.assertFalse(suggested["selected"])
        deck = suggested["imagery"]
        self.assertEqual(
            [card["id"] for card in deck["suggestions"]],
            ["open-window", "doorway", "lantern"],
        )
        self.assertIsNone(deck["selection"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_steps")["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_suggestions")["n"], 1)
        self.assertIn("ne çağrıştır", deck["suggestion_question"].casefold())

        model_messages = complete.call_args.args[0]
        rendered = json.dumps(model_messages, ensure_ascii=False)
        self.assertIn("Pencereli sakin bir yer düşünüyorum.", rendered)
        self.assertNotIn("ESKI-MESAJ-MODELE-GITMEMELI", rendered)
        system = model_messages[0]["content"].casefold()
        for marker in (
                "projektif test", "rorschach", "kişilik", "tanı",
                "allowlist", "1-3", "anlam"):
            self.assertIn(marker, system)

        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("replay must not call model")):
            status, replay, _ = self.post(
                "/api/freud-imagery/suggest",
                conv_id=conv_id,
                revision=revision,
                request_id="suggest-valid-0001",
                model_consent=True,
            )
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["duplicate"])
        self.assertIsNone(replay["imagery"]["selection"])

    def test_invalid_or_extra_model_card_ids_fail_closed(self):
        conv_id, _ = self.ready_freud()
        status, body, _ = self.consent_deck(conv_id)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        invalid_outputs = (
            '{"card_ids":["doorway","lantern","river-bend","attic"]}',
            '{"card_ids":["doorway","not-allowlisted"]}',
            '{"card_ids":["doorway","doorway"]}',
            '{"card_ids":["doorway"],"selected":true}',
            'Kart olarak doorway seç.',
            '{"card_ids":[]}',
        )
        for index, output in enumerate(invalid_outputs):
            with self.subTest(output=output), mock.patch.object(
                    app, "ds_complete", return_value=output):
                status, body, _ = self.post(
                    "/api/freud-imagery/suggest",
                    conv_id=conv_id,
                    revision=revision,
                    request_id="suggest-invalid-{:04d}".format(index),
                    model_consent=True,
                )
                self.assertEqual(status, 502, body)
                self.assertNotEqual(status, 500)
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_suggestions")["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_steps")["n"], 0)

    def test_stale_and_concurrent_model_responses_cannot_overwrite_state(self):
        conv_id, _ = self.ready_freud()
        status, body, _ = self.consent_deck(conv_id)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]

        def make_stale(_latest_user_text):
            with app.db() as connection:
                connection.execute(
                    "UPDATE freud_imagery_sessions SET revision=revision+1 "
                    "WHERE conv=?", (conv_id,))
            return ["doorway"]

        with mock.patch.object(
                app, "generate_freud_imagery_suggestions",
                side_effect=make_stale):
            status, body, _ = self.post(
                "/api/freud-imagery/suggest",
                conv_id=conv_id,
                revision=revision,
                request_id="suggest-stale-0001",
                model_consent=True,
            )
        self.assertEqual(status, 409, body)
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_suggestions")["n"], 0)

        current_revision = self.row(
            "SELECT revision FROM freud_imagery_sessions WHERE conv=?",
            (conv_id,))["revision"]
        collision_id = "suggest-race-0001"

        def insert_winning_request(_latest_user_text):
            session = self.row(
                "SELECT * FROM freud_imagery_sessions WHERE conv=?",
                (conv_id,))
            request_hash = app.freud_imagery_request_hash({
                "action": "suggest",
                "imagery_session": session["id"],
                "revision": current_revision,
                "latest_user_message_id": 0,
                "latest_user_message_hash": hashlib.sha256(
                    b"").hexdigest(),
                "model_consent": True,
            })
            with app.db() as connection:
                connection.execute(
                    "INSERT INTO freud_imagery_suggestions("
                    "imagery_session,conv,request_id,request_hash,"
                    "card_ids_json,created) VALUES(?,?,?,?,?,?)",
                    (session["id"], conv_id, collision_id, request_hash,
                     '["lantern"]', app.now()),
                )
            return ["doorway"]

        with mock.patch.object(
                app, "generate_freud_imagery_suggestions",
                side_effect=insert_winning_request):
            status, body, _ = self.post(
                "/api/freud-imagery/suggest",
                conv_id=conv_id,
                revision=current_revision,
                request_id=collision_id,
                model_consent=True,
            )
        self.assertEqual(status, 200, body)
        self.assertTrue(body["duplicate"])
        self.assertEqual(
            [card["id"] for card in body["imagery"]["suggestions"]],
            ["lantern"],
        )
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_suggestions")["n"], 1)

    def test_suggestion_crisis_and_new_message_races_fail_before_persistence(self):
        crisis_conv, _ = self.ready_freud()
        status, body, _ = self.consent_deck(crisis_conv)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        self.add_user_message(
            crisis_conv,
            "Kendimi öldürmeyi düşünüyorum ve bunu yapmak için planım var.",
        )
        with mock.patch.object(
                app, "generate_freud_imagery_suggestions",
                side_effect=AssertionError("crisis text must not reach model")):
            status, held, _ = self.post(
                "/api/freud-imagery/suggest",
                conv_id=crisis_conv,
                revision=revision,
                request_id="suggest-crisis-0001",
                model_consent=True,
            )
        self.assertEqual(status, 409, held)
        self.assertEqual(held["error_code"], "safety_hold")
        self.assertEqual(self.conversation_row(crisis_conv)["safety_hold"], 1)
        self.assertEqual(self.row(
            "SELECT status FROM freud_imagery_sessions WHERE conv=?",
            (crisis_conv,))["status"], "stopped")

        changed_conv, _ = self.ready_freud()
        status, body, _ = self.consent_deck(
            changed_conv, request_id="deck-consent-message-race")
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        self.add_user_message(changed_conv, "İlk bağlam mesajı.")

        def receive_new_message(_latest_user_text):
            self.add_user_message(changed_conv, "Model beklerken gelen mesaj.")
            return ["doorway"]

        with mock.patch.object(
                app, "generate_freud_imagery_suggestions",
                side_effect=receive_new_message):
            status, stale, _ = self.post(
                "/api/freud-imagery/suggest",
                conv_id=changed_conv,
                revision=revision,
                request_id="suggest-message-race-0001",
                model_consent=True,
            )
        self.assertEqual(status, 409, stale)
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_suggestions WHERE conv=?",
            (changed_conv,))["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_steps WHERE conv=?",
            (changed_conv,))["n"], 0)

    def test_provider_errors_are_safe_and_do_not_persist_a_suggestion(self):
        conv_id, _ = self.ready_freud()
        status, body, _ = self.consent_deck(conv_id)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        secret = "PROVIDER-RAW-SECRET-MUST-NOT-LEAK"
        with mock.patch.object(
                app, "generate_freud_imagery_suggestions",
                side_effect=app.ProviderError("provider_unavailable", secret)):
            status, body, _ = self.post(
                "/api/freud-imagery/suggest",
                conv_id=conv_id,
                revision=revision,
                request_id="suggest-provider-error-0001",
                model_consent=True,
            )
        self.assertEqual(status, 502, body)
        self.assertEqual(body["error_code"], "provider_unavailable")
        self.assertNotIn(secret, json.dumps(body, ensure_ascii=False))
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM freud_imagery_suggestions")["n"], 0)

    def test_export_conversation_delete_and_delete_all_cover_all_deck_tables(self):
        conv_id, _ = self.ready_freud()
        status, body, _ = self.consent_deck(conv_id)
        self.assertEqual(status, 200, body)
        revision = body["imagery"]["session"]["revision"]
        association = "DIŞA-AKTARILACAK-KULLANICI-CAGRISIMI"
        status, body, _ = self.select_card(
            conv_id, revision,
            request_id="lifecycle-select-0001",
            association=association,
        )
        self.assertEqual(status, 200, body)
        session = self.row(
            "SELECT * FROM freud_imagery_sessions WHERE conv=?", (conv_id,))
        with app.db() as connection:
            connection.execute(
                "INSERT INTO freud_imagery_suggestions("
                "imagery_session,conv,request_id,request_hash,"
                "card_ids_json,created) VALUES(?,?,?,?,?,?)",
                (session["id"], conv_id, "lifecycle-suggest-0001",
                 app.freud_imagery_request_hash({"lifecycle": True}),
                 '["doorway"]', app.now()),
            )

        status, exported, _ = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200, exported)
        for table in (
                "freud_imagery_sessions", "freud_imagery_steps",
                "freud_imagery_suggestions"):
            self.assertIn(table, exported["data"])
            self.assertEqual(len(exported["data"][table]), 1)
        self.assertIn(association, json.dumps(exported, ensure_ascii=False))

        status, deleted, _ = self.post("/api/delete", id=conv_id)
        self.assertEqual(status, 200, deleted)
        for table in (
                "freud_imagery_suggestions", "freud_imagery_steps",
                "freud_imagery_sessions"):
            with self.subTest(table=table, operation="conversation-delete"):
                self.assertEqual(self.row(
                    "SELECT COUNT(*) n FROM " + table)["n"], 0)

        second, _ = self.ready_freud()
        status, body, _ = self.consent_deck(
            second, request_id="lifecycle-consent-0002")
        self.assertEqual(status, 200, body)
        status, body, _ = self.select_card(
            second, body["imagery"]["session"]["revision"],
            request_id="lifecycle-select-0002")
        self.assertEqual(status, 200, body)
        status, deleted, _ = self.post(
            "/api/delete-all", confirm="TÜM VERİLERİ SİL")
        self.assertEqual(status, 200, deleted)
        for table in (
                "freud_imagery_suggestions", "freud_imagery_steps",
                "freud_imagery_sessions"):
            with self.subTest(table=table, operation="delete-all"):
                self.assertEqual(self.row(
                    "SELECT COUNT(*) n FROM " + table)["n"], 0)


if __name__ == "__main__":
    unittest.main()
