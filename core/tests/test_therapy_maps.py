import json
from collections import Counter

from support import HTTPTestCase, app


EXPECTED_METHOD_NODE_IDS = {
    "freud": (
        "free-association", "transference-pattern", "defense-conflict"),
    "jung": (
        "dream-amplification", "active-imagination", "shadow-persona"),
    "klein": (
        "here-now-object-relations", "projective-identification",
        "reparation"),
    "winnicott": (
        "holding-environment", "true-false-self", "squiggle-game"),
    "bowlby": (
        "attachment-map", "secure-base", "internal-working-model"),
    "ferenczi": (
        "validate-traumatic-impact", "wise-baby", "relational-repair"),
    "kohut": (
        "empathic-immersion", "selfobject-need", "rupture-repair"),
    "rogers": (
        "feeling-reflection", "unconditional-regard", "congruence"),
    "beck": (
        "thought-record", "socratic-questioning",
        "behavioral-experiment", "activity-scheduling"),
    "frankl": (
        "meaning-discovery", "dereflection", "paradoxical-intention"),
    "perls": (
        "empty-chair", "two-chair-conflict", "here-now-awareness"),
    "yalom": (
        "here-now-relationship", "existential-inquiry",
        "responsibility-choice"),
    "young": (
        "mode-map", "imagery-rescripting", "chair-dialogue",
        "limited-reparenting", "empathic-confrontation",
        "pattern-breaking"),
    "adler": (
        "lifestyle-map", "early-recollections", "acting-as-if"),
    "horney": (
        "movement-directions", "tyranny-of-shoulds", "real-self"),
    "erickson": (
        "resource-recall", "metaphor-work", "attention-focusing"),
    "berne": (
        "ego-states", "transactional-analysis", "game-redecision"),
    "satir": (
        "communication-stances", "family-map", "parts-party"),
    "linehan": (
        "behavior-chain", "distress-tolerance", "emotion-regulation",
        "interpersonal-effectiveness"),
    "hayes": (
        "cognitive-defusion", "acceptance-expansion", "values-compass",
        "self-as-context"),
    "lacan": (
        "signifier-chain", "desire-and-other", "scansion"),
    "truth": (
        "felt-sense", "open-awareness", "direct-looking"),
    "bion": (
        "container-contained", "alpha-function-symbolization",
        "without-memory-desire", "basic-assumption-map"),
    "kernberg": (
        "treatment-frame", "affect-dyad-map",
        "clarify-confront-interpret", "split-representations-integration"),
    "fonagy": (
        "mentalizing-stance", "stop-rewind-explore",
        "self-other-perspectives", "rupture-restore-mentalizing"),
    "ellis": (
        "abc-map", "belief-disputation",
        "unconditional-acceptance", "rational-emotive-imagery"),
    "insoo_berg": (
        "preferred-future", "exception-search",
        "scaling-question", "coping-question"),
    "white": (
        "externalizing-conversation", "unique-outcomes",
        "re-authoring", "absent-but-implicit"),
    "minuchin": (
        "family-structure-map", "boundaries-subsystems",
        "interaction-enactment", "structural-reframe"),
    "bowen": (
        "three-generation-genogram", "triangle-map",
        "i-position", "differentiation-practice"),
    "greenberg": (
        "emotion-scheme-map", "two-chair-self-criticism",
        "unfinished-business-chair", "transform-emotion-with-emotion"),
    "miller": (
        "oars-listening", "change-talk",
        "importance-confidence-ruler", "develop-discrepancy"),
    "shapiro": (
        "emdr-readiness-map", "resource-development",
        "dual-attention-orientation", "closure-grounding"),
    "sue_johnson": (
        "negative-cycle-map", "attachment-need-access",
        "softening-conversation-rehearsal", "bond-repair-step"),
}


