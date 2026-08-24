"""Şema Terapi odak seçimi: usta sunar, kullanıcı seçer.

Akış: kullanıcı konuşur → usta dinler → eşiğe gelince en fazla üç mod adayı
kart olarak sunar → kullanıcı **butonla** seçer ya da hiçbirini seçmez.
Buradaki testler seçimin kullanıcıda kaldığını ve modelin katalog dışına
çıkamadığını korur.
"""

import threading
from unittest import mock

from support import app
from test_schema_path import SchemaPathTests


class SchemaFocusSelectionTests(SchemaPathTests):
    """Kurulum yardımcıları (completed_turns/candidate/start) devralınır."""

    def path_in_focus(self):
        """Odak aşamasında bekleyen bir çalışma yolu kur."""
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path_id = self.legacy_start_fixture(claim)[1]["active_path"]["id"]
        for index, (kind, value) in enumerate((
                ("current_trigger", "Mesaj gelmeyince içim daraldı"),
                ("need", "Güvende hissetmek"))):
            self.assertEqual(self.post({
                "action": "record", "conv_id": self.conv, "path_id": path_id,
                "kind": kind, "value": value,
                "request_id": "focus-record-{:04d}".format(index),
            })[0], 200)
        self.assertEqual(self.post({
            "action": "advance", "conv_id": self.conv, "path_id": path_id,
            "to_phase": "focus", "request_id": "focus-advance-0001",
        })[0], 200)
        return path_id

    def offer(self, path_id, candidates, suffix="offer-0001"):
        return self.post({
            "action": "offer_focus", "conv_id": self.conv,
            "path_id": path_id, "candidates": candidates,
            "request_id": "focus-{}".format(suffix),
        })

    # --- Sunma ---

    def test_focus_offer_lists_user_selectable_mode_cards(self):
        path_id = self.path_in_focus()
        status, body = self.offer(path_id, [
            {"mode_key": "detached_protector", "evidence": "duvar örüyorum"},
            {"mode_key": "punitive_parent", "evidence": "kendime kızıyorum"},
        ])
        self.assertEqual(status, 200, body)
        offer = body["focus"]["offer"]
        self.assertEqual(len(offer["candidates"]), 2)
        first = offer["candidates"][0]
        # Etiket sunucudaki kütüphaneden gelir, modelden değil.
        self.assertEqual(first["mode_key"], "detached_protector")
        self.assertEqual(first["label"], "Kopuk Korungan / Kaçınan")
        self.assertEqual(first["evidence"], "duvar örüyorum")
        self.assertIn("choose_focus", body["allowed_actions"])
        self.assertIn("decline_focus", body["allowed_actions"])

    def test_offer_rejects_modes_outside_the_reviewed_library(self):
        """Model klinik görünümlü bir mod uydurup karta sokamaz."""
        path_id = self.path_in_focus()
        status, body = self.offer(
            path_id, [{"mode_key": "narsistik_cekirdek",
                       "evidence": "uydurma"}], suffix="bad-0001")
        self.assertEqual(status, 400, body)

    def test_healthy_adult_is_a_resource_not_a_problem_focus(self):
        """Sağlıklı Yetişkin ve Mutlu Çocuk üzerinde 'çalışılmaz'."""
        path_id = self.path_in_focus()
        for index, key in enumerate(("healthy_adult", "happy_child")):
            status, _ = self.offer(
                path_id, [{"mode_key": key}],
                suffix="resource-{:04d}".format(index))
            self.assertEqual(status, 400)

    def test_offer_is_capped_at_three_candidates(self):
        path_id = self.path_in_focus()
        status, _ = self.offer(path_id, [
            {"mode_key": "detached_protector"},
            {"mode_key": "punitive_parent"},
            {"mode_key": "angry_child"},
            {"mode_key": "compliant_surrender"},
        ], suffix="cap-0001")
        self.assertEqual(status, 400)

    def test_same_mode_cannot_be_offered_twice(self):
        path_id = self.path_in_focus()
        status, _ = self.offer(path_id, [
            {"mode_key": "detached_protector"},
            {"mode_key": "detached_protector"},
        ], suffix="dup-0001")
        self.assertEqual(status, 400)

    # --- Seçme ---

    def test_user_choice_is_recorded_and_opens_the_method_phase(self):
        path_id = self.path_in_focus()
        self.assertEqual(self.offer(path_id, [
            {"mode_key": "detached_protector"},
            {"mode_key": "angry_child"},
        ])[0], 200)
        status, body = self.post({
            "action": "choose_focus", "conv_id": self.conv,
            "path_id": path_id, "mode_key": "angry_child",
            "request_id": "focus-choose-0001",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["focus"]["chosen"]["mode_key"], "angry_child")
        self.assertEqual(body["focus"]["chosen"]["label"], "Öfkeli Çocuk")
        self.assertIn("advance", body["allowed_actions"])

    def test_user_cannot_be_given_a_mode_that_was_never_offered(self):
        """Seçim yalnız gerçekten sunulan kartlar arasından yapılabilir."""
        path_id = self.path_in_focus()
        self.assertEqual(
            self.offer(path_id, [{"mode_key": "detached_protector"}])[0], 200)
        status, body = self.post({
            "action": "choose_focus", "conv_id": self.conv,
            "path_id": path_id, "mode_key": "punitive_parent",
            "request_id": "focus-choose-bad-0001",
        })
        self.assertEqual(status, 409, body)

    def test_declining_every_candidate_is_a_complete_answer(self):
        """'Hiçbiri' seçilebilir; kullanıcı seçmeye zorlanmaz."""
        path_id = self.path_in_focus()
        self.assertEqual(self.offer(path_id, [
            {"mode_key": "detached_protector"},
        ])[0], 200)
        status, body = self.post({
            "action": "decline_focus", "conv_id": self.conv,
            "path_id": path_id, "request_id": "focus-decline-0001",
        })
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["focus"]["offer"])
        self.assertIsNone(body["focus"]["chosen"])
        # Reddetmek yolu kapatmaz; usta yeniden sunabilir.
        self.assertIn("offer_focus", body["allowed_actions"])

    def test_method_phase_needs_a_chosen_focus(self):
        """Kullanıcı bir odak seçmeden yöntem aşamasına geçilemez."""
        path_id = self.path_in_focus()
        status, body = self.post({
            "action": "advance", "conv_id": self.conv, "path_id": path_id,
            "to_phase": "method", "request_id": "focus-skip-0001",
        })
        self.assertEqual(status, 409, body)

    # --- Erken etiketleme yasağı ---

    def test_offer_is_blocked_before_enough_listening(self):
        """Eşik dolmadan mod adı sunulmaz: erken etiketleme kapatmadır."""
        path_id = self.path_in_focus()
        # Tamamlanmış turların bir kısmını geri al: eşiğin altına düş.
        with app.db() as connection:
            keep = connection.execute(
                "SELECT request_id FROM chat_requests WHERE conv=? "
                "ORDER BY rowid LIMIT 1",
                (self.conv,)).fetchone()["request_id"]
            connection.execute(
                "DELETE FROM chat_requests WHERE conv=? AND request_id<>?",
                (self.conv, keep))
        status, body = self.offer(
            path_id, [{"mode_key": "detached_protector"}],
            suffix="early-0001")
        self.assertEqual(status, 409, body)
        self.assertIn("yeterli", body["error"].casefold())

    # --- Ustanın prompt bağlamı ---

    def test_prompt_tells_the_master_to_wait_for_the_user_choice(self):
        """Usta kendi seçip seçilmiş gibi konuşamaz."""
        path_id = self.path_in_focus()
        with app.db() as connection:
            conv = connection.execute(
                "SELECT * FROM conversations WHERE id=?",
                (self.conv,)).fetchone()
        # Aday sunulmadan önce: sunma aşaması anlatılmalı.
        context = app.schema_path_prompt_context(conv)
        self.assertIn("Odak sunma aşaması", context)
        self.assertIn("kullanıcı seçer", context)

        self.assertEqual(self.offer(path_id, [
            {"mode_key": "detached_protector", "evidence": "duvar örüyorum"},
        ])[0], 200)
        context = app.schema_path_prompt_context(conv)
        self.assertIn("Odak seçimi kullanıcıda", context)
        self.assertIn("Kopuk Korungan", context)
        self.assertIn("hiçbiri", context.casefold())

    def test_prompt_names_the_chosen_mode_after_selection(self):
        path_id = self.path_in_focus()
        self.assertEqual(self.offer(path_id, [
            {"mode_key": "angry_child"}])[0], 200)
        self.assertEqual(self.post({
            "action": "choose_focus", "conv_id": self.conv,
            "path_id": path_id, "mode_key": "angry_child",
            "request_id": "focus-prompt-choose-0001",
        })[0], 200)
        with app.db() as connection:
            conv = connection.execute(
                "SELECT * FROM conversations WHERE id=?",
                (self.conv,)).fetchone()
        context = app.schema_path_prompt_context(conv)
        self.assertIn("çalışmayı seçtiği mod: Öfkeli Çocuk", context)
        # Seçim yapıldıktan sonra "bekle" yönergesi kalkmalı.
        self.assertNotIn("Odak seçimi kullanıcıda", context)

    # --- Kerem Genç'te tercih hazır, cihaz onayı ayrı ---

    def test_schema_mode_preference_needs_local_consent_for_new_kerem(self):
        """Yeni Kerem görüşmesi cihazın sağlayıcı onayını varsayamaz."""
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "young", "mode": "terapi"})
        _, body, _ = self.request(
            "GET", "/api/schema-path?conv_id={}".format(created["id"]))
        self.assertFalse(body["schema_mode"]["enabled"], body["schema_mode"])
        self.assertTrue(body["schema_mode"]["preference_enabled"])
        self.assertTrue(body["schema_mode"]["pending_device_confirmation"])
        self.assertEqual(body["allowed_actions"], ["set_mode"])
        with app.db() as connection:
            meta = connection.execute(
                "SELECT * FROM session_meta WHERE conv=?", (created["id"],)
            ).fetchone()
        self.assertEqual(meta["schema_mode_initialized"], 0)
        self.assertEqual(meta["schema_mode_provider"], "")
        self.assertEqual(meta["schema_mode_model"], "")

    def test_default_on_does_not_leak_to_other_masters_or_lessons(self):
        """Yalnız Kerem'in terapi görüşmesi; ders ve diğer ustalar hariç."""
        for therapist, mode in (("young", "ders"), ("freud", "terapi")):
            _, created, _ = self.request("POST", "/api/new", {
                "therapist": therapist, "mode": mode})
            with app.db() as connection:
                state = app.schema_mode_state(connection, created["id"])
            self.assertFalse(
                state["enabled"], "{}/{}".format(therapist, mode))

    def test_default_on_is_skipped_for_guest_conversations(self):
        """Misafir görüşmesinde kalıcı mod açılmaz."""
        self.assertFalse(
            app.schema_mode_default_on("young", "terapi", "konsey"))
        self.assertTrue(app.schema_mode_default_on("young", "terapi", ""))
        self.assertFalse(app.schema_mode_default_on("young", "ders", ""))
        self.assertFalse(app.schema_mode_default_on("freud", "terapi", ""))

    # --- Odak önerisi kendiliğinden hazırlanır ---

    def test_focus_offer_appears_without_anyone_calling_it(self):
        """`offer_focus` ölü uçtu; kart gerçek kullanımda hiç çıkmıyordu."""
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        with app.db() as connection:
            connection.execute(
                "UPDATE psych_claims SET mode_key='detached_protector' "
                "WHERE id=?", (claim,))
        path_id = self.legacy_start_fixture(claim)[1]["active_path"]["id"]
        for index, (kind, value) in enumerate((
                ("current_trigger", "Mesaj gelmeyince daraldım"),
                ("need", "Güvende hissetmek"))):
            self.assertEqual(self.post({
                "action": "record", "conv_id": self.conv, "path_id": path_id,
                "kind": kind, "value": value,
                "request_id": "auto-focus-rec-{:04d}".format(index),
            })[0], 200)
        status, body = self.post({
            "action": "advance", "conv_id": self.conv, "path_id": path_id,
            "to_phase": "focus", "request_id": "auto-focus-advance-01",
        })
        self.assertEqual(status, 200, body)
        offer = body["focus"]["offer"]
        self.assertIsNotNone(offer, body["focus"])
        self.assertTrue(offer["candidates"])
        self.assertEqual(
            offer["candidates"][0]["mode_key"], "detached_protector")

    def test_focus_offer_appears_after_a_later_third_safe_turn(self):
        """Focus'a erken giren yol üçüncü turdan sonra kalıcı takılmaz."""
        self.completed_turns(2)
        claim = self.candidate(status="confirmed")
        with app.db() as connection:
            connection.execute(
                "UPDATE psych_claims SET mode_key='detached_protector' "
                "WHERE id=?", (claim,))
        path_id = self.legacy_start_fixture(claim)[1]["active_path"]["id"]
        for index, (kind, value) in enumerate((
                ("current_trigger", "Mesaj gelmeyince daraldım"),
                ("need", "Güvende hissetmek"))):
            self.assertEqual(self.post({
                "action": "record", "conv_id": self.conv,
                "path_id": path_id, "kind": kind, "value": value,
                "request_id": "late-focus-rec-{:04d}".format(index),
            })[0], 200)
        status, body = self.post({
            "action": "advance", "conv_id": self.conv,
            "path_id": path_id, "to_phase": "focus",
            "request_id": "late-focus-advance-0001",
        })
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["focus"]["offer"])

        self.completed_turns(1)
        status, refreshed = self.get()
        self.assertEqual(status, 200, refreshed)
        self.assertEqual(
            refreshed["focus"]["offer"]["candidates"][0]["mode_key"],
            "detached_protector")

        # GET ile oluşturulan teklif commit edilir ve her yenilemede çoğalmaz.
        self.assertEqual(self.get()[1]["focus"]["offer"]["id"],
                         refreshed["focus"]["offer"]["id"])
        with app.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) n FROM schema_focus_offers WHERE path=?",
                (path_id,)).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_concurrent_dashboard_reads_create_only_one_focus_offer(self):
        """İki GET aynı anda teklif üretip reddi etkisiz bırakamaz."""
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        with app.db() as connection:
            connection.execute(
                "UPDATE psych_claims SET mode_key='detached_protector' "
                "WHERE id=?", (claim,))
        path_id = self.legacy_start_fixture(claim)[1]["active_path"]["id"]
        # Yalnız dashboard'un geç-eşik üretimini sınamak için yolu doğrudan
        # focus'a getir; POST geçişi üçüncü turda teklifi hemen üretirdi.
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET phase='focus' WHERE id=?",
                (path_id,))

        original = app.ensure_schema_focus_offer
        first_inside = threading.Event()
        second_inside = threading.Event()
        release = threading.Event()
        state_lock = threading.Lock()
        state = {"active": 0, "maximum": 0}

        def observed_ensure(*args, **kwargs):
            with state_lock:
                state["active"] += 1
                state["maximum"] = max(
                    state["maximum"], state["active"])
                if state["active"] == 1:
                    first_inside.set()
                else:
                    second_inside.set()
            release.wait(2)
            try:
                return original(*args, **kwargs)
            finally:
                with state_lock:
                    state["active"] -= 1

        payloads = []
        errors = []

        def read_dashboard():
            try:
                payloads.append(app.schema_path_payload(self.conv))
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with mock.patch.object(
                app, "ensure_schema_focus_offer",
                side_effect=observed_ensure):
            first = threading.Thread(target=read_dashboard)
            second = threading.Thread(target=read_dashboard)
            first.start()
            self.assertTrue(first_inside.wait(1))
            second.start()
            # Eski kilitsiz uygulamada ikinci GET burada aynı üretim
            # fonksiyonuna girerdi. Kilitli uygulamada ilk commit'i bekler.
            second_inside.wait(0.25)
            release.set()
            first.join(2)
            second.join(2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(state["maximum"], 1)
        self.assertEqual(len(payloads), 2)
        offer_ids = {
            payload["focus"]["offer"]["id"] for payload in payloads}
        self.assertEqual(len(offer_ids), 1)
        with app.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) n FROM schema_focus_offers WHERE path=?",
                (path_id,)).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_mode_disable_wins_over_a_dashboard_waiting_on_the_write_lock(self):
        """GET kilitte beklerken kapanan mod, eski onayla kart üretemez."""
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        with app.db() as connection:
            connection.execute(
                "UPDATE psych_claims SET mode_key='detached_protector' "
                "WHERE id=?", (claim,))
        path_id = self.legacy_start_fixture(claim)[1]["active_path"]["id"]
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET phase='focus' WHERE id=?",
                (path_id,))

        prelock_read = threading.Event()
        original_active_path = app.schema_active_path_row

        def observed_active_path(*args, **kwargs):
            row = original_active_path(*args, **kwargs)
            prelock_read.set()
            return row

        payloads = []
        errors = []

        def read_dashboard():
            try:
                payloads.append(app.schema_path_payload(self.conv))
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with mock.patch.object(
                app, "schema_active_path_row",
                side_effect=observed_active_path):
            # RLock lets this thread perform the explicit mode change while
            # the GET is guaranteed to be waiting at the write boundary.
            with app.DATA_WRITE_LOCK:
                reader = threading.Thread(target=read_dashboard)
                reader.start()
                self.assertTrue(prelock_read.wait(1))
                app.set_schema_mode(self.conv, False)
            reader.join(2)

        self.assertFalse(reader.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(payloads), 1)
        self.assertFalse(payloads[0]["schema_mode"]["enabled"])
        self.assertIsNone(payloads[0]["focus"]["offer"])
        with app.db() as connection:
            path = connection.execute(
                "SELECT status FROM schema_paths WHERE id=?",
                (path_id,)).fetchone()
            count = connection.execute(
                "SELECT COUNT(*) n FROM schema_focus_offers WHERE path=?",
                (path_id,)).fetchone()["n"]
        self.assertEqual(path["status"], "paused")
        self.assertEqual(count, 0)

    def test_auto_offer_respects_the_early_labelling_threshold(self):
        """Eşik dolmadan mod adı sunulmaz."""
        with app.db() as connection:
            path = connection.execute(
                "SELECT 1").fetchone()
        cards = None
        with app.db() as connection:
            cards = app.schema_auto_focus_candidates(connection, self.conv)
        # Hiç kanıt yokken aday üretilmez.
        self.assertEqual(cards, [])

    def test_auto_offer_only_uses_catalogued_modes(self):
        """Katalog dışı bir mode_key karta dönüşmez."""
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        with app.db() as connection:
            connection.execute(
                "UPDATE psych_claims SET mode_key='uydurma_mod' WHERE id=?",
                (claim,))
            cards = app.schema_auto_focus_candidates(connection, self.conv)
        self.assertEqual(cards, [])

    def test_declined_offer_is_not_forced_again(self):
        """Kullanıcı 'hiçbiri' dediyse öneri yeniden dayatılmaz."""
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        with app.db() as connection:
            connection.execute(
                "UPDATE psych_claims SET mode_key='detached_protector' "
                "WHERE id=?", (claim,))
        path_id = self.legacy_start_fixture(claim)[1]["active_path"]["id"]
        for index, (kind, value) in enumerate((
                ("current_trigger", "Olay"), ("need", "İhtiyaç"))):
            self.post({
                "action": "record", "conv_id": self.conv, "path_id": path_id,
                "kind": kind, "value": value,
                "request_id": "decline-rec-{:04d}".format(index)})
        self.post({
            "action": "advance", "conv_id": self.conv, "path_id": path_id,
            "to_phase": "focus", "request_id": "decline-advance-0001"})
        self.assertEqual(self.post({
            "action": "decline_focus", "conv_id": self.conv,
            "path_id": path_id, "request_id": "decline-now-000001",
        })[0], 200)
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)).fetchone()
            app.ensure_schema_focus_offer(connection, self.conv, path)
            again = app.schema_focus_active_offer(connection, path_id)
        self.assertIsNone(again)

    # --- Öneri yanıtla aynı çağrıda gelir ---

    def test_suggestion_line_is_stripped_from_the_reply(self):
        """Mod satırı kullanıcıya asla gösterilmez."""
        text, suggestion = app.split_schema_suggestion(
            "Anlıyorum, bu tanıdık geliyor.\n"
            "[[MOD]] detached_protector | duvar örüyorum")
        self.assertEqual(text, "Anlıyorum, bu tanıdık geliyor.")
        self.assertEqual(suggestion["mode_key"], "detached_protector")
        self.assertEqual(suggestion["evidence"], "duvar örüyorum")

    def test_invalid_mode_key_never_leaks_to_the_user(self):
        """Katalog dışı anahtar gelse bile ham işaret gösterilmez."""
        text, suggestion = app.split_schema_suggestion(
            "Yanıt.\n[[MOD]] uydurma_mod | bir şey")
        self.assertEqual(text, "Yanıt.")
        self.assertIsNone(suggestion)
        self.assertNotIn("[[MOD]]", text)

    def test_reply_without_a_suggestion_is_untouched(self):
        text, suggestion = app.split_schema_suggestion("Sadece yanıt.")
        self.assertEqual(text, "Sadece yanıt.")
        self.assertIsNone(suggestion)

    def test_prompt_forbids_naming_the_mode_in_the_reply(self):
        """Usta etiketi konuşmaya taşımamalı; erken etiketleme yasağı."""
        self.completed_turns(2)
        with app.db() as connection:
            conv = connection.execute(
                "SELECT * FROM conversations WHERE id=?",
                (self.conv,)).fetchone()
        prompt = app.schema_inline_suggestion_prompt(conv)
        self.assertIn("mod adını geçirme", prompt)
        self.assertIn("Kanıt zayıfsa satırı HİÇ yazma", prompt)
        self.assertIn("kullanıcıya gösterilmez", prompt)

    def test_inline_prompt_waits_for_third_pair_and_matches_provider_consent(self):
        with app.db() as connection:
            conv = connection.execute(
                "SELECT * FROM conversations WHERE id=?", (self.conv,)
            ).fetchone()
        provider, model = app._configured_provider_model_snapshot()
        self.assertEqual(app.schema_inline_suggestion_prompt(
            conv, provider, model), "")
        self.completed_turns(1)
        self.assertEqual(app.schema_inline_suggestion_prompt(
            conv, provider, model), "")
        self.completed_turns(1)
        self.assertIn("[[MOD]]", app.schema_inline_suggestion_prompt(
            conv, provider, model))
        self.assertEqual(app.schema_inline_suggestion_prompt(
            conv, "different-provider", "different-model"), "")

    def test_no_suggestion_prompt_while_a_path_is_open(self):
        """Çalışma sürerken yeni öneri istenmez."""
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        self.legacy_start_fixture(claim)
        with app.db() as connection:
            conv = connection.execute(
                "SELECT * FROM conversations WHERE id=?",
                (self.conv,)).fetchone()
        self.assertEqual(app.schema_inline_suggestion_prompt(conv), "")
