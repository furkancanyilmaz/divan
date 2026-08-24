"""5 ajanlı denetimde bulunan hataların regresyon testleri.

Her test gerçek bir bulguya karşılık gelir; hiçbiri varsayımsal değildir.
"""

import sqlite3

from support import HTTPTestCase, app


class MarkerLeakTests(HTTPTestCase):
    """Ham işaret kullanıcıya ASLA görünmemeli (harf/boşluk farkı dahil)."""

    def test_case_and_space_variants_are_stripped(self):
        for raw in (
            "Bugün zor.\n[[mod]] detached_protector | x",
            "Bugün zor.\n[[ MOD ]] detached_protector | x",
            "Bugün zor.\n[[Teknik]] yansıtma | x",
            "Bugün zor.\n[[harita]] dongu | x",
            "Bugün zor.\n[[kayit]] tetikleyici | x",
            "Bugün zor.\n[[FAZ]] focus | x",
        ):
            text, *_ = app.split_schema_markers(raw)
            self.assertNotIn("[[", text, raw)
            self.assertEqual(text, "Bugün zor.", raw)

    def test_streaming_holds_back_lowercase_marker(self):
        self.assertTrue(app.suggestion_tail_started("merhaba [[mo"))
        self.assertTrue(app.suggestion_tail_started("merhaba [[MOD]]"))
        self.assertFalse(app.suggestion_tail_started("düz metin"))

    def test_valid_markers_still_work(self):
        text, suggestions, _, technique, _, _ = app.split_schema_markers(
            "Anlıyorum.\n[[MOD]] detached_protector | duvar\n"
            "[[TEKNIK]] yansıtma | neden")
        self.assertEqual(text, "Anlıyorum.")
        self.assertTrue(suggestions)
        self.assertTrue(technique)


class SecretRedactionTests(HTTPTestCase):
    """Tanı günlüğü hiçbir anahtar biçimini sızdırmamalı."""

    def test_all_known_key_formats_are_masked(self):
        for secret in (
            "Authorization: Basic dXNlcjpwYXNzd29yZA==",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abcdefghijk",
            "a3f5c8d9e1b2a4f6c8d0e2b4a6f8c0d2",
            "AIzaSyD-1234567890abcdefghijk",
            "x-api-key: sk_live_51H8xQeSl5T3Kx1abcdEFGH",
            "sk-proj-ABCDEFGH12345678",
            "Bearer gizli-token-12345",
        ):
            masked = app.DIAGNOSTIC_SECRET_RE.sub("[gizlendi]", secret)
            self.assertIn("[gizlendi]", masked, secret)


class MigrationSafetyTests(HTTPTestCase):
    """Migrasyon veri kaybettirmemeli — yetim satır olsa bile."""

    def legacy_db(self, path, orphan=True):
        connection = sqlite3.connect(path)
        connection.executescript("""
        CREATE TABLE conversations(id INTEGER PRIMARY KEY AUTOINCREMENT,
            therapist TEXT, mode TEXT, submode TEXT, title TEXT,
            created TEXT, updated TEXT);
        CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,
            conv INTEGER, role TEXT, content TEXT, created TEXT,
            delivery_status TEXT DEFAULT 'completed');
        CREATE TABLE schema_inline_suggestions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, conv INTEGER NOT NULL,
            assistant_message INTEGER NOT NULL, mode_key TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open', created TEXT NOT NULL,
            UNIQUE(assistant_message),
            CHECK(status IN ('open','accepted','dismissed')));
        """)
        connection.execute(
            "INSERT INTO conversations(id,therapist,mode,created,updated) "
            "VALUES(1,'young','terapi','t','t')")
        connection.execute(
            "INSERT INTO messages(id,conv,role,content,created) "
            "VALUES(5,1,'assistant','x','t')")
        connection.execute(
            "INSERT INTO schema_inline_suggestions(conv,assistant_message,"
            "mode_key,evidence,status,created) "
            "VALUES(1,5,'detached_protector','gerçek kayıt','open','t')")
        if orphan:
            # Silinmiş bir mesaja işaret eden satır: migrasyonu
            # patlatıp tabloyu kalıcı boşaltıyordu.
            connection.execute(
                "INSERT INTO schema_inline_suggestions(conv,"
                "assistant_message,mode_key,evidence,status,created) "
                "VALUES(1,999,'punitive_parent','yetim','open','t')")
        connection.commit()
        connection.close()

    def test_orphan_row_does_not_destroy_the_table(self):
        import tempfile
        import os
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "eski.db")
        self.legacy_db(path, orphan=True)
        # Migrasyon patlamamalı.
        app.create_server(port=9490, db_path=path)
        connection = sqlite3.connect(path)
        rows = [r[0] for r in connection.execute(
            "SELECT evidence FROM schema_inline_suggestions")]
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE "
            "name='schema_inline_suggestions'").fetchone()[0]
        leftover = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE "
            "name='schema_inline_suggestions_old'").fetchone()
        connection.close()
        # Gerçek kayıt korunmalı, yetim satır düşmeli.
        self.assertIn("gerçek kayıt", rows)
        self.assertIn("UNIQUE(assistant_message,mode_key)", sql)
        self.assertIsNone(leftover)