class TherapyMapTestCase(HTTPTestCase):

    def new_therapy(self, therapist="freud", node_id=None, precheck=None):
        payload = {"mode": "terapi", "therapist": therapist}
        if node_id is not None:
            payload["map_node_id"] = node_id
        if precheck is not None:
            payload["precheck"] = precheck
        status, body, _ = self.request("POST", "/api/new", payload)
        self.assertEqual(status, 200, body)
        self.assertIn("map", body)
        return body["id"], body

    def post_map(self, conv_id, action, **extra):
        payload = {"conv_id": conv_id, "action": action}
        payload.update(extra)
        return self.request("POST", "/api/therapy-map", payload)

    def get_map(self, therapist, conv_id=None):
        path = "/api/therapy-map?therapist={}".format(therapist)
        if conv_id is not None:
            path += "&conv_id={}".format(conv_id)
        return self.request("GET", path)

    def map_run(self, conv_id):
        return self.row(
            "SELECT * FROM session_map_runs WHERE conv=?", (conv_id,))

    def map_target(self, conv_id, node_id=None):
        if node_id is None:
            return self.row(
                "SELECT * FROM session_map_targets "
                "WHERE conv=? AND is_current=1", (conv_id,))
        return self.row(
            "SELECT * FROM session_map_targets "
            "WHERE conv=? AND node_id=?", (conv_id, node_id))

    def map_events(self, conv_id):
        return self.rows(
            "SELECT * FROM session_map_events WHERE conv=? ORDER BY seq",
            (conv_id,))


