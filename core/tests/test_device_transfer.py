import copy
import json
from pathlib import Path

from support import HTTPTestCase, app


def bundle_with(conversations):
    return {
        "kind": app.TRANSFER_KIND,
        "version": app.TRANSFER_VERSION,
        "exported_at": "2026-07-30 10:00",
        "conversations": conversations,
    }


def conversation_payload(public_id="1" * 32, messages=None, **changes):
    value = {
        "public_id": public_id,
        "mode": "terapi",
        "submode": None,
        "master": "freud",
        "title": "Aktarılan görüşme",
        "created": "2026-07-29 09:00",
        "updated": "2026-07-29 09:30",
        "ended": False,
        "archived": False,
        "messages": messages or [],
    }
    value.update(changes)
    return value


def message_payload(public_id, content, role="user", reply_to=None):
    return {
        "public_id": public_id,
        "role": role,
        "content": content,
        "created": "2026-07-29 09:05",
        "reply_to": reply_to,
    }


class DeviceTransferTests(HTTPTestCase):

    def test_schema_backfills_and_assigns_opaque_public_ids(self):
        first = self.conversation()
        second = self.conversation()
        self.messages(first, 2)
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET public_id=NULL WHERE id=?",
                (first,))
            connection.execute(
                "UPDATE messages SET public_id=NULL WHERE conv=?",
                (first,))

        app.init_db()

        conversation_ids = [
            row["public_id"] for row in self.rows(
                "SELECT public_id FROM conversations ORDER BY id")]
        message_ids = [
            row["public_id"] for row in self.rows(
                "SELECT public_id FROM messages ORDER BY id")]
        self.assertEqual(len(conversation_ids), len(set(conversation_ids)))
        self.assertEqual(len(message_ids), len(set(message_ids)))
        for public_id in conversation_ids + message_ids:
            self.assertRegex(public_id, r"^[0-9a-f]{32}$")
        self.assertRegex(
            self.conversation_row(second)["public_id"],
            r"^[0-9a-f]{32}$")

    def test_export_contains_only_selected_conversation_data_and_no_secrets(self):
        selected = self.conversation(
            title="Seçili", ended=1, updated="2026-07-20 10:20")
        unselected = self.conversation(title="Seçilmemiş")
        with app.db() as connection:
            user = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (selected, "user", "Bir düşünce", "2026-07-20 10:01"),
            ).lastrowid
            connection.execute(
                "INSERT INTO messages(conv,role,content,created,reply_to) "
                "VALUES(?,?,?,?,?)",
                (selected, "assistant", "Bir yanıt",
                 "2026-07-20 10:02", user),
            )
            connection.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created) "
                "VALUES(?,?,?,?,?)",
                (selected, "terapi", "freud", "gizli klinik not",
                 "2026-07-20 10:10"),
            )
            connection.execute(
                "INSERT INTO formulations(mode,therapist,content,created) "
                "VALUES(?,?,?,?)",
                ("terapi", "freud", "gizli formülasyon",
                 "2026-07-20 10:11"),
            )
        app.set_setting("openai_api_key", "sk-super-secret")
        app.set_setting("profile", "gizli profil")

        status, exported, _ = self.request(
            "POST", "/api/transfer/export", {"ids": [selected]})

        self.assertEqual(status, 200)
        self.assertEqual(
            set(exported),
            {"kind", "version", "exported_at", "conversations"})
        self.assertEqual(len(exported["conversations"]), 1)
        conv = exported["conversations"][0]
        self.assertEqual(conv["title"], "Seçili")
        self.assertNotIn("id", conv)
        self.assertNotIn("source", conv)
        self.assertNotIn("case_id", conv)
        self.assertNotIn("settings", conv)
        self.assertEqual(len(conv["messages"]), 2)
        self.assertEqual(
            conv["messages"][1]["reply_to"],
            conv["messages"][0]["public_id"])
        serialized = json.dumps(exported, ensure_ascii=False)
        for forbidden in (
                "sk-super-secret", "gizli profil", "gizli klinik not",
                "gizli formülasyon", "Seçilmemiş"):
            self.assertNotIn(forbidden, serialized)
        self.assertIsNotNone(self.conversation_row(unselected))

    def test_preview_and_import_roundtrip_are_read_only_and_idempotent(self):
        source_id = self.conversation(
            title="Taşınacak", ended=0,
            created="2026-07-20 10:00", updated="2026-07-20 10:05")
        with app.db() as connection:
            assistant = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (source_id, "assistant", "İkinci mesaja bağlı",
                 "2026-07-20 10:01"),
            ).lastrowid
            user = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (source_id, "user", "Bağın hedefi",
                 "2026-07-20 10:02"),
            ).lastrowid
            connection.execute(
                "UPDATE messages SET reply_to=? WHERE id=?",
                (user, assistant))
        status, exported, _ = self.request(
            "POST", "/api/transfer/export", {"ids": [source_id]})
        self.assertEqual(status, 200)

        source_path = app.DB_PATH
        target_path = str(Path(self._tmp.name) / "target.db")
        app.DB_PATH = target_path
        try:
            app.init_db()
            status, preview, _ = self.request(
                "POST", "/api/transfer/preview", {"bundle": exported})
            self.assertEqual(status, 200)
            self.assertEqual(preview["summary"]["new_conversation_count"], 1)
            self.assertEqual(preview["summary"]["new_message_count"], 2)
            self.assertEqual(
                self.row("SELECT COUNT(*) AS n FROM conversations")["n"], 0)

            status, imported, _ = self.request(
                "POST", "/api/transfer/import", {"bundle": exported})
            self.assertEqual(status, 200)
            self.assertEqual(imported["conversations_imported"], 1)
            self.assertEqual(imported["messages_imported"], 2)
            conv = self.row("SELECT * FROM conversations")
            self.assertEqual(conv["title"], "Taşınacak")
            self.assertEqual(conv["ended"], 1)
            self.assertIsNotNone(conv["archived_at"])
            self.assertEqual(conv["source_mode"], 0)
            self.assertIsNone(conv["case_id"])
            rows = self.rows(
                "SELECT m.public_id,m.content,q.public_id AS reply_public_id "
                "FROM messages m LEFT JOIN messages q ON q.id=m.reply_to "
                "ORDER BY m.id")
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                rows[0]["reply_public_id"], rows[1]["public_id"])

            status, repeated, _ = self.request(
                "POST", "/api/transfer/import", {"bundle": exported})
            self.assertEqual(status, 200)
            self.assertEqual(repeated["conversations_imported"], 0)
            self.assertEqual(repeated["conversations_existing"], 1)
            self.assertEqual(repeated["messages_imported"], 0)
            self.assertEqual(repeated["messages_existing"], 2)
            self.assertEqual(
                self.row("SELECT COUNT(*) AS n FROM conversations")["n"], 1)
            self.assertEqual(
                self.row("SELECT COUNT(*) AS n FROM messages")["n"], 2)
        finally:
            app.DB_PATH = source_path

    def test_malformed_and_oversize_bundles_are_rejected_before_writes(self):
        valid = bundle_with([conversation_payload(messages=[
            message_payload("2" * 32, "kısa"),
        ])])
        unknown_field = copy.deepcopy(valid)
        unknown_field["conversations"][0]["api_key"] = "must-not-pass"
        status, body, _ = self.request(
            "POST", "/api/transfer/import", {"bundle": unknown_field})
        self.assertEqual(status, 400)
        self.assertIn("bilinmeyen alan", body["error"])

        oversized = copy.deepcopy(valid)
        oversized["conversations"][0]["messages"][0]["content"] = (
            "x" * (app.TRANSFER_MAX_MESSAGE_CHARS + 1))
        status, body, _ = self.request(
            "POST", "/api/transfer/import", {"bundle": oversized})
        self.assertEqual(status, 413)
        self.assertIn("çok uzun", body["error"])

        bad_master = copy.deepcopy(valid)
        bad_master["conversations"][0]["master"] = "taninmayan"
        status, _, _ = self.request(
            "POST", "/api/transfer/preview", {"bundle": bad_master})
        self.assertEqual(status, 400)

        bad_submode = copy.deepcopy(valid)
        bad_submode["conversations"][0]["submode"] = "serbest"
        status, _, _ = self.request(
            "POST", "/api/transfer/import", {"bundle": bad_submode})
        self.assertEqual(status, 400)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM conversations")["n"], 0)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM messages")["n"], 0)

    def test_public_id_collisions_never_overwrite_local_rows(self):
        local = self.conversation(
            title="Yerel başlık", created="2026-07-20 10:00")
        local_public_id = self.conversation_row(local)["public_id"]
        collision = bundle_with([conversation_payload(
            public_id=local_public_id,
            title="Dışarıdan başlık",
            created="2026-07-20 10:00",
            messages=[message_payload("3" * 32, "eklenmemeli")],
        )])

        status, result, _ = self.request(
            "POST", "/api/transfer/import", {"bundle": collision})

        self.assertEqual(status, 200)
        self.assertEqual(result["conversation_collisions"], 1)
        row = self.conversation_row(local)
        self.assertEqual(row["title"], "Yerel başlık")
        self.assertEqual(row["ended"], 0)
        self.assertIsNone(row["archived_at"])
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM messages")["n"], 0)

    def test_message_collision_in_another_conversation_is_not_relinked(self):
        target = self.conversation(
            title="Aktarılan görüşme",
            ended=1,
            created="2026-07-29 09:00",
            updated="2026-07-29 09:30")
        other = self.conversation(title="Başka")
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET archived_at=? WHERE id=?",
                ("2026-07-29 09:31", target))
        target_public_id = self.conversation_row(target)["public_id"]
        colliding_message_id = "4" * 32
        with app.db() as connection:
            connection.execute(
                "INSERT INTO messages("
                "public_id,conv,role,content,created) VALUES(?,?,?,?,?)",
                (colliding_message_id, other, "user", "yerel içerik",
                 "2026-07-29 09:05"))
        incoming = bundle_with([conversation_payload(
            public_id=target_public_id,
            messages=[
                message_payload(colliding_message_id, "dış içerik"),
                message_payload(
                    "5" * 32, "yanıt", role="assistant",
                    reply_to=colliding_message_id),
            ],
        )])

        status, result, _ = self.request(
            "POST", "/api/transfer/import", {"bundle": incoming})

        self.assertEqual(status, 200)
        self.assertEqual(result["message_collisions"], 1)
        self.assertEqual(result["messages_imported"], 1)
        local_collision = self.row(
            "SELECT * FROM messages WHERE public_id=?",
            (colliding_message_id,))
        self.assertEqual(local_collision["conv"], other)
        self.assertEqual(local_collision["content"], "yerel içerik")
        imported_reply = self.row(
            "SELECT * FROM messages WHERE public_id=?", ("5" * 32,))
        self.assertEqual(imported_reply["conv"], target)
        self.assertIsNone(imported_reply["reply_to"])

    def test_reimport_never_mutates_matching_open_or_unarchived_history(self):
        local = self.conversation(
            title="Aktarılan görüşme",
            ended=0,
            created="2026-07-29 09:00",
            updated="2026-07-29 09:30")
        public_id = self.conversation_row(local)["public_id"]
        incoming = bundle_with([conversation_payload(
            public_id=public_id,
            messages=[message_payload("6" * 32, "eklenmemeli")],
        )])

        status, result, _ = self.request(
            "POST", "/api/transfer/import", {"bundle": incoming})

        self.assertEqual(status, 200)
        self.assertEqual(result["conversation_collisions"], 1)
        self.assertEqual(result["messages_skipped"], 1)
        self.assertEqual(result["messages_imported"], 0)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (local,))["n"],
            0,
        )


if __name__ == "__main__":
    import unittest
    unittest.main()
