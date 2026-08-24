"""Metadata-only, durable ADHD TUS planner contract."""

import hashlib
import json
from pathlib import Path

from support import HTTPTestCase, app


def catalog_document(*, suffix="", question_areas=45):
    lesson_key = "lesson:farmakoloji:test00000001"
    other_lesson_key = "lesson:anatomi:test00000002"
    questions = []
    for index in range(question_areas):
        questions.append({
            "exam_scope": "tus" if index % 2 else "other",
            "key": "question-area:test:{:04d}".format(index),
            "lesson": {"key": lesson_key, "name": "Farmakoloji"},
            "module": "soru",
            "name": "Farmakoloji · Konu {:04d}{} · ÖSYM".format(
                index, suffix),
            "question_count": index + 1,
            "source": {"key": "question-source:osym", "name": "ÖSYM"},
            "topic": {
                "key": "topic:test:{:04d}".format(index),
                "name": "Konu {:04d}{}".format(index, suffix),
            },
            "tus_default_eligible": True,
        })
    reading = [{
        "key": "reading-area:test:0001",
        "lesson": {"key": lesson_key, "name": "Farmakoloji"},
        "module": "okuma",
        "name": "Farmakoloji · Check-List · Reseptörler{}".format(suffix),
        "sentence_count": 37,
        "source": {"key": "reading-source:check", "name": "Check-List"},
        "topic": {"key": "topic:reseptorler", "name": "Reseptörler{}".format(
            suffix)},
        "tus_default_eligible": True,
    }, {
        "key": "reading-area:secret:0002",
        "lesson": {"key": other_lesson_key, "name": "KATALOG-GİZLİ-DERS"},
        "module": "tokuma",
        "name": "KATALOG-GİZLİ-DERS · Gizli Kaynak · Gizli Konu",
        "sentence_count": 11,
        "source": {"key": "reading-source:secret", "name": "Gizli Kaynak"},
        "topic": {"key": "topic:secret", "name": "Gizli Konu"},
        "tus_default_eligible": True,
    }]
    question_count = sum(item["question_count"] for item in questions)
    lessons = [{
        "ineligible_by_default_question_count": 0,
        "key": lesson_key,
        "name": "Farmakoloji",
        "question_count": question_count,
        "sentence_count": 37,
        "tus_default_eligible": True,
        "tus_default_question_count": question_count,
    }, {
        "ineligible_by_default_question_count": 0,
        "key": other_lesson_key,
        "name": "KATALOG-GİZLİ-DERS",
        "question_count": 0,
        "sentence_count": 11,
        "tus_default_eligible": True,
        "tus_default_question_count": 0,
    }]
    totals = {
        "cataloged_question_count": question_count,
        "ineligible_by_default_question_count": 0,
        "lesson_count": 2,
        "question_area_count": len(questions),
        "question_count": question_count,
        "reading_area_count": len(reading),
        "sentence_count": 48,
        "tus_default_question_count": question_count,
        "unclassified_question_count": 0,
    }
    core = {
        "protocol": app.ADHD_TUS_CATALOG_PROTOCOL,
        "schema_version": 1,
        "schema_fingerprint": app.ADHD_TUS_CATALOG_SCHEMA_FINGERPRINT,
        "totals": totals,
        "lessons": lessons,
        "question_areas": questions,
        "reading_areas": reading,
    }
    fingerprint = hashlib.sha256((json.dumps(
        core, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
    return {
        "content_fingerprint": "sha256:" + fingerprint,
        "lessons": lessons,
        "protocol": app.ADHD_TUS_CATALOG_PROTOCOL,
        "question_areas": questions,
        "reading_areas": reading,
        "schema_fingerprint": core["schema_fingerprint"],
        "schema_version": 1,
        "totals": totals,
    }


def rehash_catalog(document):
    core = {key: document[key] for key in (
        "protocol", "schema_version", "schema_fingerprint", "totals",
        "lessons", "question_areas", "reading_areas")}
    document["content_fingerprint"] = "sha256:" + hashlib.sha256((json.dumps(
        core, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
    return document


class ADHDTUSPlannerTests(HTTPTestCase):

    def setUp(self):
        super().setUp()
        self.old_catalog_path = app.TUS_CATALOG_PATH
        self.catalog_path = Path(self._tmp.name) / "catalog-v1.json"
        self.write_catalog(catalog_document())
        app.TUS_CATALOG_PATH = str(self.catalog_path)
        self.conv_id = self.conversation(therapist="adhd")
        self.revision = 0
        self.serial = 0

    def tearDown(self):
        app.TUS_CATALOG_PATH = self.old_catalog_path
        super().tearDown()

    def write_catalog(self, document):
        self.catalog_path.write_text(json.dumps(
            document, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")), encoding="utf-8")

    def mutate(self, action, *, conv_id=None, expected_revision=None,
               request_id=None, **extra):
        self.serial += 1
        payload = {
            "protocol": app.ADHD_TUS_PROTOCOL,
            "conv_id": conv_id or self.conv_id,
            "action": action,
            "expected_revision": (
                self.revision if expected_revision is None
                else expected_revision),
            "request_id": request_id or "tus-test-{:08d}".format(self.serial),
        }
        payload.update(extra)
        status, body, headers = self.request(
            "POST", "/api/adhd/tus", payload)
        if status == 200 and (conv_id is None or conv_id == self.conv_id):
            self.revision = body["revision"]
        return status, body, headers

    def enable(self):
        status, body, _ = self.mutate("set_mode", enabled=True)
        self.assertEqual(status, 200, body)
        return body

    def answer(self, question_id, option_id, **extra):
        status, body, _ = self.mutate(
            "answer", question_id=question_id, option_id=option_id, **extra)
        self.assertEqual(status, 200, body)
        return body

    def ready_plan(self, minutes=25, friction="normal"):
        self.enable()
        self.answer("activity", "mixed")
        self.answer("lesson", "lesson:farmakoloji:test00000001")
        self.answer("reading_area", "reading-area:test:0001")
        self.answer("question_area", "question-area:test:0000")
        if minutes in app.ADHD_TUS_TIME_OPTIONS:
            self.answer("available_time", str(minutes))
        else:
            self.answer(
                "available_time", "custom", custom_minutes=minutes)
        return self.answer("start_friction", friction)

    def test_catalog_is_cryptographically_bound_and_raw_or_extra_fields_close_it(self):
        catalog = app.load_adhd_tus_catalog()
        self.assertTrue(catalog["available"])
        self.assertEqual(len(catalog["question_areas"]), 45)
        self.assertNotIn("question_text", json.dumps(catalog))

        stale = catalog_document()
        stale["question_areas"][0]["question_count"] += 1
        self.write_catalog(stale)
        self.assertEqual(
            app.load_adhd_tus_catalog()["error_code"], "catalog_invalid")

        extra = catalog_document()
        extra["source_path"] = "/private/source.db"
        self.write_catalog(extra)
        self.assertEqual(
            app.load_adhd_tus_catalog()["error_code"], "catalog_invalid")

        raw = catalog_document()
        raw["question_areas"][0]["content"] = "RAW-QUESTION-CONTENT"
        self.write_catalog(rehash_catalog(raw))
        self.assertEqual(
            app.load_adhd_tus_catalog()["error_code"], "catalog_invalid")

        for relation, field, value in (
                ("lesson", "source_path", "/Users/private/question-bank.sqlite"),
                ("source", "url", "file:///private/question-bank.sqlite"),
                ("source", "questionText", "RAW BODY")):
            nested = catalog_document()
            nested["question_areas"][0][relation][field] = value
            self.write_catalog(rehash_catalog(nested))
            self.assertEqual(
                app.load_adhd_tus_catalog()["error_code"], "catalog_invalid",
                (relation, field))

        app.TUS_CATALOG_PATH = str(self.catalog_path) + ".missing"
        self.assertEqual(
            app.load_adhd_tus_catalog()["error_code"], "catalog_unavailable")

    def test_catalog_rejects_non_scalar_area_metadata_and_unknown_enums(self):
        scalar_paths = (
            ("question_areas", 0, "key"),
            ("question_areas", 0, "name"),
            ("question_areas", 0, "module"),
            ("question_areas", 0, "exam_scope"),
            ("question_areas", 0, "question_count"),
            ("reading_areas", 0, "key"),
            ("reading_areas", 0, "name"),
            ("reading_areas", 0, "module"),
            ("reading_areas", 0, "sentence_count"),
        )
        for path in scalar_paths:
            for invalid in ({"safe": "nested"}, ["nested"], True):
                document = catalog_document()
                document[path[0]][path[1]][path[2]] = invalid
                self.write_catalog(rehash_catalog(document))
                self.assertEqual(
                    app.load_adhd_tus_catalog()["error_code"],
                    "catalog_invalid", (path, invalid))

        for area in ("question_areas", "reading_areas"):
            for relation in ("lesson", "source", "topic"):
                for invalid in ({}, ["nested"], True):
                    document = catalog_document()
                    document[area][0][relation] = invalid
                    self.write_catalog(rehash_catalog(document))
                    self.assertEqual(
                        app.load_adhd_tus_catalog()["error_code"],
                        "catalog_invalid", (area, relation, invalid))
                for field in ("key", "name"):
                    for invalid in ({"safe": "nested"}, ["nested"], True):
                        document = catalog_document()
                        document[area][0][relation][field] = invalid
                        self.write_catalog(rehash_catalog(document))
                        self.assertEqual(
                            app.load_adhd_tus_catalog()["error_code"],
                            "catalog_invalid",
                            (area, relation, field, invalid))

        for area in ("question_areas", "reading_areas"):
            for invalid in ({"safe": "nested"}, ["nested"], 1, "true"):
                document = catalog_document()
                document[area][0]["tus_default_eligible"] = invalid
                self.write_catalog(rehash_catalog(document))
                self.assertEqual(
                    app.load_adhd_tus_catalog()["error_code"],
                    "catalog_invalid", (area, invalid))

        for field, invalid in (
                ("module", "questions"),
                ("exam_scope", "board_exam")):
            document = catalog_document()
            document["question_areas"][0][field] = invalid
            self.write_catalog(rehash_catalog(document))
            self.assertEqual(
                app.load_adhd_tus_catalog()["error_code"],
                "catalog_invalid", (field, invalid))

        document = catalog_document()
        document["question_areas"][0]["exam_scope"] = {
            "questionText": "RAW BODY"}
        self.write_catalog(rehash_catalog(document))
        self.assertEqual(
            app.load_adhd_tus_catalog()["error_code"], "catalog_invalid")

    def test_catalog_rejects_scalar_impostors_in_rollups_and_schema(self):
        lesson_paths = (
            "key", "name", "question_count", "sentence_count",
            "ineligible_by_default_question_count",
            "tus_default_question_count",
        )
        for field in lesson_paths:
            for invalid in ({"safe": "nested"}, ["nested"], True):
                document = catalog_document()
                document["lessons"][0][field] = invalid
                self.write_catalog(rehash_catalog(document))
                self.assertEqual(
                    app.load_adhd_tus_catalog()["error_code"],
                    "catalog_invalid", (field, invalid))

        for invalid in ({"safe": "nested"}, ["nested"], 1, "true"):
            document = catalog_document()
            document["lessons"][0]["tus_default_eligible"] = invalid
            self.write_catalog(rehash_catalog(document))
            self.assertEqual(
                app.load_adhd_tus_catalog()["error_code"],
                "catalog_invalid", invalid)

        for field in catalog_document()["totals"]:
            for invalid in ({"safe": "nested"}, ["nested"], True):
                document = catalog_document()
                document["totals"][field] = invalid
                self.write_catalog(rehash_catalog(document))
                self.assertEqual(
                    app.load_adhd_tus_catalog()["error_code"],
                    "catalog_invalid", (field, invalid))

        for invalid in ({"safe": "nested"}, ["nested"], True):
            document = catalog_document()
            document["schema_version"] = invalid
            self.write_catalog(rehash_catalog(document))
            self.assertEqual(
                app.load_adhd_tus_catalog()["error_code"],
                "catalog_invalid", invalid)

        for field in ("protocol", "schema_fingerprint"):
            for invalid in ({"safe": "nested"}, ["nested"], True):
                document = catalog_document()
                document[field] = invalid
                self.write_catalog(rehash_catalog(document))
                self.assertEqual(
                    app.load_adhd_tus_catalog()["error_code"],
                    "catalog_invalid", (field, invalid))

        for invalid in ({"safe": "nested"}, ["nested"], True):
            document = catalog_document()
            document["content_fingerprint"] = invalid
            self.write_catalog(document)
            self.assertEqual(
                app.load_adhd_tus_catalog()["error_code"],
                "catalog_invalid", invalid)

        document = catalog_document()
        document["schema_fingerprint"] = "sha256:" + "2" * 64
        self.write_catalog(rehash_catalog(document))
        self.assertEqual(
            app.load_adhd_tus_catalog()["error_code"], "catalog_invalid")

    def test_guided_flow_asks_one_question_and_builds_bounded_plan(self):
        body = self.enable()
        self.assertEqual(body["revision"], 1)
        for question_id, option_id in (
                ("activity", "mixed"),
                ("lesson", "lesson:farmakoloji:test00000001"),
                ("reading_area", "reading-area:test:0001"),
                ("question_area", "question-area:test:0000"),
                ("available_time", "25"),
                ("start_friction", "hard")):
            self.assertEqual(body["question"]["id"], question_id)
            body = self.answer(question_id, option_id)
        self.assertEqual(body["state"], "plan_ready")
        self.assertIsNone(body["question"])
        plan = body["plan"]
        self.assertEqual(plan["lesson"]["name"], "Farmakoloji")
        self.assertEqual(plan["reading_area"]["source"], "Check-List")
        self.assertEqual(plan["reading_area"]["available_count"], 37)
        self.assertEqual(sum(
            step["duration_minutes"] for step in plan["steps"]), 25)
        self.assertEqual(sum(step["visible"] for step in plan["steps"]), 1)
        self.assertTrue(all(
            step["collapsed"] for step in plan["steps"] if not step["visible"]))
        self.assertIn("borç", body["notices"]["no_debt"])

    def test_time_and_count_invariants_cover_long_custom_sessions(self):
        catalog = app.load_adhd_tus_catalog()
        base = {
            "lesson": "lesson:farmakoloji:test00000001",
            "reading_area": "reading-area:test:0001",
            "question_area": "question-area:test:0000",
            "start_friction": "normal",
        }
        for activity in ("read", "questions", "mixed"):
            for minutes in (5, 15, 25, 45, 180):
                answers = dict(base, activity=activity,
                               available_minutes=minutes)
                plan = app._tus_plan_blueprint(answers, catalog)
                planned = sum(
                    item["duration_minutes"] for item in plan["steps"])
                self.assertEqual(planned, plan["available_minutes"])
                self.assertLessEqual(planned, minutes)
                self.assertLessEqual(len(plan["steps"]), 20)
                self.assertTrue(all(
                    item["duration_minutes"] <= 20 for item in plan["steps"]))
                self.assertLessEqual(sum(
                    item["quantity"] for item in plan["steps"]
                    if item["kind"] == "reading"), 37)
                self.assertLessEqual(sum(
                    item["quantity"] for item in plan["steps"]
                    if item["kind"] == "questions"), 1)
                if minutes == 180:
                    self.assertEqual(planned, {
                        "read": 26, "questions": 5, "mixed": 29,
                    }[activity])

    def test_options_are_exact_filterable_and_bounded(self):
        self.enable()
        body = self.answer("activity", "questions")
        body = self.answer("lesson", "lesson:farmakoloji:test00000001")
        self.assertEqual(body["question"]["id"], "question_area")
        self.assertEqual(len(body["question"]["options"]), 40)
        self.assertTrue(body["question"]["has_more"])
        status, filtered, _ = self.request(
            "GET", "/api/adhd/tus?conv_id={}&q=0044".format(self.conv_id))
        self.assertEqual(status, 200, filtered)
        self.assertEqual([
            item["id"] for item in filtered["question"]["options"]],
            ["question-area:test:0044"])
        status, rejected, _ = self.mutate(
            "answer", question_id="question_area",
            option_id="question-area:invented")
        self.assertEqual(status, 409, rejected)

    def test_idempotency_stale_revision_and_cross_conversation_binding(self):
        request_id = "tus-idempotent-0001"
        status, first, _ = self.mutate(
            "set_mode", request_id=request_id, enabled=True)
        self.assertEqual(status, 200, first)
        status, duplicate, _ = self.mutate(
            "set_mode", request_id=request_id, expected_revision=0,
            enabled=True)
        self.assertEqual(status, 200, duplicate)
        self.assertTrue(duplicate["duplicate"])
        status, conflict, _ = self.mutate(
            "set_mode", request_id=request_id, expected_revision=0,
            enabled=False)
        self.assertEqual(status, 409, conflict)
        status, stale, _ = self.mutate(
            "restart", expected_revision=0)
        self.assertEqual(status, 409, stale)
        self.assertEqual(stale["error_code"], "tus_stale_revision")
        self.assertEqual(stale["current_revision"], 1)

        ready = self.ready_plan()
        other = self.conversation(therapist="adhd")
        status, enabled, _ = self.mutate(
            "set_mode", conv_id=other, expected_revision=0, enabled=True)
        self.assertEqual(status, 200, enabled)
        status, wrong, _ = self.mutate(
            "start", conv_id=other, expected_revision=enabled["revision"],
            plan_id=ready["plan"]["id"])
        self.assertEqual(status, 409, wrong)

    def test_active_plan_only_advances_visible_step_and_resumes(self):
        ready = self.ready_plan()
        plan_id = ready["plan"]["id"]
        status, active, _ = self.mutate("start", plan_id=plan_id)
        self.assertEqual(status, 200, active)
        future = next(step for step in active["plan"]["steps"]
                      if not step["visible"])
        status, mismatch, _ = self.mutate(
            "complete_step", plan_id=plan_id, step_id=future["id"])
        self.assertEqual(status, 409, mismatch)
        self.assertEqual(mismatch["error_code"], "tus_step_mismatch")

        status, paused, _ = self.mutate("pause")
        self.assertEqual(status, 200, paused)
        self.assertEqual(paused["state"], "paused")
        status, resumed, _ = self.mutate("resume")
        self.assertEqual(status, 200, resumed)
        current = resumed["plan"]["current_step"]
        status, advanced, _ = self.mutate(
            "complete_step", plan_id=plan_id, step_id=current["id"])
        self.assertEqual(status, 200, advanced)
        self.assertEqual(advanced["plan"]["progress"]["completed"], 1)

    def test_catalog_change_requires_explicit_restart(self):
        self.enable()
        self.answer("activity", "mixed")
        self.write_catalog(catalog_document(suffix=" Yeni"))
        status, body, _ = self.request(
            "GET", "/api/adhd/tus?conv_id={}".format(self.conv_id))
        self.assertEqual(status, 200, body)
        self.assertTrue(body["catalog_changed"])
        self.assertIsNone(body["question"])
        self.assertIn("restart", body["allowed_actions"])
        self.assertNotIn("answer", body["allowed_actions"])
        status, blocked, _ = self.mutate(
            "answer", question_id="lesson",
            option_id="lesson:farmakoloji:test00000001")
        self.assertEqual(status, 409, blocked)
        self.assertEqual(blocked["error_code"], "tus_catalog_changed")
        status, restarted, _ = self.mutate("restart")
        self.assertEqual(status, 200, restarted)
        self.assertEqual(restarted["question"]["id"], "activity")

    def test_safety_hold_pauses_and_blocks_resume_but_allows_cancel(self):
        ready = self.ready_plan()
        status, active, _ = self.mutate(
            "start", plan_id=ready["plan"]["id"])
        self.assertEqual(status, 200, active)
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (self.conv_id,))
            self.assertTrue(app.pause_adhd_tus_plan(
                connection, self.conv_id))
        self.revision += 1
        status, held, _ = self.request(
            "GET", "/api/adhd/tus?conv_id={}".format(self.conv_id))
        self.assertEqual(status, 200, held)
        self.assertEqual(held["state"], "paused")
        self.assertEqual(held["allowed_actions"], ["cancel", "set_mode"])
        status, blocked, _ = self.mutate("resume")
        self.assertEqual(status, 409, blocked)
        self.assertEqual(blocked["error_code"], "safety_hold")
        status, cancelled, _ = self.mutate(
            "cancel", plan_id=ready["plan"]["id"])
        self.assertEqual(status, 200, cancelled)

    def test_privacy_delete_export_transfer_and_coach_context_boundaries(self):
        ready = self.ready_plan()
        context = app.adhd_coach_context(
            self.conversation_row(self.conv_id))
        self.assertIn("Farmakoloji", context)
        self.assertIn("Reseptörler", context)
        self.assertIn('"available_count":37', context)
        self.assertNotIn("KATALOG-GİZLİ-DERS", context)
        self.assertNotIn("question-area:test:0044", context)

        status, privacy, _ = self.request("GET", "/api/privacy-summary")
        self.assertEqual(status, 200, privacy)
        self.assertEqual(privacy["counts"]["adhd_tus_plans"], 1)
        status, exported, _ = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200)
        text = json.dumps(exported, ensure_ascii=False)
        self.assertIn("adhd_tus_plans", text)

        status, transfer, _ = self.request(
            "POST", "/api/transfer/export", {"ids": [self.conv_id]})
        self.assertIn(status, (200, 400), transfer)
        transfer_keys = set()
        pending = [transfer]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                transfer_keys.update(value)
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        self.assertTrue({
            "adhd_tus_planners", "adhd_tus_plans",
            "adhd_tus_plan_steps",
        }.isdisjoint(transfer_keys))

        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            app.delete_conversation_data(connection, self.conv_id)
            for table in (
                    "adhd_tus_plan_steps", "adhd_tus_plans",
                    "adhd_tus_planners"):
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM " + table).fetchone()[0], 0)

    def test_archive_and_session_end_pause_running_plan(self):
        ready = self.ready_plan()
        status, active, _ = self.mutate(
            "start", plan_id=ready["plan"]["id"])
        self.assertEqual(status, 200, active)
        before = active["revision"]
        status, archived, _ = self.request(
            "POST", "/api/archive", {"id": self.conv_id, "archived": True})
        self.assertEqual(status, 200, archived)
        plan = self.row(
            "SELECT status FROM adhd_tus_plans WHERE conv=?",
            (self.conv_id,))
        planner = self.row(
            "SELECT revision FROM adhd_tus_planners WHERE conv=?",
            (self.conv_id,))
        self.assertEqual(plan["status"], "paused")
        self.assertEqual(planner["revision"], before + 1)

        status, restored, _ = self.request(
            "POST", "/api/archive", {"id": self.conv_id, "archived": False})
        self.assertEqual(status, 200, restored)
        status, ended, _ = self.request(
            "POST", "/api/end", {"conv_id": self.conv_id})
        self.assertEqual(status, 200, ended)
        self.assertEqual(self.row(
            "SELECT status FROM adhd_tus_plans WHERE conv=?",
            (self.conv_id,))["status"], "paused")

    def test_guest_shutdown_and_delete_all_erase_every_tus_row(self):
        self.ready_plan()
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET is_guest=1 WHERE id=?",
                (self.conv_id,))
        app.set_setting("guest_mode", "1")
        status, closed, _ = self.request(
            "POST", "/api/guest-mode", {"active": False})
        self.assertEqual(status, 200, closed)
        for table in (
                "adhd_tus_plan_steps", "adhd_tus_plans",
                "adhd_tus_planners"):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM " + table)["n"], 0)

        self.conv_id = self.conversation(therapist="adhd")
        self.revision = 0
        self.ready_plan()
        status, deleted, _ = self.request(
            "POST", "/api/delete-all", {"confirm": "TÜM VERİLERİ SİL"})
        self.assertEqual(status, 200, deleted)
        for table in (
                "adhd_tus_plan_steps", "adhd_tus_plans",
                "adhd_tus_planners"):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM " + table)["n"], 0)