class TherapyMapCatalogTests(TherapyMapTestCase):

    def test_all_schools_publish_the_expected_stable_unique_method_nodes(self):
        self.assertEqual(set(app.THERAPISTS), set(EXPECTED_METHOD_NODE_IDS))
        self.assertEqual(set(app.THERAPY_METHODS),
                         set(EXPECTED_METHOD_NODE_IDS))
        self.assertEqual(set(app.THERAPY_METHOD_NODE_IDS),
                         set(EXPECTED_METHOD_NODE_IDS))

        all_node_ids = []
        all_method_keys = []
        total_methods = 0
        for therapist, expected_ids in EXPECTED_METHOD_NODE_IDS.items():
            with self.subTest(therapist=therapist):
                self.assertEqual(
                    tuple(app.THERAPY_METHOD_NODE_IDS[therapist]),
                    expected_ids)
                methods = app.method_records(therapist)
                self.assertEqual(len(methods), len(expected_ids))
                self.assertEqual(
                    [method["node_id"] for method in methods],
                    ["{}:method:{}".format(therapist, stable_id)
                     for stable_id in expected_ids])
                self.assertTrue(all(method["requires_consent"]
                                    for method in methods))
                all_node_ids.extend(method["node_id"] for method in methods)
                all_method_keys.extend(method["key"] for method in methods)
                total_methods += len(methods)

        expected_total = sum(
            len(ids) for ids in EXPECTED_METHOD_NODE_IDS.values())
        self.assertEqual(len(EXPECTED_METHOD_NODE_IDS), 34)
        self.assertEqual(expected_total, 120)
        self.assertEqual(total_methods, expected_total)
        self.assertEqual(len(all_node_ids), expected_total)
        self.assertEqual(len(set(all_node_ids)), expected_total)
        self.assertEqual(len(all_method_keys), expected_total)
        self.assertEqual(len(set(all_method_keys)), expected_total)
        self.assertEqual(
            sum(len(ids) == 3 for ids in EXPECTED_METHOD_NODE_IDS.values()),
            18)
        self.assertEqual(
            sum(len(ids) == 4 for ids in EXPECTED_METHOD_NODE_IDS.values()),
            15)
        self.assertEqual(
            sum(len(ids) == 6 for ids in EXPECTED_METHOD_NODE_IDS.values()),
            1)

    def test_every_school_graph_has_complete_node_and_edge_integrity(self):
        all_published_nodes = set()
        for therapist, stable_ids in EXPECTED_METHOD_NODE_IDS.items():
            with self.subTest(therapist=therapist):
                nodes = app.therapy_map_nodes(therapist)
                edges = app.therapy_map_edges(therapist)
                node_by_id = {node["node_id"]: node for node in nodes}
                node_ids = set(node_by_id)
                kinds = Counter(node["kind"] for node in nodes)
                entry = "{}:entry".format(therapist)
                integration = "{}:integration".format(therapist)
                closure = "{}:closure".format(therapist)
                method_ids = {
                    "{}:method:{}".format(therapist, stable_id)
                    for stable_id in stable_ids
                }

                self.assertEqual(len(node_by_id), len(nodes))
                self.assertEqual(kinds, {
                    "entry": 1,
                    "method": len(stable_ids),
                    "integration": 1,
                    "closure": 1,
                })
                self.assertEqual(
                    {node["node_id"] for node in nodes
                     if node["kind"] == "method"},
                    method_ids)
                self.assertEqual(len(edges), 3 * len(stable_ids) + 2)
                self.assertEqual(
                    len({(edge["from"], edge["to"], edge["kind"])
                         for edge in edges}),
                    len(edges))

                for node in nodes:
                    self.assertTrue(node["name"])
                    self.assertTrue(node["description"])
                    self.assertTrue(node["start_criteria"])
                    self.assertTrue(node["end_criteria"])
                    self.assertIn(node["risk_level"],
                                  ("standard", "enhanced"))
                self.assertFalse(node_by_id[entry]["requires_consent"])
                self.assertFalse(node_by_id[integration]["requires_consent"])
                self.assertFalse(node_by_id[closure]["requires_consent"])

                expected_edges = {
                    (entry, closure, "may_close"),
                    (integration, closure, "may_close"),
                }
                for method_id in method_ids:
                    expected_edges.update({
                        (entry, method_id, "choice"),
                        (method_id, integration, "reflect"),
                        (integration, method_id, "revisit"),
                    })
                actual_edges = {
                    (edge["from"], edge["to"], edge["kind"])
                    for edge in edges
                }
                self.assertEqual(actual_edges, expected_edges)
                for edge in edges:
                    self.assertIn(edge["from"], node_ids)
                    self.assertIn(edge["to"], node_ids)
                    self.assertNotEqual(edge["from"], edge["to"])

                reachable = {entry}
                changed = True
                while changed:
                    changed = False
                    for edge in edges:
                        if (edge["from"] in reachable
                                and edge["to"] not in reachable):
                            reachable.add(edge["to"])
                            changed = True
                self.assertEqual(reachable, node_ids)
                self.assertFalse(all_published_nodes.intersection(node_ids))
                all_published_nodes.update(node_ids)

        expected_total = sum(
            len(ids) for ids in EXPECTED_METHOD_NODE_IDS.values())
        self.assertEqual(
            len(all_published_nodes),
            expected_total + len(EXPECTED_METHOD_NODE_IDS) * 3)

    def test_get_map_catalog_and_all_school_summaries(self):
        status, catalog, _ = self.get_map("truth")
        self.assertEqual(status, 200)
        self.assertEqual(catalog["therapist"], "truth")
        self.assertEqual(catalog["map_version"], app.THERAPY_MAP_VERSION)
        self.assertEqual(catalog["stats"], {
            "visited": 0, "reached": 0, "total_methods": 3})
        self.assertEqual(len(catalog["nodes"]), 6)
        self.assertIsNone(catalog["target"])
        self.assertTrue(catalog["can_end"])
        self.assertIn("iyileşme yüzdesi", catalog["disclaimer"])

        conv_id, _ = self.new_therapy()
        method_node = app.method_records("freud")[0]["node_id"]
        status, _, _ = self.post_map(
            conv_id, "select", node_id=method_node)
        self.assertEqual(status, 200)
        status, _, _ = self.post_map(
            conv_id, "checkpoint", outcome="reached", fit="helpful",
            note="Bu seans için kullanıcı değerlendirmesi")
        self.assertEqual(status, 200)

        status, current, _ = self.get_map("freud", conv_id)
        self.assertEqual(status, 200)
        self.assertEqual(current["target"]["node_id"], method_node)
        self.assertEqual(current["target"]["status"], "reached")
        self.assertEqual(current["stats"]["visited"], 1)
        self.assertEqual(current["stats"]["reached"], 1)

        status, all_maps, _ = self.request(
            "GET", "/api/therapy-map?all=1")
        self.assertEqual(status, 200)
        self.assertEqual(all_maps["map_version"], app.THERAPY_MAP_VERSION)
        self.assertEqual(
            len(all_maps["schools"]), len(EXPECTED_METHOD_NODE_IDS))
        self.assertEqual(
            {school["therapist"] for school in all_maps["schools"]},
            set(EXPECTED_METHOD_NODE_IDS))
        self.assertEqual(
            sum(school["total_methods"] for school in all_maps["schools"]),
            sum(len(ids) for ids in EXPECTED_METHOD_NODE_IDS.values()))
        freud = next(
            school for school in all_maps["schools"]
            if school["therapist"] == "freud")
        self.assertEqual(freud["visited"], 1)
        self.assertEqual(freud["reached"], 1)


