import json
from unittest import mock

from support import HTTPTestCase, app


class LivingMapTrustChainTests(HTTPTestCase):
    """Source lineage and explicit-consent boundaries for the living map."""

    stamp = "2026-07-20 12:00"

    def prompt(self, conv_id, current_text=""):
        conv = self.conversation_row(conv_id)
        return app.build_system_prompt(
            conv,
            app.context_notes(conv, conv_id),
            app.latest_approved_formulation(
                conv["mode"], conv["therapist"]),
            None,
            current_user_text=current_text,
        )

    def user_message(self, conv_id, content, created=None):
        with app.db() as conn:
            return conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user',?,?)",
                (conv_id, content, created or self.stamp),
            ).lastrowid

    def assistant_message(self, conv_id, content, created=None):
        with app.db() as conn:
            return conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'assistant',?,?)",
                (conv_id, content, created or self.stamp),
            ).lastrowid

    def completed_turn(self, conv_id, content, created=None):
        stamp = created or self.stamp
        user_id = self.user_message(conv_id, content, stamp)
        assistant_id = self.assistant_message(conv_id, "tamamlanmış yanıt", stamp)
        with app.db() as conn:
            job_id = conn.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat_response',?,'succeeded',?,?)",
                (conv_id, stamp, stamp)).lastrowid
            conn.execute(
                "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                "assistant_message,status,created,updated) VALUES(?,?,?,?,?,"
                "'completed',?,?)",
                ("living-map-turn-{:012d}".format(user_id), job_id, conv_id,
                 user_id, assistant_id, stamp, stamp))
        return user_id

    def candidate_json(
            self, supporting_ids, *, claim_type="pattern",
            title="Eleştiride geri çekilme",
            statement="Eleştiri beklediğimde geri çekilme eğilimim olabilir",
            existing_claim_id=None, counterexample_ids=None):
        return json.dumps({
            "insights": [{
                "existing_claim_id": existing_claim_id,
                "claim_type": claim_type,
                "title": title,
                "statement": statement,
                "trigger": "Eleştiri beklediğimde",
                "experience": "Gerilim ve utanma hissediyorum",
                "response": "Sessizleşip geri çekiliyorum",
                "short_term_effect": "Çatışmadan korunuyorum",
                "long_term_effect": "İhtiyacımı anlatamıyorum",
                "need": "Güvenli biçimde duyulmak",
                "context": "İş ortamındaki eleştiriler",
                "counterexample": (
                    "Güvendiğim kişilerle konuşabiliyorum"
                    if counterexample_ids else ""),
                "supporting_message_ids": list(supporting_ids),
                "counterexample_message_ids": list(
                    counterexample_ids or []),
            }],
        }, ensure_ascii=False)

    def add_claim(
            self, source_conv, *, title, status="confirmed",
            claim_type="pattern", scope="therapist", sensitive=0,
            therapist="freud", statement=None, content=None):
        message_id = self.user_message(
            source_conv, content or "Bu durumu kendi sözlerimle anlattım.")
        with app.db() as conn:
            observation_id = conn.execute(
                "INSERT INTO psych_observations("
                "conv,source_message,therapist,dimension,content,"
                "source_created,created) VALUES("
                "?,?,?,'user_report',?,?,?)",
                (source_conv, message_id, therapist,
                 content or "Bu durumu kendi sözlerimle anlattım.",
                 self.stamp, self.stamp),
            ).lastrowid
            claim_id = conn.execute(
                "INSERT INTO psych_claims("
                "public_id,source_conv,therapist,lens,claim_type,title,"
                "statement,status,scope,sensitive,first_seen,last_seen,"
                "created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "claim-{}-{}".format(source_conv, message_id),
                    source_conv, therapist, "neutral", claim_type, title,
                    statement or title, status, scope, sensitive,
                    self.stamp, self.stamp, self.stamp, self.stamp,
                ),
            ).lastrowid
            evidence_id = conn.execute(
                "INSERT INTO psych_claim_evidence("
                "claim,observation,relation,created) "
                "VALUES(?,?,'supports',?)",
                (claim_id, observation_id, self.stamp),
            ).lastrowid
            if status in app.LIVING_MAP_ACTIVE_STATUSES:
                conn.execute(
                    "UPDATE psych_claim_evidence SET review_status='accepted' "
                    "WHERE id=?", (evidence_id,))
                conn.execute(
                    "UPDATE psych_claims SET reviewed_evidence_id=? "
                    "WHERE id=?", (evidence_id, claim_id))
        return claim_id, message_id

    def add_support(self, claim_id, source_conv, content):
        message_id = self.user_message(source_conv, content)
        with app.db() as conn:
            therapist = conn.execute(
                "SELECT therapist FROM psych_claims WHERE id=?",
                (claim_id,),
            ).fetchone()["therapist"]
            observation_id = conn.execute(
                "INSERT INTO psych_observations("
                "conv,source_message,therapist,dimension,content,"
                "source_created,created) VALUES("
                "?,?,?,'user_report',?,?,?)",
                (source_conv, message_id, therapist, content,
                 self.stamp, self.stamp),
            ).lastrowid
            conn.execute(
                "INSERT INTO psych_claim_evidence("
                "claim,observation,relation,created) "
                "VALUES(?,?,'supports',?)",
                (claim_id, observation_id, self.stamp),
            )
        return message_id

    def test_pending_formulation_is_not_prompt_visible_until_explicitly_approved(self):
        conv_id = self.conversation()
        source = self.conversation(title="Ham notun kaynağı")
        with app.db() as conn:
            note_id = conn.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,approved,scope,"
                "sensitive,updated) VALUES("
                "?,'terapi','freud','ONAYLI-HAM-NOT',?,"
                "1,'therapist',0,?)",
                (source, self.stamp, self.stamp),
            ).lastrowid
            formulation_id = conn.execute(
                "INSERT INTO formulations("
                "mode,therapist,content,note_count,through_note_id,created,"
                "status,scope,sensitive,updated) VALUES("
                "'terapi','freud','ONAYSIZ-FORMULASYON',1,?,?,"
                "'pending','therapist',0,?)",
                (note_id, self.stamp, self.stamp),
            ).lastrowid
            conn.execute(
                "INSERT INTO formulation_evidence("
                "formulation,note,created) VALUES(?,?,?)",
                (formulation_id, note_id, self.stamp),
            )

        self.assertIsNone(
            app.latest_approved_formulation("terapi", "freud"))
        pending_prompt = self.prompt(conv_id)
        self.assertNotIn("ONAYSIZ-FORMULASYON", pending_prompt)
        self.assertIn("ONAYLI-HAM-NOT", pending_prompt)

        status, body, _ = self.request(
            "POST", "/api/formulation-control",
            {"id": formulation_id, "action": "approve"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["formulation"]["status"], "approved")
        approved_prompt = self.prompt(conv_id)
        self.assertIn("ONAYSIZ-FORMULASYON", approved_prompt)
        self.assertNotIn("ONAYLI-HAM-NOT", approved_prompt)

    def test_next_formulation_versions_prior_approval_with_only_new_evidence(self):
        old_text = "ESKI-MODEL-SENTEZI-KANIT-DEGIL"
        source = self.conversation(title="Önceki sürümün kaynak notu")
        with app.db() as conn:
            old_note_id = conn.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,approved,scope,"
                "sensitive,updated) VALUES("
                "?,'terapi','freud','ESKI-KULLANICI-NOTU',?,"
                "1,'therapist',0,?)",
                (source, self.stamp, self.stamp),
            ).lastrowid
            base_id = conn.execute(
                "INSERT INTO formulations("
                "mode,therapist,content,note_count,through_note_id,created,"
                "status,scope,sensitive,updated) VALUES("
                "'terapi','freud',?,1,?,?,'approved','therapist',0,?)",
                (old_text, old_note_id, self.stamp, self.stamp),
            ).lastrowid
            conn.execute(
                "INSERT INTO formulation_evidence(formulation,note,created) "
                "VALUES(?,?,?)", (base_id, old_note_id, self.stamp))
        for index in range(app.FORMULATE_EVERY):
            source = self.conversation(title="Not {}".format(index))
            with app.db() as conn:
                conn.execute(
                    "INSERT INTO notes("
                    "conv,mode,therapist,content,created,approved,scope,"
                    "sensitive,updated) VALUES("
                    "?,'terapi','freud',?,?,1,'therapist',0,?)",
                    (source, "KULLANICI-NOTU-{}".format(index),
                     self.stamp, self.stamp),
                )

        captured = []

        def complete(messages, **_kwargs):
            captured.extend(message["content"] for message in messages)
            return "YENI-FORMULASYON-TASLAGI"

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            self.assertTrue(app.maybe_formulate("terapi", "freud"))

        corpus = "\n".join(captured)
        self.assertIn(old_text, corpus)
        self.assertIn("YENİ KANIT DEĞİLDİR", corpus)
        for index in range(app.FORMULATE_EVERY):
            self.assertIn("KULLANICI-NOTU-{}".format(index), corpus)
        latest = app.latest_formulation("terapi", "freud")
        self.assertEqual(latest["content"], "YENI-FORMULASYON-TASLAGI")
        self.assertEqual(latest["status"], "pending")
        self.assertEqual(latest["base_formulation"], base_id)
        with app.db() as conn:
            evidence = conn.execute(
                "SELECT note FROM formulation_evidence WHERE formulation=? "
                "ORDER BY note", (latest["id"],)).fetchall()
        self.assertEqual(len(evidence), app.FORMULATE_EVERY)
        self.assertNotIn(old_note_id, [row["note"] for row in evidence])

    def test_generation_exposes_only_user_messages_and_creates_pending_claim(self):
        conv_id = self.conversation()
        user_ids = [
            self.user_message(conv_id, "KULLANICI-KAYNAGI-{}".format(index))
            for index in range(app.LIVING_MAP_MIN_USER_MESSAGES)
        ]
        assistant_id = self.assistant_message(
            conv_id, "ASISTAN-CIKARIMI-KANIT-OLAMAZ")
        captured = []

        def complete(messages, **_kwargs):
            captured.extend(message["content"] for message in messages)
            return self.candidate_json(user_ids)

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            result = app.generate_living_map_candidates(conv_id)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["candidate_count"], 1)
        model_input = "\n".join(captured)
        self.assertIn("KULLANICI-KAYNAGI-0", model_input)
        self.assertNotIn("ASISTAN-CIKARIMI-KANIT-OLAMAZ", model_input)
        claim = self.row("SELECT * FROM psych_claims")
        self.assertEqual(claim["status"], "candidate")
        target = self.conversation()
        self.assertNotIn("Eleştiride geri çekilme", self.prompt(target))
        source_rows = self.rows(
            "SELECT o.source_message,m.role FROM psych_claim_evidence e "
            "JOIN psych_observations o ON o.id=e.observation "
            "JOIN messages m ON m.id=o.source_message "
            "WHERE e.claim=?",
            (claim["id"],),
        )
        self.assertEqual(
            {row["source_message"] for row in source_rows}, set(user_ids))
        self.assertEqual({row["role"] for row in source_rows}, {"user"})
        self.assertNotIn(
            assistant_id, {row["source_message"] for row in source_rows})

    def test_assistant_message_id_is_rejected_as_candidate_evidence(self):
        conv_id = self.conversation()
        user_ids = [
            self.user_message(conv_id, "kullanıcı {}".format(index))
            for index in range(app.LIVING_MAP_MIN_USER_MESSAGES)
        ]
        assistant_id = self.assistant_message(conv_id, "model varsayımı")

        with mock.patch.object(
                app, "ds_complete",
                return_value=self.candidate_json([assistant_id])), \
                mock.patch("builtins.print"):
            result = app.generate_living_map_candidates(conv_id)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)
        self.assertTrue(user_ids)

    def test_safety_hold_skips_generation_without_calling_model(self):
        conv_id = self.conversation()
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (conv_id,),
            )
        for index in range(app.LIVING_MAP_MIN_USER_MESSAGES):
            self.user_message(conv_id, "güvenlik kaynağı {}".format(index))

        with mock.patch.object(app, "ds_complete") as complete:
            result = app.generate_living_map_candidates(conv_id)

        complete.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["error_code"], "safety_hold")
        run = self.row(
            "SELECT * FROM insight_generation_runs WHERE conv=?",
            (conv_id,),
        )
        self.assertEqual(run["status"], "skipped")
        self.assertEqual(run["error_code"], "safety_hold")

    def test_map_claims_never_enter_lesson_or_philosopher_prompts(self):
        source = self.conversation()
        claim_id, _ = self.add_claim(
            source, title="YALNIZ-TERAPI-HARITASI")
        therapy = self.conversation(mode="terapi", therapist="freud")
        lesson = self.conversation(mode="ders", therapist="freud")
        philosopher = self.conversation(mode="ders", therapist="confucius")

        self.assertIn("YALNIZ-TERAPI-HARITASI", self.prompt(therapy))
        self.assertNotIn("YALNIZ-TERAPI-HARITASI", self.prompt(lesson))
        self.assertNotIn(
            "YALNIZ-TERAPI-HARITASI", self.prompt(philosopher))
        self.assertTrue(claim_id)

    def test_prompt_projection_is_capped_and_filters_noneligible_claims(self):
        source = self.conversation()
        eligible = []
        for index in range(3):
            claim_id, _ = self.add_claim(
                source,
                title="UYGUN-{}".format(index),
                content="uygun kullanıcı kaynağı {}".format(index),
            )
            eligible.append(claim_id)
        self.add_claim(source, title="HASSAS", sensitive=1)
        self.add_claim(source, title="OZEL", scope="private")
        self.add_claim(source, title="HARIC", scope="excluded")
        self.add_claim(source, title="RED", status="rejected")
        target = self.conversation()
        rows = app.context_living_map_claims(
            self.conversation_row(target), limit=99)

        self.assertEqual(len(rows), app.LIVING_MAP_PROMPT_LIMIT)
        self.assertTrue({row["id"] for row in rows}.issubset(set(eligible)))
        blocked = {"HASSAS", "OZEL", "HARIC", "RED"}
        self.assertTrue(blocked.isdisjoint({row["title"] for row in rows}))

    def test_schema_and_defense_need_support_from_two_conversations(self):
        first = self.conversation(title="İlk kaynak")
        target = self.conversation(title="Yeni seans")
        schema_id, _ = self.add_claim(
            first,
            title="IKI-SEANS-GEREKEN-SEMA",
            claim_type="schema_hypothesis",
            statement="Bu yalnızca bir çalışma hipotezi olabilir",
        )
        defense_id, _ = self.add_claim(
            first,
            title="IKI-SEANS-GEREKEN-SAVUNMA",
            claim_type="defense_hypothesis",
            statement="Bu da ihtiyatlı bir çalışma hipotezi olabilir",
        )

        self.assertNotIn("IKI-SEANS-GEREKEN-SEMA", self.prompt(target))
        self.assertNotIn("IKI-SEANS-GEREKEN-SAVUNMA", self.prompt(target))

        second = self.conversation(title="İkinci kaynak")
        self.add_support(
            schema_id, second,
            "Başka bir görüşmede benzer yaşantıyı yine bildirdim.")
        self.add_support(
            defense_id, second,
            "Başka bir görüşmede koruyucu tepkiyi yine bildirdim.")

        # Yeni kaynaklar kullanıcı kararı olmadan iki-seans eşiğini açmaz.
        self.assertNotIn("IKI-SEANS-GEREKEN-SEMA", self.prompt(target))
        self.assertNotIn("IKI-SEANS-GEREKEN-SAVUNMA", self.prompt(target))

        app.review_living_map_claim({
            "claim_id": schema_id, "action": "confirm"})
        app.review_living_map_claim({
            "claim_id": defense_id, "action": "confirm"})

        self.assertIn("IKI-SEANS-GEREKEN-SEMA", self.prompt(target))
        self.assertIn("IKI-SEANS-GEREKEN-SAVUNMA", self.prompt(target))

    def test_generated_second_session_evidence_waits_for_user_review(self):
        first = self.conversation(title="İlk gözlem")
        target = self.conversation(title="Yeni görüşme")
        claim_id, _ = self.add_claim(
            first,
            title="SESSIZCE-ACILMAYAN-SEMA",
            claim_type="schema_hypothesis",
            statement="İki görüşmede sınanması gereken bir çalışma notu",
        )
        before = self.row(
            "SELECT reviewed_evidence_id FROM psych_claims WHERE id=?",
            (claim_id,),
        )["reviewed_evidence_id"]
        second = self.conversation(title="İkinci gözlem")
        user_ids = [
            self.user_message(second, "ikinci görüşme {}".format(index))
            for index in range(app.LIVING_MAP_MIN_USER_MESSAGES)
        ]
        generated = self.candidate_json(
            user_ids,
            claim_type="schema_hypothesis",
            title="SESSIZCE-ACILMAYAN-SEMA",
            statement="İki görüşmede sınanması gereken bir çalışma notu",
            existing_claim_id=claim_id,
        )

        with mock.patch.object(app, "ds_complete", return_value=generated):
            result = app.generate_living_map_candidates(second)

        self.assertEqual(result["status"], "succeeded")
        self.assertNotIn("SESSIZCE-ACILMAYAN-SEMA", self.prompt(target))
        unchanged = self.row(
            "SELECT reviewed_evidence_id FROM psych_claims WHERE id=?",
            (claim_id,),
        )["reviewed_evidence_id"]
        self.assertEqual(unchanged, before)
        detail = app.living_map_claim_detail(claim_id)
        self.assertEqual(detail["claim"]["source_count"], 1)
        self.assertEqual(detail["claim"]["pending_source_count"], 1)
        self.assertEqual(
            detail["claim"]["pending_evidence_count"], len(user_ids))
        pending = [
            item for item in app.living_map_payload("freud")[
                "pending_evidence_reviews"]
            if item["id"] == claim_id
        ]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["review_kind"], "new_evidence")
        self.assertEqual(pending[0]["reject_action"], "reject_evidence")
        self.assertTrue(any(
            item["pending"] and item["message_id"] in user_ids
            for item in detail["evidence"]))

        status, reviewed, _ = self.request(
            "POST", "/api/living-map/review",
            {"claim_id": claim_id, "action": "confirm"},
        )

        self.assertEqual(status, 200, reviewed)
        self.assertEqual(reviewed["review_outcome"], "evidence_accepted")
        self.assertEqual(reviewed["claim"]["source_count"], 2)
        self.assertEqual(reviewed["claim"]["pending_evidence_count"], 0)
        self.assertIn("SESSIZCE-ACILMAYAN-SEMA", self.prompt(target))
        after = self.row(
            "SELECT reviewed_evidence_id FROM psych_claims WHERE id=?",
            (claim_id,),
        )["reviewed_evidence_id"]
        newest = self.row(
            "SELECT MAX(id) AS id FROM psych_claim_evidence WHERE claim=?",
            (claim_id,),
        )["id"]
        self.assertEqual(after, newest)

    def test_rejecting_pending_evidence_keeps_active_claim_and_old_counts(self):
        first = self.conversation(title="Onaylanmış kaynak")
        claim_id, _ = self.add_claim(
            first, title="ONAYLI-IDDIAYI-KORU")
        second = self.conversation(title="Yeni karma kaynak")
        user_ids = [
            self.user_message(second, "karma kaynak {}".format(index))
            for index in range(app.LIVING_MAP_MIN_USER_MESSAGES)
        ]
        generated = self.candidate_json(
            [user_ids[0]],
            title="ONAYLI-IDDIAYI-KORU",
            existing_claim_id=claim_id,
            counterexample_ids=[user_ids[1]],
        )
        with mock.patch.object(app, "ds_complete", return_value=generated):
            app.generate_living_map_candidates(second)

        before = app.living_map_claim_detail(claim_id)["claim"]
        self.assertEqual(before["evidence_count"], 1)
        self.assertEqual(before["counterexample_count"], 0)
        self.assertEqual(before["pending_support_count"], 1)
        self.assertEqual(before["pending_counterexample_count"], 1)

        # The legacy UI sends `reject`; on an active claim with pending
        # evidence the backend must interpret it as an evidence-only decision.
        status, rejected, _ = self.request(
            "POST", "/api/living-map/review",
            {"claim_id": claim_id, "action": "reject"},
        )

        self.assertEqual(status, 200, rejected)
        self.assertEqual(rejected["review_outcome"], "evidence_rejected")
        self.assertEqual(rejected["claim"]["status"], "confirmed")
        self.assertEqual(rejected["claim"]["evidence_count"], 1)
        self.assertEqual(rejected["claim"]["counterexample_count"], 0)
        self.assertEqual(rejected["claim"]["pending_evidence_count"], 0)
        states = self.rows(
            "SELECT review_status,COUNT(*) AS n "
            "FROM psych_claim_evidence WHERE claim=? "
            "GROUP BY review_status", (claim_id,))
        self.assertEqual(
            {row["review_status"]: row["n"] for row in states},
            {"accepted": 1, "rejected": 2},
        )
        self.assertEqual(
            self.row(
                "SELECT action FROM psych_claim_history WHERE claim=? "
                "ORDER BY id DESC LIMIT 1", (claim_id,))["action"],
            "reject_evidence",
        )
        self.assertIn(
            "ONAYLI-IDDIAYI-KORU",
            self.prompt(self.conversation(title="Sonraki görüşme")),
        )

    def test_confirming_pending_counterexample_counts_it_only_after_review(self):
        first = self.conversation(title="İlk kaynak")
        claim_id, _ = self.add_claim(first, title="KARSI-ORNEK-SINIRI")
        second = self.conversation(title="İstisna kaynağı")
        user_ids = [
            self.user_message(second, "istisna {}".format(index))
            for index in range(app.LIVING_MAP_MIN_USER_MESSAGES)
        ]
        generated = self.candidate_json(
            [user_ids[0]], title="KARSI-ORNEK-SINIRI",
            existing_claim_id=claim_id,
            counterexample_ids=[user_ids[1]],
        )
        with mock.patch.object(app, "ds_complete", return_value=generated):
            app.generate_living_map_candidates(second)

        self.assertEqual(
            app.living_map_claim_detail(claim_id)["claim"][
                "counterexample_count"], 0)
        target = self.conversation(title="Prompt sayımı")
        before_prompt = app.context_living_map_claims(
            self.conversation_row(target), limit=2)
        self.assertEqual(before_prompt[0]["support_count"], 1)
        self.assertEqual(before_prompt[0]["counterexample_count"], 0)
        reviewed = app.review_living_map_claim({
            "claim_id": claim_id, "action": "partial",
            "note": "Yeni kaynak kısmen uyuyor; karşı örnek korunmalı.",
        })
        self.assertEqual(reviewed["review_outcome"], "evidence_accepted")
        self.assertEqual(reviewed["claim"]["counterexample_count"], 1)
        self.assertEqual(reviewed["claim"]["source_count"], 2)
        self.assertTrue(all(
            item["review_status"] == "accepted"
            for item in reviewed["evidence"]))
        after_prompt = app.context_living_map_claims(
            self.conversation_row(target), limit=2)
        self.assertEqual(after_prompt[0]["support_count"], 2)
        self.assertEqual(after_prompt[0]["counterexample_count"], 1)

    def test_reviewing_new_evidence_never_unhides_a_private_active_claim(self):
        first = self.conversation(title="Özel kaynak")
        claim_id, _ = self.add_claim(
            first, title="OZEL-KALAN-KAYIT", scope="excluded")
        self.add_support(
            claim_id, self.conversation(title="Yeni özel kaynak"),
            "Bu yeni kaynak da yalnız özel kayıtta kalmalı.")

        reviewed = app.review_living_map_claim({
            "claim_id": claim_id, "action": "confirm"})

        self.assertEqual(reviewed["review_outcome"], "evidence_accepted")
        self.assertEqual(reviewed["claim"]["scope"], "excluded")
        self.assertTrue(reviewed["claim"]["excluded_from_model"])
        self.assertEqual(reviewed["claim"]["pending_evidence_count"], 0)
        self.assertNotIn(
            "OZEL-KALAN-KAYIT",
            self.prompt(self.conversation(title="Başka görüşme")),
        )

    def test_legacy_active_evidence_is_backfilled_once_but_new_evidence_waits(self):
        active_conv = self.conversation(title="Eski etkin kayıt")
        candidate_conv = self.conversation(title="Eski aday kayıt")
        active_id, _ = self.add_claim(
            active_conv, title="MIGRASYON-AKTIF")
        candidate_id, _ = self.add_claim(
            candidate_conv, title="MIGRASYON-ADAY", status="candidate")

        with app.db() as conn:
            conn.execute("DROP INDEX psych_evidence_review_queue")
            conn.execute(
                "ALTER TABLE psych_claim_evidence DROP COLUMN review_status")
            conn.execute(
                "ALTER TABLE psych_claims DROP COLUMN reviewed_evidence_id")

        app.init_db()

        active = self.row(
            "SELECT reviewed_evidence_id FROM psych_claims WHERE id=?",
            (active_id,))
        active_evidence = self.row(
            "SELECT id,review_status FROM psych_claim_evidence "
            "WHERE claim=?", (active_id,))
        candidate = self.row(
            "SELECT reviewed_evidence_id FROM psych_claims WHERE id=?",
            (candidate_id,))
        candidate_evidence = self.row(
            "SELECT review_status FROM psych_claim_evidence WHERE claim=?",
            (candidate_id,))
        self.assertEqual(active["reviewed_evidence_id"], active_evidence["id"])
        self.assertEqual(active_evidence["review_status"], "accepted")
        self.assertEqual(candidate["reviewed_evidence_id"], 0)
        self.assertEqual(candidate_evidence["review_status"], "pending")

        self.add_support(
            active_id, self.conversation(title="Yükseltme sonrası kaynak"),
            "Yükseltme sonrasında eklenen yeni kullanıcı kaynağı.")
        previous_watermark = active["reviewed_evidence_id"]
        app.init_db()
        after = self.row(
            "SELECT reviewed_evidence_id FROM psych_claims WHERE id=?",
            (active_id,))
        latest = self.row(
            "SELECT review_status FROM psych_claim_evidence WHERE claim=? "
            "ORDER BY id DESC LIMIT 1", (active_id,))
        self.assertEqual(after["reviewed_evidence_id"], previous_watermark)
        self.assertEqual(latest["review_status"], "pending")

    def test_deleting_the_only_source_erases_the_orphaned_claim(self):
        source = self.conversation()
        claim_id, message_id = self.add_claim(
            source, title="SILINEN-KAYNAGA-BAGLI")

        with app.db() as conn:
            conn.execute("DELETE FROM messages WHERE id=?", (message_id,))

        self.assertIsNone(
            self.row("SELECT id FROM psych_claims WHERE id=?", (claim_id,)))
        self.assertIsNone(
            self.row(
                "SELECT id FROM psych_observations WHERE source_message=?",
                (message_id,)))

    def test_overview_detail_and_review_api_preserve_user_provenance(self):
        source = self.conversation(title="Kaynak görüşme")
        claim_id, message_id = self.add_claim(
            source,
            title="API-INCELEME-TASLAGI",
            status="candidate",
            content="Eleştiri duyduğumda sessizleştiğimi ben söyledim.",
        )
        public_id = self.row(
            "SELECT public_id FROM psych_claims WHERE id=?",
            (claim_id,),
        )["public_id"]

        status, overview, _ = self.request(
            "GET", "/api/living-map?therapist=freud")
        self.assertEqual(status, 200)
        pending = [
            item for item in overview["pending"]
            if item.get("claim_type") != "formulation"
        ]
        self.assertEqual([item["id"] for item in pending], [claim_id])
        self.assertEqual(pending[0]["source_count"], 1)
        self.assertEqual(pending[0]["pending_evidence_count"], 0)
        self.assertFalse(pending[0]["has_pending_evidence"])
        self.assertEqual(overview["pending_evidence_reviews"], [])
        self.assertEqual(overview["counts"]["pending_insights"], 1)

        status, detail, _ = self.request(
            "GET", "/api/living-map/detail?claim_id=" + public_id)
        self.assertEqual(status, 200)
        self.assertEqual(detail["claim"]["id"], claim_id)
        self.assertEqual(len(detail["evidence"]), 1)
        evidence = detail["evidence"][0]
        self.assertEqual(evidence["message_id"], message_id)
        self.assertEqual(evidence["authored_by"], "user")
        self.assertIn("ben söyledim", evidence["snippet"])

        status, reviewed, _ = self.request(
            "POST", "/api/living-map/review",
            {"claim_id": public_id, "action": "confirm"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(reviewed["ok"])
        self.assertEqual(reviewed["claim"]["status"], "confirmed")
        reviewed_source = self.row(
            "SELECT p.reviewed_evidence_id,e.id,e.review_status "
            "FROM psych_claims p JOIN psych_claim_evidence e "
            "ON e.claim=p.id WHERE p.id=?", (claim_id,))
        self.assertEqual(
            reviewed_source["reviewed_evidence_id"], reviewed_source["id"])
        self.assertEqual(reviewed_source["review_status"], "accepted")
        self.assertEqual(
            self.row(
                "SELECT source FROM psych_claim_history "
                "WHERE claim=? ORDER BY id DESC LIMIT 1",
                (claim_id,),
            )["source"],
            "user",
        )

        status, after, _ = self.request(
            "GET", "/api/living-map?therapist=freud")
        self.assertEqual(status, 200)
        self.assertEqual(after["counts"]["pending_insights"], 0)
        self.assertEqual(
            [item["id"] for item in after["sections"]["cycles"]],
            [claim_id],
        )

    def test_overview_counts_pending_formulations_and_review_uses_prefixed_id(self):
        conv_id = self.conversation()
        source = self.conversation(title="Formülasyon notu")
        with app.db() as conn:
            note_id = conn.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,approved,scope,"
                "sensitive,updated) VALUES("
                "?,'terapi','freud','API-FORMULASYON-KAYNAGI',?,"
                "1,'therapist',0,?)",
                (source, self.stamp, self.stamp),
            ).lastrowid
            formulation_id = conn.execute(
                "INSERT INTO formulations("
                "mode,therapist,content,note_count,through_note_id,created,"
                "status,scope,sensitive,updated) VALUES("
                "'terapi','freud','API-FORMULASYON-TASLAGI',1,?,?,"
                "'pending','therapist',0,?)",
                (note_id, self.stamp, self.stamp),
            ).lastrowid
            conn.execute(
                "INSERT INTO formulation_evidence("
                "formulation,note,created) VALUES(?,?,?)",
                (formulation_id, note_id, self.stamp),
            )

        status, overview, _ = self.request(
            "GET", "/api/living-map?therapist=freud")
        self.assertEqual(status, 200)
        self.assertEqual(overview["counts"]["pending"], 1)
        self.assertEqual(overview["counts"]["pending_formulations"], 1)
        card = overview["pending"][0]
        self.assertEqual(card["artifact_type"], "formulation")
        self.assertEqual(card["public_id"], "formulation:" + str(
            formulation_id))
        self.assertNotIn("API-FORMULASYON-TASLAGI", self.prompt(conv_id))

        status, body, _ = self.request(
            "POST", "/api/living-map/review",
            {
                "claim_id": card["public_id"],
                "artifact_type": "formulation",
                "action": "confirm",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["formulation"]["status"], "approved")
        self.assertIn("API-FORMULASYON-TASLAGI", self.prompt(conv_id))
        status, after, _ = self.request(
            "GET", "/api/living-map?therapist=freud")
        self.assertEqual(status, 200)
        self.assertEqual(after["counts"]["pending_formulations"], 0)

    def test_historical_scan_scope_order_and_busy_exclusion(self):
        active = self.conversation(
            title="Açık", ended=0, updated="2026-07-23 12:00")
        ended = self.conversation(
            title="Bitmiş", ended=1, updated="2026-07-22 12:00")
        archived = self.conversation(
            title="Arşiv", ended=1, updated="2026-07-21 12:00")
        lesson = self.conversation(mode="ders", title="Ders")
        philosopher = self.conversation(
            mode="terapi", therapist="confucius", title="Düşünür")
        council = self.conversation(
            mode="terapi", submode="konsey", title="Konsey")
        safety = self.conversation(title="Güvenlik")
        short = self.conversation(title="Kısa")
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET archived_at=? WHERE id=?",
                ("2026-07-24 12:00", archived))
            conn.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (safety,))
        for conv_id in (
                active, ended, archived, lesson, philosopher, council,
                safety):
            for index in range(app.LIVING_MAP_MIN_USER_MESSAGES):
                self.completed_turn(
                    conv_id, "{} kaynak {}".format(conv_id, index))
        for index in range(app.LIVING_MAP_MIN_USER_MESSAGES - 1):
            self.completed_turn(short, "kısa {}".format(index))

        with app.db() as conn:
            self.assertEqual(
                app.living_map_backfill_conversation_ids(conn),
                [active, short, ended, archived])
            status = app.living_map_analysis_status(conn)
        self.assertEqual(status["eligible_count"], 4)
        self.assertEqual(status["active_count"], 2)
        self.assertEqual(status["ended_count"], 2)
        self.assertEqual(status["archived_count"], 1)
        self.assertEqual(
            status["safety_skipped_turn_count"],
            app.LIVING_MAP_MIN_USER_MESSAGES)

        app.create_job("session_postprocess", ended)
        with app.db() as conn:
            self.assertEqual(
                app.living_map_backfill_conversation_ids(conn),
                [active, short, archived])
            self.assertEqual(app.living_map_analysis_status(conn)["busy_count"], 1)

    def test_historical_scan_watermark_reopens_only_for_new_user_source(self):
        conv_id = self.conversation()
        user_ids = [
            self.completed_turn(conv_id, "kaynak {}".format(index))
            for index in range(app.LIVING_MAP_MIN_USER_MESSAGES)
        ]
        with app.db() as conn:
            conn.execute(
                "INSERT INTO insight_generation_runs("
                "conv,status,candidate_count,through_message_id,error_code,"
                "created,finished,updated) VALUES("
                "?,'succeeded',0,?,'',?,?,?)",
                (conv_id, max(user_ids), self.stamp, self.stamp, self.stamp))
            status = app.living_map_analysis_status(conn)
            self.assertEqual(status["analyzed_turns"], 0)
            self.assertEqual(
                status["remaining_turns"],
                app.LIVING_MAP_MIN_USER_MESSAGES)

        self.assistant_message(conv_id, "yalnız asistan yanıtı")
        with app.db() as conn:
            self.assertEqual(
                app.living_map_analysis_status(conn)["remaining_turns"],
                app.LIVING_MAP_MIN_USER_MESSAGES)

        self.user_message(conv_id, "yeni doğrudan kullanıcı kaynağı")
        with app.db() as conn:
            self.assertEqual(
                app.living_map_analysis_status(conn)["remaining_turns"],
                app.LIVING_MAP_MIN_USER_MESSAGES)
        self.completed_turn(conv_id, "yeni tamamlanmış kullanıcı kaynağı")
        with app.db() as conn:
            self.assertEqual(
                app.living_map_analysis_status(conn)["remaining_turns"],
                app.LIVING_MAP_MIN_USER_MESSAGES + 1)

    def test_historical_scan_requires_consent_and_deduplicates_start(self):
        conv_id = self.conversation()
        for index in range(app.LIVING_MAP_MIN_USER_MESSAGES):
            self.completed_turn(
                conv_id, "onay kaynağı {}".format(index))
        provider_id, model_id = app._configured_provider_model_snapshot()

        status, body, _ = self.request(
            "POST", "/api/living-map/backfill",
            {"provider_id": provider_id, "model_id": model_id})
        self.assertEqual(status, 400, body)
        self.assertTrue(app.JOB_QUEUE.empty())

        payload = {
            "consent": True,
            "provider_id": provider_id,
            "model_id": model_id,
        }
        status, first, _ = self.request(
            "POST", "/api/living-map/backfill", payload)
        self.assertEqual(status, 200, first)
        self.assertTrue(first["queued"])
        self.assertEqual(app.JOB_QUEUE.qsize(), 1)

        status, second, _ = self.request(
            "POST", "/api/living-map/backfill", payload)
        self.assertEqual(status, 200, second)
        self.assertFalse(second["queued"])
        self.assertEqual(second["job_id"], first["job_id"])
        self.assertEqual(app.JOB_QUEUE.qsize(), 1)

    def test_atomic_job_claim_rejects_duplicate_worker(self):
        conv_id = self.conversation()
        job_id = app.create_job(
            "insight_generation", conv_id, "lmstudio", "local-model")

        first = app.claim_queued_job(job_id)
        second = app.claim_queued_job(job_id)

        self.assertIsNotNone(first)
        self.assertEqual(first["status"], "running")
        self.assertIsNone(second)

    def test_failed_conversation_does_not_hide_later_historical_sessions(self):
        bad = self.conversation(
            title="Bozuk", updated="2026-07-23 12:00")
        good = self.conversation(
            title="Sağlam", updated="2026-07-22 12:00")
        for conv_id in (bad, good):
            for index in range(app.LIVING_MAP_MIN_USER_MESSAGES):
                self.completed_turn(
                    conv_id, "{} kaynak {}".format(conv_id, index))
        job_id, _ = app.create_living_map_backfill_job(
            "lmstudio", "local-model")
        calls = []

        def generate(conv_id, *_args, **_kwargs):
            calls.append(conv_id)
            user_message = _kwargs["single_turn_user_message_id"]
            with app.db() as conn:
                assistant_message = conn.execute(
                    "SELECT assistant_message FROM chat_requests WHERE "
                    "conv=? AND user_message=? AND status='completed'",
                    (conv_id, user_message)).fetchone()["assistant_message"]
                stamp = app.now()
                if conv_id == bad:
                    conn.execute(
                        "INSERT INTO insight_generation_runs("
                        "conv,status,candidate_count,through_message_id,"
                        "error_code,created,finished,updated) VALUES("
                        "?,'failed',0,0,'invalid_insight_json',?,?,?) "
                        "ON CONFLICT(conv) DO UPDATE SET status='failed',"
                        "error_code='invalid_insight_json',updated=?",
                        (conv_id, stamp, stamp, stamp, stamp))
                else:
                    conn.execute(
                        "INSERT INTO living_map_turn_analyses("
                        "conv,user_message,assistant_message,job,source,"
                        "schema_mode,status,created,finished,updated) VALUES("
                        "?,?,?,?,'historical_global',0,'succeeded',?,?,?) "
                        "ON CONFLICT(conv,user_message) DO UPDATE SET "
                        "status='succeeded',finished=excluded.finished,"
                        "updated=excluded.updated",
                        (conv_id, user_message, assistant_message, job_id,
                         stamp, stamp, stamp))
            if conv_id == bad:
                raise ValueError("bozuk model çıktısı")
            return {"status": "succeeded", "candidate_count": 0}

        with mock.patch.object(
                app, "generate_living_map_candidates",
                side_effect=generate):
            app.run_living_map_backfill_job(job_id)
            self.assertEqual(self.queued_job_id(), job_id)
            app.JOB_QUEUE.task_done()
            app.run_living_map_backfill_job(job_id)

        self.assertEqual(calls, [bad, good])
        self.assertEqual(
            self.row(
                "SELECT status FROM living_map_turn_analyses WHERE conv=?",
                (good,))["status"],
            "succeeded")
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,))["status"],
            "queued")

    def test_session_postprocess_does_not_run_living_map_generation(self):
        conv_id = self.conversation(ended=1)
        for index in range(app.LIVING_MAP_MIN_USER_MESSAGES):
            self.user_message(conv_id, "kullanıcı mesajı {}".format(index))
        job_id = app.create_job("session_postprocess", conv_id)

        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("oturum sonu harita çağırmamalı")), \
                mock.patch("builtins.print"), \
                mock.patch.object(
                    app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)

        run = self.row(
            "SELECT * FROM insight_generation_runs WHERE conv=?",
            (conv_id,),
        )
        self.assertIsNone(run)
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,))
            ["status"],
            "succeeded",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
