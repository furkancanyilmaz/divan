import unittest
from pathlib import Path
from urllib.parse import quote

from support import HTTPTestCase, PROJECT_DIR, app


class ConversationArchiveTests(HTTPTestCase):

    def archive(self, conv_id, archived=True):
        return self.request(
            "POST", "/api/archive",
            {"id": conv_id, "archived": archived})

    def batch(self, action, conv_ids):
        return self.request(
            "POST", "/api/conversations/batch",
            {"action": action, "ids": conv_ids})

    def ids(self, path="/api/conversations"):
        status, rows, _ = self.request("GET", path)
        self.assertEqual(status, 200, rows)
        return {row["id"] for row in rows}

    def test_therapy_and_lesson_round_trip_without_losing_content(self):
        for mode, therapist in (("terapi", "young"), ("ders", "freud")):
            with self.subTest(mode=mode):
                conv_id = self.conversation(
                    mode=mode, therapist=therapist, ended=1,
                    title="Korunacak {}".format(mode))
                self.messages(conv_id, 2, prefix=mode)
                with app.db() as conn:
                    conn.execute(
                        "INSERT INTO notes("
                        "conv,mode,therapist,content,created,updated) "
                        "VALUES(?,?,?,?,?,?)",
                        (conv_id, mode, therapist, "korunan not",
                         app.now(), app.now()))
                before = dict(self.conversation_row(conv_id))
                generation = app.data_generation()

                status, archived, _ = self.archive(conv_id)

                self.assertEqual(status, 200, archived)
                self.assertTrue(archived["ok"])
                self.assertTrue(archived["archived"])
                self.assertEqual(archived["id"], conv_id)
                self.assertTrue(archived["archived_at"])
                self.assertEqual(app.data_generation(), generation)
                self.assertNotIn(conv_id, self.ids())
                self.assertIn(
                    conv_id, self.ids("/api/conversations?archived=1"))
                saved = dict(self.conversation_row(conv_id))
                for field in (
                        "title", "mode", "therapist", "ended",
                        "created", "updated"):
                    self.assertEqual(saved[field], before[field])
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                        (conv_id,))["n"], 2)
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM notes WHERE conv=?",
                        (conv_id,))["n"], 1)

                first_stamp = archived["archived_at"]
                status, repeated, _ = self.archive(conv_id)
                self.assertEqual(status, 200, repeated)
                self.assertEqual(repeated["archived_at"], first_stamp)

                status, restored, _ = self.archive(conv_id, False)

                self.assertEqual(status, 200, restored)
                self.assertFalse(restored["archived"])
                self.assertIsNone(restored["archived_at"])
                self.assertIn(conv_id, self.ids())
                self.assertNotIn(
                    conv_id, self.ids("/api/conversations?archived=1"))

    def test_invalid_archive_and_delete_ids_are_reported(self):
        conv_id = self.conversation()
        generation = app.data_generation()
        for payload in (
                {"id": True, "archived": True},
                {"id": conv_id, "archived": "true"},
                {"id": "bozuk", "archived": True}):
            with self.subTest(payload=payload):
                status, _, _ = self.request(
                    "POST", "/api/archive", payload)
                self.assertEqual(status, 400)
        status, body, _ = self.archive(999999)
        self.assertEqual(status, 404, body)
        self.assertEqual(app.data_generation(), generation)
        self.assertIsNotNone(self.conversation_row(conv_id))

        status, _, _ = self.request(
            "POST", "/api/delete", {"id": True})
        self.assertEqual(status, 400)
        status, body, _ = self.request(
            "POST", "/api/delete", {"id": 999999})
        self.assertEqual(status, 404, body)

    def test_archived_open_conversation_rejects_direct_chat_without_saving(self):
        conv_id = self.conversation()
        self.archive(conv_id)

        with self.assertRaises(app.RequestInputError) as caught:
            app.begin_chat_request(
                conv_id, "Arşive yazılmamalı",
                request_id="chat-archived-direct-1")

        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (conv_id,))["n"],
            0,
        )

    def test_archiving_active_chat_cancels_job_and_signals_stream(self):
        conv_id = self.conversation()
        request, _ = app.begin_chat_request(
            conv_id, "Yanıt hazırlanıyor",
            request_id="chat-archive-active-1")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='running' "
                "WHERE request_id=?", (request["request_id"],))
            conn.execute(
                "UPDATE jobs SET status='running' WHERE id=?",
                (request["job"],))
        event = app.chat_cancel_event(request["request_id"], create=True)

        status, body, _ = self.archive(conv_id)

        self.assertEqual(status, 200, body)
        saved = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (request["request_id"],))
        job = self.row("SELECT * FROM jobs WHERE id=?", (request["job"],))
        self.assertEqual(saved["status"], "cancelled")
        self.assertEqual(saved["error_code"], "conversation_archived")
        self.assertEqual(job["status"], "interrupted")
        self.assertTrue(event.is_set())

    def test_archived_conversation_can_still_be_permanently_deleted(self):
        source = self.conversation(title="Silinecek kaynak")
        child = self.conversation(
            mode="ders", submode="supervizyon", title="Kalacak ders")
        self.messages(source, 2)
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET source=? WHERE id=?",
                (source, child))
        self.archive(source)

        status, body, _ = self.request(
            "POST", "/api/delete", {"id": source})

        self.assertEqual(status, 200, body)
        self.assertEqual(body["deleted"], source)
        self.assertIsNone(self.conversation_row(source))
        self.assertIsNone(self.conversation_row(child)["source"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (source,))["n"], 0)
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        status, _, _ = self.request(
            "POST", "/api/delete", {"id": source})
        self.assertEqual(status, 404)

    def test_archive_is_protected_from_retention_but_active_history_is_not(self):
        active = self.conversation(
            title="Süresi dolan", created="2000-01-01 00:00",
            updated="2000-01-02 00:00")
        archived = self.conversation(
            title="Arşivde korunan", created="2000-01-01 00:00",
            updated="2000-01-02 00:00")
        self.archive(archived)
        app.set_setting("retention_days", "30")

        deleted = app.enforce_retention_policy()

        self.assertEqual(deleted, 1)
        self.assertIsNone(self.conversation_row(active))
        self.assertIsNotNone(self.conversation_row(archived))

    def test_normal_search_hides_archived_content(self):
        active = self.conversation(title="Güncel")
        archived = self.conversation(title="Arşiv")
        with app.db() as conn:
            for conv_id, text in (
                    (active, "ARAMA-İŞARETİ güncel"),
                    (archived, "ARAMA-İŞARETİ arşiv")):
                conn.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,'user',?,?)",
                    (conv_id, text, app.now()))
        self.archive(archived)

        status, body, _ = self.request(
            "GET", "/api/search?q=" + quote("ARAMA-İŞARETİ"))

        self.assertEqual(status, 200, body)
        self.assertEqual(
            {row["conv"] for row in body["results"]}, {active})

    def test_conversation_list_returns_bounded_latest_message_preview(self):
        older = self.conversation(
            therapist="young", title="Önceki",
            updated="2026-07-20 10:00")
        newer = self.conversation(
            therapist="freud", title="En son",
            updated="2026-07-20 11:00")
        long_preview = "son-" + ("x" * 260)
        with app.db() as conn:
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (older, "assistant", "ilk", "2026-07-20 10:01"))
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (older, "user", long_preview, "2026-07-20 10:02"))

        status, rows, _ = self.request("GET", "/api/conversations")

        self.assertEqual(status, 200, rows)
        self.assertEqual([row["id"] for row in rows], [newer, older])
        by_id = {row["id"]: row for row in rows}
        self.assertIsNone(by_id[newer]["preview"])
        self.assertEqual(by_id[older]["preview"], long_preview[:220])
        self.assertEqual(by_id[older]["preview_role"], "user")
        self.assertEqual(
            by_id[older]["preview_created"], "2026-07-20 10:02")

    def test_conversation_list_uses_id_as_stable_tie_breaker(self):
        first = self.conversation(
            title="Aynı saatte ilk", updated="2026-07-28 12:00")
        second = self.conversation(
            title="Aynı saatte ikinci", updated="2026-07-28 12:00")

        status, rows, _ = self.request("GET", "/api/conversations")

        self.assertEqual(status, 200, rows)
        self.assertEqual([row["id"] for row in rows], [second, first])

    def test_active_conversations_precede_newer_ended_conversations(self):
        older_ended = self.conversation(
            title="Eski bitmiş", ended=1, updated="2026-07-20 09:00")
        older_active = self.conversation(
            title="Eski açık", ended=0, updated="2026-07-20 10:00")
        newer_ended = self.conversation(
            title="Yeni bitmiş", ended=1, updated="2026-07-29 12:00")
        newer_active = self.conversation(
            title="Yeni açık", ended=0, updated="2026-07-28 12:00")

        status, rows, _ = self.request("GET", "/api/conversations")

        self.assertEqual(status, 200, rows)
        self.assertEqual(
            [row["id"] for row in rows],
            [newer_active, older_active, newer_ended, older_ended])

    def test_archived_list_keeps_archive_order_independent_of_ended_state(self):
        ended = self.conversation(
            title="Önce arşivlenen bitmiş", ended=1,
            updated="2026-07-29 15:00")
        active = self.conversation(
            title="Sonra arşivlenen açık", ended=0,
            updated="2026-07-20 09:00")
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET archived_at=? WHERE id=?",
                ("2026-07-29 10:00", ended))
            conn.execute(
                "UPDATE conversations SET archived_at=? WHERE id=?",
                ("2026-07-30 10:00", active))

        status, rows, _ = self.request(
            "GET", "/api/conversations?archived=1")

        self.assertEqual(status, 200, rows)
        self.assertEqual([row["id"] for row in rows], [active, ended])

    def test_batch_archive_and_restore_are_idempotent_and_preserve_content(self):
        first = self.conversation(title="Birinci")
        second = self.conversation(
            mode="ders", therapist="young", title="İkinci")
        self.messages(first, 2, prefix="bir")
        self.messages(second, 3, prefix="iki")
        generation = app.data_generation()

        status, archived, _ = self.batch("archive", [first, second])

        self.assertEqual(status, 200, archived)
        self.assertEqual(archived["action"], "archive")
        self.assertEqual(archived["ids"], [first, second])
        self.assertEqual(archived["count"], 2)
        self.assertTrue(archived["archived"])
        first_stamp = self.conversation_row(first)["archived_at"]
        second_stamp = self.conversation_row(second)["archived_at"]
        self.assertTrue(first_stamp)
        self.assertEqual(first_stamp, second_stamp)
        self.assertEqual(app.data_generation(), generation)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv IN (?,?)",
                (first, second))["n"], 5)

        status, repeated, _ = self.batch("archive", [second, first])
        self.assertEqual(status, 200, repeated)
        self.assertEqual(
            self.conversation_row(first)["archived_at"], first_stamp)
        self.assertEqual(
            self.conversation_row(second)["archived_at"], second_stamp)

        status, restored, _ = self.batch("restore", [first, second])
        self.assertEqual(status, 200, restored)
        self.assertFalse(restored["archived"])
        self.assertIsNone(self.conversation_row(first)["archived_at"])
        self.assertIsNone(self.conversation_row(second)["archived_at"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv IN (?,?)",
                (first, second))["n"], 5)

    def test_batch_rejects_invalid_or_duplicate_ids_without_mutating_any_row(self):
        first = self.conversation(title="Korunacak bir")
        second = self.conversation(title="Korunacak iki")
        generation = app.data_generation()
        invalid_payloads = (
            {"action": "unknown", "ids": [first, second]},
            {"action": "archive", "ids": first},
            {"action": "archive", "ids": []},
            {"action": "archive", "ids": [first, True]},
            {"action": "archive", "ids": [first, "2"]},
            {"action": "archive", "ids": [first, 2.0]},
            {"action": "archive", "ids": [first, 0]},
            {"action": "archive", "ids": [first, first]},
            {"action": "archive", "ids": list(range(1, 102))},
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                status, _, _ = self.request(
                    "POST", "/api/conversations/batch", payload)
                self.assertEqual(status, 400)
                self.assertIsNone(self.conversation_row(first)["archived_at"])
                self.assertIsNone(self.conversation_row(second)["archived_at"])
                self.assertEqual(app.data_generation(), generation)

    def test_batch_missing_id_is_all_or_nothing_for_archive_and_delete(self):
        first = self.conversation(title="Mevcut bir")
        second = self.conversation(title="Mevcut iki")
        self.messages(first, 1)
        self.messages(second, 1)
        missing = 999999
        generation = app.data_generation()

        status, _, _ = self.batch("archive", [first, missing, second])
        self.assertEqual(status, 404)
        self.assertIsNone(self.conversation_row(first)["archived_at"])
        self.assertIsNone(self.conversation_row(second)["archived_at"])

        status, _, _ = self.batch("delete", [first, missing, second])
        self.assertEqual(status, 404)
        self.assertIsNotNone(self.conversation_row(first))
        self.assertIsNotNone(self.conversation_row(second))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv IN (?,?)",
                (first, second))["n"], 2)
        self.assertEqual(app.data_generation(), generation)

    def test_batch_delete_removes_graphs_once_and_invalidates_affected_formulations(self):
        first = self.conversation(
            mode="terapi", therapist="freud", title="Silinecek terapi")
        second = self.conversation(
            mode="ders", therapist="young", title="Silinecek ders")
        child = self.conversation(
            mode="ders", therapist="ferenczi", submode="supervizyon",
            title="Kalacak türev")
        untouched = self.conversation(
            mode="terapi", therapist="jung", title="Kalacak görüşme")
        self.messages(first, 2, prefix="terapi")
        self.messages(second, 2, prefix="ders")
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET source=? WHERE id=?",
                (first, child))
            conn.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (second, "ders", "young", "silinecek not",
                 app.now(), app.now()))
            formulation_ids = {}
            for mode, therapist, content in (
                    ("terapi", "freud", "eski Freud formülasyonu"),
                    ("ders", "young", "eski Young formülasyonu"),
                    ("terapi", "jung", "korunan Jung formülasyonu")):
                cursor = conn.execute(
                    "INSERT INTO formulations("
                    "mode,therapist,content,note_count,created) "
                    "VALUES(?,?,?,?,?)",
                    (mode, therapist, content, 1, app.now()))
                formulation_ids[(mode, therapist)] = cursor.lastrowid
            note_id = conn.execute(
                "SELECT id FROM notes WHERE conv=?", (second,)).fetchone()[0]
            conn.execute(
                "INSERT INTO formulation_evidence(formulation,note,created) "
                "VALUES(?,?,?)",
                (formulation_ids[("ders", "young")], note_id, app.now()))
        generation = app.data_generation()

        status, result, _ = self.batch("delete", [first, second])

        self.assertEqual(status, 200, result)
        self.assertEqual(result["action"], "delete")
        self.assertEqual(result["ids"], [first, second])
        self.assertEqual(result["count"], 2)
        self.assertIsNone(result["archived"])
        self.assertEqual(app.data_generation(), generation + 1)
        self.assertIsNone(self.conversation_row(first))
        self.assertIsNone(self.conversation_row(second))
        self.assertIsNotNone(self.conversation_row(untouched))
        self.assertIsNone(self.conversation_row(child)["source"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv IN (?,?)",
                (first, second))["n"], 0)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM notes WHERE conv=?",
                (second,))["n"], 0)
        # Silinen kanıta dayanan sürüm artık denetim izi olarak korunur; yalnız
        # etkin hafızadan düşecek biçimde stale işaretlenir. İlişkisiz tarihçe
        # de toplu silmede yok edilmez.
        affected = self.rows(
            "SELECT mode,therapist,stale FROM formulations WHERE "
            "(mode='terapi' AND therapist='freud') OR "
            "(mode='ders' AND therapist='young') ORDER BY therapist")
        self.assertEqual(len(affected), 2)
        self.assertEqual(
            {(row["mode"], row["therapist"]): row["stale"]
             for row in affected},
            {("terapi", "freud"): 0, ("ders", "young"): 1})
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM formulations WHERE "
                "mode='terapi' AND therapist='jung'")["n"], 1)
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_batch_delete_rolls_back_every_conversation_on_sql_failure(self):
        first = self.conversation(title="İlk")
        second = self.conversation(title="İkinci")
        self.messages(first, 1, prefix="ilk")
        self.messages(second, 1, prefix="ikinci")
        with app.db() as conn:
            conn.execute(
                "CREATE TRIGGER fail_second_message_delete "
                "BEFORE DELETE ON messages WHEN OLD.conv={} "
                "BEGIN SELECT RAISE(ABORT,'test rollback'); END"
                .format(second))

        status, _, _ = self.batch("delete", [first, second])

        self.assertEqual(status, 500)
        self.assertIsNotNone(self.conversation_row(first))
        self.assertIsNotNone(self.conversation_row(second))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv IN (?,?)",
                (first, second))["n"], 2)
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_conversation_message_pages_are_bounded_and_do_not_overlap(self):
        conv_id = self.conversation(title="Uzun görüşme")
        self.messages(conv_id, 205, prefix="uzun")

        status, newest, _ = self.request(
            "GET", "/api/conversation?id={}&limit=80".format(conv_id))

        self.assertEqual(status, 200, newest)
        self.assertEqual(newest["message_count"], 205)
        self.assertEqual(newest["loaded_message_count"], 80)
        self.assertTrue(newest["has_more_messages"])
        newest_ids = [row["id"] for row in newest["messages"]]
        self.assertEqual(newest_ids, sorted(newest_ids))

        status, older, _ = self.request(
            "GET", "/api/conversation?id={}&limit=80&before_id={}"
            .format(conv_id, newest["oldest_message_id"]))

        self.assertEqual(status, 200, older)
        self.assertEqual(older["loaded_message_count"], 80)
        self.assertTrue(older["has_more_messages"])
        older_ids = [row["id"] for row in older["messages"]]
        self.assertFalse(set(newest_ids) & set(older_ids))
        self.assertLess(max(older_ids), min(newest_ids))

    def test_conversation_message_page_rejects_unbounded_inputs(self):
        conv_id = self.conversation(title="Sayfalı görüşme")
        for suffix in ("limit=0", "limit=201", "limit=x",
                       "limit=80&before_id=0"):
            with self.subTest(suffix=suffix):
                status, _, _ = self.request(
                    "GET", "/api/conversation?id={}&{}".format(
                        conv_id, suffix))
                self.assertEqual(status, 400)


class ConversationArchiveUISourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")

    def test_sidebar_exposes_active_and_archive_views(self):
        self.assertIn('id="conversationViews" role="tablist"', self.html)
        self.assertIn('id="activeConvsBtn"', self.html)
        self.assertIn('id="archivedConvsBtn"', self.html)
        self.assertIn("setConversationView('archived')", self.html)
        self.assertIn("bindRovingTablist('.convViewBtn'", self.html)
        self.assertIn("bindRovingTablist('.modeTab'", self.html)
        self.assertIn("tab.setAttribute('aria-selected'", self.html)
        self.assertIn("tab.tabIndex=active?0:-1", self.html)
        self.assertIn("item.getAttribute('aria-hidden')!=='true'", self.html)
        for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
                    "Home", "End"):
            self.assertIn(key, self.html)

    def test_rows_keep_archive_restore_and_permanent_delete_actions(self):
        self.assertIn('class="convOpen"', self.html)
        self.assertIn('class="convAction archiveToggle"', self.html)
        self.assertIn('class="convAction del"', self.html)
        self.assertIn("d.querySelector('.convOpen').onclick=()=>openConv(r.id)",
                      self.html)
        self.assertNotIn("activateOnKeyboard(d,()=>openConv(r.id))", self.html)
        self.assertIn("api('/api/archive',{id:row.id,archived})", self.html)
        self.assertIn("api('/api/delete',{id:ids[0]})", self.html)
        self.assertIn(
            "api('/api/conversations/batch',{action:'delete',ids})",
            self.html)
        self.assertIn('id="deleteConversationOverlay"', self.html)
        self.assertNotIn(
            "confirm('Bu görüşme ve notu silinsin mi?')", self.html)

    def test_stale_list_responses_cannot_redraw_deleted_rows(self):
        self.assertIn(
            "let conversationListRequestSequence = 0;", self.html)
        self.assertIn(
            "requestSequence!==conversationListRequestSequence", self.html)
        self.assertIn("await refreshConversationLists();", self.html)
        self.assertIn(
            "const tasks=[loadConvs()];", self.html)
        self.assertIn("button.disabled=true", self.html)

    def test_mobile_selection_uses_guarded_long_press_and_atomic_actions(self):
        self.assertIn('id="mobileConversationSelectionBar"', self.html)
        self.assertIn('id="mobileConversationArchiveSelected"', self.html)
        self.assertIn('id="mobileConversationPinSelected"', self.html)
        self.assertIn('id="mobileConversationDeleteSelected"', self.html)
        self.assertIn(
            "state.timer=setTimeout(()=>{", self.html)
        self.assertIn("},520);", self.html)
        self.assertIn(
            "Math.hypot(event.clientX-state.startX,"
            "event.clientY-state.startY)>10", self.html)
        self.assertIn(
            "const action=restoring?'restore':'archive';", self.html)
        self.assertIn("{action,ids}", self.html)
        self.assertIn(
            "const action=shouldPin?'pin':'unpin';", self.html)
        self.assertIn("result.pinned!==shouldPin", self.html)
        self.assertIn(
            "if(mobileHomeIsOpen()&&mobileConversationSelectionMode)",
            self.html)

    def test_mobile_home_shows_one_latest_row_and_history_in_chat_overflow(self):
        self.assertIn("function groupMobileConversations(rows)", self.html)
        self.assertIn("mobileConversationGroupKey(row)", self.html)
        self.assertIn("function latestMobileConversationRows(rows)", self.html)
        loader = self.html[
            self.html.index("async function loadMobileHomeConversations()"):
            self.html.index("function mobileMasterHistoryStamp(")]
        self.assertIn("const latestRows=latestMobileConversationRows(orderedRows)",
                      loader)
        self.assertIn("latestRows.forEach(latest=>", loader)
        self.assertNotIn("group.rows.slice(1)", loader)
        self.assertIn('id="mobileMasterHistoryOpen"', self.html)
        self.assertIn('id="mobileMasterHistoryOverlay"', self.html)
        self.assertIn("async function showMobileMasterHistory()", self.html)
        self.assertIn("api('/api/conversations?archived=1')", self.html)

    def test_active_order_has_desktop_and_grouped_mobile_safeguards(self):
        compact = "".join(self.html.split())
        self.assertIn(
            "function orderActiveConversationRows(rows)", self.html)
        self.assertIn(
            "Number(!!(a&&a.ended))-Number(!!(b&&b.ended))", self.html)
        self.assertIn(
            "constorderedRows=mobileConversationView==='archived'?"
            "[...(Array.isArray(rows)?rows:[])]:"
            "orderActiveConversationRows(rows);", compact)
        self.assertIn(
            "const latestRows=latestMobileConversationRows(orderedRows);",
            self.html)
        self.assertIn("latestRows.forEach(latest=>", self.html)
        self.assertIn(
            "?rows:orderActiveConversationRows(rows);", self.html)


if __name__ == "__main__":
    unittest.main()