class TherapyMapLifecycleTests(TherapyMapTestCase):

    def test_new_session_selected_node_and_precheck_initialize_one_route(self):
        node_id = "jung:method:active-imagination"
        precheck = {
            "focus": "Rüyadaki imgeyi güvenle anlamak",
            "mood_start": 5,
            "energy_start": 6,
            "anxiety_start": 4,
            "intensity_limit": 6,
            "preferred_pace": "Yavaş",
            "safety_ok": True,
        }
        conv_id, body = self.new_therapy(
            therapist="jung", node_id=node_id, precheck=precheck)

        self.assertEqual(body["map"]["target"]["node_id"], node_id)
        self.assertEqual(body["map"]["target"]["status"], "selected")
        self.assertEqual(body["map"]["target"]["phase"], "consent")
        self.assertIn("Aktif imgelem", body["greeting"])
        self.assertIn("açık onay", body["greeting"])

        meta = self.row(
            "SELECT * FROM session_meta WHERE conv=?", (conv_id,))
        self.assertEqual(meta["focus"], precheck["focus"])
        self.assertEqual(meta["mood_start"], 5)
        self.assertEqual(meta["intensity_limit"], 6)
        self.assertEqual(meta["precheck_done"], 1)

        entry = self.map_target(conv_id, "jung:entry")
        selected = self.map_target(conv_id, node_id)
        self.assertEqual(entry["status"], "reached")
        self.assertEqual(entry["phase"], "end")
        self.assertEqual(entry["is_current"], 0)
        self.assertIsNotNone(entry["reached_at"])
        self.assertEqual(selected["status"], "selected")
        self.assertEqual(selected["phase"], "consent")
        self.assertEqual(selected["is_current"], 1)
        self.assertEqual(selected["source"], "user")

        run = self.map_run(conv_id)
        events = self.map_events(conv_id)
        self.assertEqual(run["revision"], 3)
        self.assertEqual([event["seq"] for event in events], [1, 2, 3])
        self.assertEqual(
            [(event["action"], event["source"]) for event in events],
            [("select", "system"),
             ("checkpoint", "precheck"),
             ("select", "user")])

    def test_select_checkpoint_and_undo_are_revisioned_audit_events(self):
        conv_id, body = self.new_therapy()
        node_id = "freud:method:free-association"
        self.assertEqual(body["map"]["revision"], 1)

        status, selected, _ = self.post_map(
            conv_id, "select", node_id=node_id)
        self.assertEqual(status, 200)
        self.assertEqual(selected["map"]["revision"], 2)
        self.assertEqual(selected["map"]["target"]["node_id"], node_id)
        self.assertEqual(selected["map"]["target"]["phase"], "consent")

        status, same, _ = self.post_map(
            conv_id, "select", node_id=node_id)
        self.assertEqual(status, 200)
        self.assertEqual(same["map"]["revision"], 2)
        self.assertEqual(len(self.map_events(conv_id)), 2)

        status, reached, _ = self.post_map(
            conv_id, "checkpoint", outcome="reached", fit="helpful",
            note="Kullanıcının ulaştım değerlendirmesi")
        self.assertEqual(status, 200)
        self.assertEqual(reached["map"]["revision"], 3)
        self.assertEqual(reached["map"]["target"]["status"], "reached")
        self.assertEqual(reached["map"]["target"]["phase"], "end")
        self.assertEqual(reached["map"]["target"]["fit"], "helpful")
        reached_event_id = reached["map"]["last_reached_event_id"]
        self.assertIsNotNone(reached_event_id)

        status, undone, _ = self.post_map(conv_id, "undo")
        self.assertEqual(status, 200)
        self.assertEqual(undone["map"]["revision"], 4)
        self.assertEqual(undone["map"]["target"]["status"], "selected")
        self.assertEqual(undone["map"]["target"]["phase"], "consent")
        self.assertTrue(undone["map"]["target"]["candidate"])
        self.assertEqual(undone["map"]["target"]["fit"], "")
        self.assertEqual(undone["map"]["target"]["note"], "")
        self.assertIsNone(undone["map"]["last_reached_event_id"])
        self.assertEqual(undone["map"]["stats"]["reached"], 0)

        events = self.map_events(conv_id)
        self.assertEqual([event["seq"] for event in events], [1, 2, 3, 4])
        self.assertEqual(
            [event["action"] for event in events],
            ["select", "select", "checkpoint", "undo_checkpoint"])
        self.assertEqual(events[-1]["reverts_event"], reached_event_id)
        self.assertEqual(events[-1]["from_status"], "reached")
        self.assertEqual(events[-1]["to_status"], "selected")

    def test_technique_phases_update_target_but_completion_needs_checkpoint(self):
        conv_id, _ = self.new_therapy()
        method = app.method_records("freud")[0]

        status, proposed, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "action": "propose",
                "method_key": method["key"],
                "intensity": 4,
            })
        self.assertEqual(status, 200)
        run_id = proposed["run"]["id"]
        self.assertEqual(proposed["map"]["target"]["node_id"],
                         method["node_id"])
        self.assertEqual(proposed["map"]["target"]["status"], "selected")
        self.assertEqual(proposed["map"]["target"]["phase"], "consent")

        steps = [
            ("consent", "active", "prepare", False),
            ("advance", "active", "work", False),
            ("advance", "active", "grounding", False),
            ("advance", "active", "reflect", True),
            ("advance", "review", "end", True),
        ]
        last = None
        for action, map_status, phase, candidate in steps:
            with self.subTest(action=action, phase=phase):
                status, last, _ = self.request(
                    "POST", "/api/technique-run", {
                        "conv_id": conv_id,
                        "id": run_id,
                        "action": action,
                        **({"confirmed": True}
                           if action == "consent" else {}),
                        **({"checkpoint_confirmed": True}
                           if action == "advance" else {}),
                    })
                self.assertEqual(status, 200, last)
                self.assertEqual(last["map"]["target"]["node_id"],
                                 method["node_id"])
                self.assertEqual(last["map"]["target"]["status"], map_status)
                self.assertEqual(last["map"]["target"]["phase"], phase)
                self.assertEqual(
                    bool(last["map"]["target"]["candidate"]), candidate)

        self.assertEqual(last["run"]["status"], "completed")
        self.assertEqual(last["run"]["phase"], "end")
        target = self.map_target(conv_id, method["node_id"])
        self.assertEqual(target["status"], "review")
        self.assertEqual(target["candidate"], 1)
        self.assertIsNone(target["reached_at"])
        self.assertEqual(last["map"]["stats"]["reached"], 0)
        self.assertEqual(last["map"]["candidate_node"], method["node_id"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM session_map_events "
                "WHERE conv=? AND node_id=? AND action='checkpoint' "
                "AND to_status='reached'",
                (conv_id, method["node_id"]))["n"],
            0)

        status, checkpointed, _ = self.post_map(
            conv_id, "checkpoint", outcome="reached", fit="helpful",
            note="Teknik bittiği için değil, kullanıcı böyle değerlendirdi.")
        self.assertEqual(status, 200)
        self.assertEqual(checkpointed["map"]["target"]["status"], "reached")
        self.assertEqual(checkpointed["map"]["stats"]["reached"], 1)

    def test_crisis_pauses_active_technique_with_safety_sourced_map_event(self):
        conv_id, _ = self.new_therapy()
        method = app.method_records("freud")[0]
        status, proposed, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "action": "propose",
                "method_key": method["key"],
                "intensity": 4,
            })
        self.assertEqual(status, 200)
        run_id = proposed["run"]["id"]
        status, _, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id, "id": run_id, "action": "consent",
                "confirmed": True})
        self.assertEqual(status, 200)

        status, crisis, _ = self.request(
            "POST", "/api/chat", {
                "conv_id": conv_id,
                "message": "Kendime zarar vermek istiyorum.",
            })
        self.assertEqual(status, 200)
        self.assertTrue(crisis["crisis"])
        self.assertTrue(crisis["safety_hold"])

        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual(run["status"], "paused")
        self.assertEqual(run["phase"], "grounding")
        self.assertEqual(self.conversation_row(conv_id)["safety_hold"], 1)

        target = self.map_target(conv_id)
        self.assertEqual(target["node_id"], method["node_id"])
        self.assertEqual(target["status"], "paused")
        self.assertEqual(target["phase"], "grounding")
        self.assertEqual(target["candidate"], 0)
        safety_event = self.map_events(conv_id)[-1]
        self.assertEqual(safety_event["action"], "technique_phase")
        self.assertEqual(safety_event["source"], "safety")
        self.assertEqual(safety_event["to_status"], "paused")
        self.assertEqual(safety_event["to_phase"], "grounding")
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM session_map_events "
                "WHERE conv=? AND to_status='reached'", (conv_id,))["n"],
            0)

        status, blocked, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id, "id": run_id, "action": "resume"})
        self.assertEqual(status, 409)
        self.assertIn("güvenlik", blocked["error"].casefold())

    def test_end_records_each_outcome_then_always_reaches_closure(self):
        fits = {
            "reached": "helpful",
            "partial": "unclear",
            "paused": "too_much",
            "unchanged": "not_helpful",
        }
        for outcome, fit in fits.items():
            with self.subTest(outcome=outcome):
                method_node = "freud:method:free-association"
                conv_id, _ = self.new_therapy(node_id=method_node)
                note = "{} kapanış değerlendirmesi".format(outcome)
                status, ended, _ = self.request(
                    "POST", "/api/end", {
                        "conv_id": conv_id,
                        "map_outcome": outcome,
                        "map_fit": fit,
                        "map_note": note,
                    })
                self.assertEqual(status, 200, ended)
                self.assertEqual(ended["map_outcome"], outcome)
                self.assertEqual(self.conversation_row(conv_id)["ended"], 1)
                self.assertTrue(ended["processing"])
                self.assertIsNotNone(ended["job_id"])

                prior = self.map_target(conv_id, method_node)
                closure = self.map_target(conv_id, "freud:closure")
                self.assertEqual(prior["status"], outcome)
                self.assertEqual(prior["fit"], fit)
                self.assertEqual(prior["note"], note)
                self.assertEqual(prior["is_current"], 0)
                self.assertEqual(closure["status"], "reached")
                self.assertEqual(closure["phase"], "end")
                self.assertEqual(closure["is_current"], 1)
                self.assertIsNotNone(closure["reached_at"])

                self.assertEqual(
                    ended["map"]["target"]["node_id"], "freud:closure")
                self.assertEqual(
                    ended["map"]["target"]["status"], "reached")
                self.assertTrue(ended["map"]["can_end"])
                events = self.map_events(conv_id)
                self.assertEqual(events[-2]["action"], "select")
                self.assertEqual(events[-2]["node_id"], "freud:closure")
                self.assertEqual(events[-2]["source"], "session_end")
                self.assertEqual(events[-1]["action"], "checkpoint")
                self.assertEqual(events[-1]["node_id"], "freud:closure")
                self.assertEqual(events[-1]["to_status"], "reached")
                self.assertEqual(events[-1]["source"], "session_end")
                job = self.row(
                    "SELECT * FROM jobs WHERE id=?", (ended["job_id"],))
                self.assertEqual(job["status"], "queued")

    def test_end_is_allowed_without_progress_and_during_safety_hold(self):
        conv_id, initial = self.new_therapy()
        self.assertTrue(initial["map"]["can_end"])
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (conv_id,))

        status, ended, _ = self.request(
            "POST", "/api/end", {"conv_id": conv_id})

        self.assertEqual(status, 200)
        self.assertEqual(ended["map_outcome"], "unchanged")
        self.assertEqual(ended["map"]["target"]["node_id"],
                         "freud:closure")
        self.assertEqual(ended["map"]["target"]["status"], "reached")
        entry = self.map_target(conv_id, "freud:entry")
        self.assertEqual(entry["status"], "unchanged")

    def test_prompt_contains_current_target_but_diagnostics_redact_notes(self):
        node_id = "freud:method:transference-pattern"
        conv_id, _ = self.new_therapy(node_id=node_id)
        map_secret = "HARİTA-NOTU-DIAGNOSTICS-E-ÇIKMAMALI"
        status, _, _ = self.post_map(
            conv_id, "checkpoint", outcome="partial", fit="unclear",
            note=map_secret)
        self.assertEqual(status, 200)

        old_conv = self.conversation(
            therapist="freud", title="Önceki onaylı not")
        note_secret = "ONAYLI-SEANS-NOTU-DIAGNOSTICS-E-ÇIKMAMALI"
        with app.db() as conn:
            conn.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,approved,scope,"
                "sensitive,updated) VALUES("
                "?,'terapi','freud',?,?,1,'therapist',0,?)",
                (old_conv, note_secret, app.now(), app.now()))

        prompt = self.system_prompt(conv_id)
        node = app.therapy_map_node("freud", node_id)
        self.assertIn("Bugünkü çalışma odağı", prompt)
        self.assertIn(node["name"], prompt)
        self.assertIn(node["description"], prompt)
        # Durum/Aşama jargonu bağlamdan kaldırıldı; hedefin kendisi ve
        # ilişkisel çerçeve yeterli — tanı gibi yorumlanmaması kuralı kalır.
        self.assertIn("Bu bir tanı, ilerleme cetveli veya zorunlu sıra "
                      "değildir", prompt)
        self.assertIn(note_secret, prompt)

        diagnostic = app.prompt_diagnostics(conv_id)
        rendered = json.dumps(diagnostic, ensure_ascii=False)
        self.assertTrue(diagnostic["content_redacted"])
        self.assertIn("therapy_map_target", diagnostic["components"])
        self.assertIn("approved_notes", diagnostic["components"])
        self.assertEqual(diagnostic["therapy_map"]["node_id"], node_id)
        self.assertEqual(diagnostic["therapy_map"]["status"], "partial")
        self.assertNotIn("note", diagnostic["therapy_map"])
        self.assertNotIn("fit", diagnostic["therapy_map"])
        self.assertNotIn(map_secret, rendered)
        self.assertNotIn(note_secret, rendered)