class MapNoteDedupTests(HTTPTestCase):
    """Aynı harita çıkarımı her turda yeniden yazılmamalı."""

    stamp = "2026-08-21 10:00"

    def test_repeated_note_is_written_once(self):
        conv = self.conversation(therapist="young")
        provider, model = app._configured_provider_model_snapshot()
        with app.db() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO session_meta("
                "conv,schema_mode_enabled,schema_mode_initialized,"
                "schema_mode_provider,schema_mode_model,updated) "
                "VALUES(?,1,1,?,?,?)",
                (conv, provider, model, self.stamp))
            row = connection.execute(
                "SELECT * FROM conversations WHERE id=?", (conv,)).fetchone()
            user_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'user','aynı çıkarım',?,"
                "'completed')", (conv, self.stamp)).lastrowid
            assistant_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'assistant','yanıt',?,"
                "'completed')", (conv, self.stamp)).lastrowid
            for _ in range(5):
                app._record_map_notes(connection, row, assistant_id, [{
                    "category": "dongu", "section": "cycles",
                    "claim_type": "pattern", "note": "aynı çıkarım"}],
                    user_message_id=user_id)
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM psych_claims "
                "WHERE statement='aynı çıkarım'").fetchone()["n"]
            public_id = connection.execute(
                "SELECT public_id FROM psych_claims "
                "WHERE statement='aynı çıkarım'").fetchone()["public_id"]
        self.assertEqual(count, 1)
        # Senkron/dışa aktarım için kimlik şart.
        self.assertTrue(public_id)


class ProModeStateTests(HTTPTestCase):
    """Pro mod kapanınca gövde sınıfı ve rozetler de temizlenmeli."""

    def test_unavailable_conversation_clears_pro_mode_fully(self):
        html = open("index.html", encoding="utf-8").read()
        start = html.index("function syncProModeButton(")
        body = html[start:start + 900]
        self.assertIn("classList.remove('proModeOn')", body)
        self.assertIn(".proTechnique').forEach", body)


class AcceptCardTests(HTTPTestCase):
    """Kabul kaydedilmediyse kart kapanmamalı (sessiz ölü tıklama)."""

    def test_card_stays_open_when_accept_fails(self):
        html = open("index.html", encoding="utf-8").read()
        start = html.index("async function acceptInlineSuggestion(")
        body = html[start:start + 1200]
        # Önce sunucu yanıtı kontrol edilir, sonra kart kapatılır.
        self.assertIn("const sonuc=await postSchemaPath('accept_suggestion'",
                      body)
        self.assertIn("if(!sonuc){", body)
        accept_index = body.index("const sonuc=")
        dismiss_index = body.index("schemaSuggestDismissed.add")
        self.assertLess(accept_index, dismiss_index)