class TherapyMapPersistenceAndValidationTests(TherapyMapTestCase):

    def _populate_map(self, conv_id, therapist="freud"):
        node_id = app.method_records(therapist)[0]["node_id"]
        status, _, _ = self.post_map(
            conv_id, "select", node_id=node_id)
        self.assertEqual(status, 200)
        status, _, _ = self.post_map(
            conv_id, "checkpoint", outcome="partial", fit="unclear",
            note="aktarılabilir harita notu")
        self.assertEqual(status, 200)
        return node_id

    def test_export_and_per_conversation_delete_cover_all_map_tables(self):
        conv_id, _ = self.new_therapy()
        self._populate_map(conv_id)

        status, exported, _ = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200)
        for table in (
                "session_map_runs", "session_map_targets",
                "session_map_events"):
            self.assertIn(table, exported["data"])
            self.assertTrue(
                any(row["conv"] == conv_id
                    for row in exported["data"][table]),
                table)

        status, body, _ = self.request(
            "POST", "/api/delete", {"id": conv_id})
        self.assertEqual(status, 200, body)
        self.assertIsNone(self.conversation_row(conv_id))
        for table in (
                "session_map_events", "session_map_targets",
                "session_map_runs"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM {} WHERE conv=?"
                        .format(table), (conv_id,))["n"],
                    0)

    def test_delete_all_and_retention_cover_map_tables(self):
        old = self.conversation(
            therapist="jung", created="2000-01-01 00:00",
            updated="2000-01-02 00:00")
        recent = self.conversation(
            therapist="jung", created="2999-01-01 00:00",
            updated="2999-01-02 00:00")
        old_node = "jung:method:dream-amplification"
        recent_node = "jung:method:active-imagination"
        with app.db() as conn:
            old_conv = conn.execute(
                "SELECT * FROM conversations WHERE id=?", (old,)).fetchone()
            recent_conv = conn.execute(
                "SELECT * FROM conversations WHERE id=?", (recent,)).fetchone()
            app.initialize_session_map(conn, old_conv, old_node, False)
            app.checkpoint_session_map(
                conn, old_conv, "partial", "unclear", "eski", "user")
            app.initialize_session_map(
                conn, recent_conv, recent_node, False)
            app.checkpoint_session_map(
                conn, recent_conv, "partial", "unclear", "yeni", "user")

        app.set_setting("retention_days", "30")
        self.assertEqual(app.enforce_retention_policy(), 1)
        self.assertIsNone(self.conversation_row(old))
        self.assertIsNotNone(self.conversation_row(recent))
        for table in (
                "session_map_events", "session_map_targets",
                "session_map_runs"):
            with self.subTest(table=table, age="old"):
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM {} WHERE conv=?"
                        .format(table), (old,))["n"],
                    0)
            with self.subTest(table=table, age="recent"):
                self.assertGreater(
                    self.row(
                        "SELECT COUNT(*) AS n FROM {} WHERE conv=?"
                        .format(table), (recent,))["n"],
                    0)

        status, body, _ = self.request(
            "POST", "/api/delete-all",
            {"confirm": "TÜM VERİLERİ SİL"})
        self.assertEqual(status, 200, body)
        for table in (
                "session_map_events", "session_map_targets",
                "session_map_runs"):
            with self.subTest(table=table, operation="delete-all"):
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM {}".format(table))["n"],
                    0)

    def test_invalid_and_mismatched_map_requests_do_not_mutate_state(self):
        freud_conv, _ = self.new_therapy("freud")
        jung_conv, _ = self.new_therapy("jung")
        lesson = self.conversation(mode="ders", therapist="freud")

        invalid_gets = [
            "/api/therapy-map?therapist=unknown",
            "/api/therapy-map?therapist=freud&conv_id=abc",
            "/api/therapy-map?therapist=freud&conv_id=999999",
            "/api/therapy-map?therapist=freud&conv_id={}".format(lesson),
            "/api/therapy-map?therapist=freud&conv_id={}".format(jung_conv),
        ]
        for path in invalid_gets:
            with self.subTest(path=path):
                status, body, _ = self.request("GET", path)
                self.assertEqual(status, 400, body)

        revision = self.map_run(freud_conv)["revision"]
        invalid_posts = [
            {"conv_id": 999999, "action": "select",
             "node_id": "freud:entry"},
            {"conv_id": lesson, "action": "select",
             "node_id": "freud:entry"},
            {"conv_id": freud_conv, "action": "select",
             "node_id": "jung:entry"},
            {"conv_id": freud_conv, "action": "unknown"},
            {"conv_id": freud_conv, "action": "checkpoint",
             "outcome": "mastered"},
            {"conv_id": freud_conv, "action": "checkpoint",
             "outcome": "partial", "fit": "perfect"},
            {"conv_id": freud_conv, "action": "undo"},
        ]
        for payload in invalid_posts:
            with self.subTest(payload=payload):
                status, _, _ = self.request(
                    "POST", "/api/therapy-map", payload)
                self.assertIn(status, (400, 404))
                self.assertEqual(
                    self.map_run(freud_conv)["revision"], revision)

        before = self.row(
            "SELECT COUNT(*) AS n FROM conversations")["n"]
        status, body, _ = self.request(
            "POST", "/api/new", {
                "mode": "terapi",
                "therapist": "freud",
                "map_node_id": "jung:method:active-imagination",
            })
        self.assertEqual(status, 400, body)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM conversations")["n"],
            before)

        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET ended=1 WHERE id=?",
                (freud_conv,))
        status, body, _ = self.post_map(
            freud_conv, "select", node_id="freud:integration")
        self.assertEqual(status, 409, body)
        self.assertEqual(self.map_run(freud_conv)["revision"], revision)
