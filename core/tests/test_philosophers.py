from pathlib import Path
from unittest import mock

from support import HTTPTestCase, app


EXPECTED_THERAPISTS = {
    "freud", "jung", "klein", "winnicott", "bowlby", "ferenczi",
    "kohut", "rogers", "beck", "frankl", "perls", "yalom", "young",
    "adler", "horney", "erickson", "berne", "satir", "linehan",
    "hayes", "lacan", "truth", "bion", "kernberg", "fonagy", "ellis",
    "insoo_berg", "white", "minuchin", "bowen", "greenberg", "miller",
    "shapiro", "sue_johnson",
}

EXPECTED_DARK_RESEARCHERS = {
    "delroy_paulhus", "kevin_williams", "erin_buckels", "daniel_jones",
    "henri_chabrol", "morten_moshagen",
}

EXPECTED_DARK_THINKERS = {
    "machiavelli", "hobbes", "la_rochefoucauld", "de_sade",
    "schopenhauer", "cioran", "carl_schmitt",
}

EXPECTED_PUBLIC_THINKERS = {
    "steven_pinker", "vaclav_smil", "david_christian", "bill_gates",
    "steve_jobs",
}

EXPECTED_LIVING_PUBLIC_THINKERS = {
    "steven_pinker", "vaclav_smil", "david_christian", "bill_gates",
}

EXPECTED_PHILOSOPHERS = {
    "socrates", "plato", "aristotle", "epictetus", "marcus_aurelius",
    "epicurus", "confucius", "farabi", "ibn_sina", "ibn_rushd",
    "descartes", "spinoza", "hume", "kant", "kierkegaard", "nietzsche",
    "wittgenstein", "sartre", "beauvoir", "camus", "arendt",
    "merleau_ponty", "foucault",
} | EXPECTED_DARK_RESEARCHERS | EXPECTED_DARK_THINKERS | \
    EXPECTED_PUBLIC_THINKERS

META_IDENTITY_OPENING_FRAGMENTS = (
    "yayımlanmış eserlerden sentezim",
    "yayımlanmış eserlerin senteziyim",
    "eğitimsel temsiliyim",
    "eğitimsel bir canlandırmayım",
    "akademik canlandırmayım",
    "gerçek kişi değilim",
    "o kişinin kendisi değilim",
    "bir dil modeliyim",
    "yapay zekâyım",
    "yapay araştırma diyaloğuyum",
    "bu tarihsel canlandırmada",
    "bu akademik canlandırmada",
)


class PhilosopherCatalogTests(HTTPTestCase):

    def test_clinical_and_philosophy_catalogs_are_exact_and_disjoint(self):
        self.assertEqual(set(app.THERAPISTS), EXPECTED_THERAPISTS)
        self.assertEqual(set(app.PHILOSOPHERS), EXPECTED_PHILOSOPHERS)
        self.assertEqual(len(app.THERAPISTS), 34)
        self.assertEqual(len(app.PHILOSOPHERS), 41)
        self.assertTrue(
            set(app.THERAPISTS).isdisjoint(set(app.PHILOSOPHERS)))
        self.assertEqual(
            set(app.ALL_MASTERS),
            EXPECTED_THERAPISTS | EXPECTED_PHILOSOPHERS,
        )

        for philosopher_id, philosopher in app.PHILOSOPHERS.items():
            with self.subTest(philosopher=philosopher_id):
                self.assertTrue(app.is_philosopher(philosopher_id))
                self.assertFalse(app.is_philosopher("freud"))
                self.assertIs(
                    app.master_record(philosopher_id, fallback=False),
                    philosopher,
                )
                for key in (
                        "name", "initials", "emoji", "school", "sub",
                        "quote", "greet_ders", "persona", "theme"):
                    self.assertIn(key, philosopher)
                    self.assertTrue(philosopher[key])
                self.assertNotIn("greet_terapi", philosopher)

    def test_dark_catalog_groups_are_exact_disjoint_and_visible(self):
        self.assertEqual(
            set(app.DARK_PERSONALITY_RESEARCHER_IDS),
            EXPECTED_DARK_RESEARCHERS,
        )
        self.assertEqual(set(app.DARK_THINKER_IDS), EXPECTED_DARK_THINKERS)
        self.assertTrue(
            app.DARK_PERSONALITY_RESEARCHER_IDS.isdisjoint(
                app.DARK_THINKER_IDS))
        self.assertTrue(
            set(app.DARK_PERSONALITY_RESEARCHER_IDS) <=
            set(app.PHILOSOPHERS))
        self.assertTrue(set(app.DARK_THINKER_IDS) <= set(app.PHILOSOPHERS))

        for philosopher_id in EXPECTED_DARK_RESEARCHERS:
            self.assertEqual(
                app.PHILOSOPHERS[philosopher_id]["school"],
                "Karanlık Kişilik Araştırmacıları",
            )
        for philosopher_id in EXPECTED_DARK_THINKERS:
            self.assertEqual(
                app.PHILOSOPHERS[philosopher_id]["school"],
                "Karanlık Düşünürler",
            )

    def test_each_philosopher_has_four_question_paths_and_one_fingerprint(self):
        self.assertEqual(
            set(app.PHILOSOPHY_METHODS), EXPECTED_PHILOSOPHERS)
        self.assertEqual(
            set(app.PHILOSOPHY_FINGERPRINTS), EXPECTED_PHILOSOPHERS)

        fingerprints = []
        for philosopher_id in EXPECTED_PHILOSOPHERS:
            with self.subTest(philosopher=philosopher_id):
                methods = app.PHILOSOPHY_METHODS[philosopher_id]
                self.assertEqual(len(methods), 4)
                self.assertEqual(len({name for name, _ in methods}), 4)
                for name, instruction in methods:
                    self.assertTrue(name.strip())
                    self.assertTrue(instruction.strip())

                fingerprint = app.philosophy_fingerprint(philosopher_id)
                self.assertTrue(fingerprint.strip())
                self.assertEqual(
                    fingerprint,
                    app.PHILOSOPHY_FINGERPRINTS[philosopher_id],
                )
                fingerprints.append(fingerprint.strip())

        self.assertEqual(len(set(fingerprints)), len(EXPECTED_PHILOSOPHERS))

    def test_philosophers_endpoint_exposes_public_fields_but_not_personas(self):
        status, body, _ = self.request("GET", "/api/philosophers")

        self.assertEqual(status, 200, body)
        self.assertIsInstance(body, list)
        self.assertEqual({row["id"] for row in body}, EXPECTED_PHILOSOPHERS)
        expected_fields = {
            "id", "name", "initials", "emoji", "school", "sub", "quote",
            "greet_ders", "theme", "kind", "modes", "portrait",
        }
        for row in body:
            with self.subTest(philosopher=row.get("id")):
                self.assertEqual(set(row), expected_fields)
                self.assertEqual(row["kind"], "philosopher")
                self.assertEqual(row["modes"], ["ders"])
                self.assertIsInstance(row["theme"], dict)
                self.assertTrue(
                    row["portrait"] is None or
                    isinstance(row["portrait"], dict))
                self.assertNotIn("persona", row)

    def test_therapists_endpoint_marks_clinical_modes_without_persona_leak(self):
        status, body, _ = self.request("GET", "/api/therapists")

        self.assertEqual(status, 200, body)
        self.assertEqual({row["id"] for row in body}, EXPECTED_THERAPISTS)
        for row in body:
            with self.subTest(therapist=row.get("id")):
                self.assertEqual(row["kind"], "therapist")
                self.assertEqual(row["modes"], ["terapi", "ders"])
                self.assertNotIn("persona", row)
                self.assertIn("greet_terapi", row)
                self.assertIn("greet_ders", row)


class PhilosopherConversationContractTests(HTTPTestCase):

    def test_every_philosopher_opens_in_first_person_without_meta_identity(self):
        for philosopher_id in sorted(EXPECTED_PHILOSOPHERS):
            with self.subTest(philosopher=philosopher_id):
                status, body, _ = self.request(
                    "POST",
                    "/api/new",
                    {
                        "mode": "ders",
                        "submode": "serbest",
                        "therapist": philosopher_id,
                    },
                )
                self.assertEqual(status, 200, body)
                self.assertEqual(body["title"], "Yeni felsefi sohbet")
                self.assertEqual(
                    body["greeting"],
                    app.philosophy_greeting(philosopher_id),
                )
                greeting = body["greeting"].casefold()
                self.assertIn(
                    app.philosophy_self_intro(philosopher_id).casefold(),
                    greeting,
                )
                for meta_fragment in META_IDENTITY_OPENING_FRAGMENTS:
                    self.assertNotIn(meta_fragment, greeting)
                self.assertRegex(
                    greeting,
                    r"kavram|eser|sav|argüman|itiraz|bakış",
                )
                row = self.conversation_row(body["id"])
                self.assertIsNotNone(row)
                self.assertEqual(row["mode"], "ders")
                self.assertEqual(row["submode"], "serbest")
                self.assertEqual(row["therapist"], philosopher_id)
                self.assertEqual(row["title"], "Yeni felsefi sohbet")

    def test_vaclav_smil_api_greeting_uses_exact_first_person_identity(self):
        status, body, _ = self.request(
            "POST",
            "/api/new",
            {
                "mode": "ders",
                "submode": "serbest",
                "therapist": "vaclav_smil",
            },
        )

        self.assertEqual(status, 200, body)
        self.assertIn("Ben Volkan Sayılar'ım.", body["greeting"])

    def test_confucius_greeting_does_not_probe_personal_role_or_problem(self):
        greeting = app.philosophy_greeting("confucius").casefold()

        for personal_probe in (
                "hangi rolde", "davranmak istiyorsunuz", "sorununuz",
                "duygunuz", "ilişkiniz", "hayatınızda", "yaşamınızda"):
            with self.subTest(personal_probe=personal_probe):
                self.assertNotIn(personal_probe, greeting)
        self.assertRegex(
            greeting,
            r"kavram|eser|sav|argüman|itiraz|bakış",
        )

    def test_philosopher_is_rejected_from_therapy_mode(self):
        before = self.row(
            "SELECT COUNT(*) AS n FROM conversations")["n"]

        status, body, _ = self.request(
            "POST",
            "/api/new",
            {
                "mode": "terapi",
                "therapist": "socrates",
                "precheck": {"safety_ok": True},
            },
        )

        self.assertEqual(status, 400, body)
        self.assertIn("error", body)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM conversations")["n"],
            before,
        )

    def test_unknown_master_never_silently_creates_a_freud_conversation(self):
        for mode in ("terapi", "ders"):
            with self.subTest(mode=mode):
                before = self.row(
                    "SELECT COUNT(*) AS n FROM conversations")["n"]
                status, body, _ = self.request(
                    "POST",
                    "/api/new",
                    {
                        "mode": mode,
                        "submode": "serbest" if mode == "ders" else None,
                        "therapist": "usta-katalogda-yok",
                    },
                )
                self.assertEqual(status, 400, body)
                self.assertIn("error", body)
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM conversations")["n"],
                    before,
                )
        self.assertIsNone(
            app.master_record("usta-katalogda-yok", fallback=False))

    def test_philosopher_prompt_has_own_voice_methods_and_nonclinical_boundary(self):
        clinical_fingerprints = tuple(app.THERAPY_FINGERPRINTS.values())
        for philosopher_id in sorted(EXPECTED_PHILOSOPHERS):
            with self.subTest(philosopher=philosopher_id):
                conv_id = self.conversation(
                    mode="ders",
                    submode="serbest",
                    therapist=philosopher_id,
                    title="Felsefi diyalog",
                )
                prompt = self.system_prompt(conv_id)
                fingerprint = app.philosophy_fingerprint(philosopher_id)
                immersive_voice = app.PHILOSOPHY_IMMERSIVE_VOICE.format(
                    name=app.master_name(philosopher_id),
                    self_intro=app.philosophy_self_intro(philosopher_id),
                )
                late_voice = app.philosophy_late_voice_prompt(philosopher_id)

                self.assertIn(
                    app.PHILOSOPHERS[philosopher_id]["persona"], prompt)
                self.assertIn(app.PHILOSOPHER_TAIL, prompt)
                self.assertIn(app.PHILOSOPHY_TEACHER_COMMON, prompt)
                self.assertIn(app.PHILOSOPHY_DIALOGUE_PROMPT, prompt)
                self.assertIn(
                    app.philosophy_methods_prompt(philosopher_id), prompt)
                self.assertEqual(prompt.count(fingerprint), 1)
                self.assertEqual(
                    prompt.count(app.PHILOSOPHY_DEFAULT_RESPONSE), 1)
                self.assertEqual(prompt.count(immersive_voice), 1)
                self.assertTrue(late_voice.endswith(immersive_voice))
                self.assertTrue(prompt.endswith(late_voice))

                self.assertNotIn(app.THERAPY_PROMPT, prompt)
                self.assertNotIn(app.METHOD_SAFETY, prompt)
                self.assertNotIn(app.COLLABORATIVE_DISCOVERY, prompt)
                for clinical_fingerprint in clinical_fingerprints:
                    self.assertNotIn(clinical_fingerprint, prompt)

    def test_living_public_prompts_keep_private_current_and_spokesperson_limits(self):
        self.assertEqual(
            set(app.LIVING_PUBLIC_THINKER_IDS),
            EXPECTED_LIVING_PUBLIC_THINKERS,
        )
        for philosopher_id in sorted(EXPECTED_LIVING_PUBLIC_THINKERS):
            with self.subTest(philosopher=philosopher_id):
                conv_id = self.conversation(
                    mode="ders",
                    submode="serbest",
                    therapist=philosopher_id,
                    title="Yaşayan kamusal düşünür",
                )
                prompt = self.system_prompt(conv_id)
                normalized = " ".join(prompt.casefold().split())

                self.assertEqual(
                    prompt.count(app.PUBLIC_THINKER_BOUNDARY), 1)
                self.assertIn("yaşayan kişi sınırı", normalized)
                self.assertIn("özel deneyim", normalized)
                self.assertIn("kamuya açık güncel bilgiyi", normalized)
                self.assertRegex(
                    normalized,
                    r"özel/?yayımlanmamış (?:güncel )?görüş",
                )
                self.assertIn("kurum sözcülüğü", normalized)
                self.assertIn("uydurma", normalized)

    def test_default_philosophy_contract_is_explanatory_not_personal_probing(self):
        contract = " ".join(
            app.PHILOSOPHY_DEFAULT_RESPONSE.casefold().split())

        self.assertRegex(
            contract,
            r"bu mesaj.{0,180}kişisel.{0,80}uygula.{0,80}açık",
        )
        self.assertRegex(
            contract,
            r"sorun.{0,80}duygu.{0,80}ilişki",
        )
        self.assertRegex(contract, r"sorma|istem[eeyi]*")
        self.assertRegex(
            contract,
            r"kavram.{0,120}(?:sav|argüman).{0,120}(?:itiraz|sınır)",
        )

        conv_id = self.conversation(
            mode="ders",
            submode="serbest",
            therapist="confucius",
            title="Konfüçyüs'ün bakışı",
        )
        prompt = self.system_prompt(conv_id)
        self.assertEqual(prompt.count(app.PHILOSOPHY_DEFAULT_RESPONSE), 1)
        self.assertTrue(
            prompt.endswith(app.philosophy_late_voice_prompt("confucius")))

    def test_explicit_personal_application_is_the_only_opt_in(self):
        contract = " ".join(
            app.PHILOSOPHY_DEFAULT_RESPONSE.casefold().split())

        self.assertRegex(
            contract,
            r"bu mesaj(?:ın)?da.{0,150}açık.{0,80}(?:yalnız|ancak)",
        )
        self.assertRegex(
            contract,
            r"(?:kişisel|kendi durumuna).{0,80}uygula.{0,120}"
            r"(?:yalnız|sadece).{0,120}(?:verdiği|paylaştığı|belirttiği)",
        )
        self.assertRegex(
            contract,
            r"(?:ek|fazladan|ilave).{0,80}(?:özel|kişisel|mahrem).{0,80}"
            r"(?:sorma|avına çıkma|isteme)",
        )

    def test_profile_and_previous_memory_are_not_personal_application_permission(self):
        private_detail = "İlişkimde yaşadığım çatışmayı daha önce paylaşmıştım."
        app.set_setting("profile", "Profil notu: " + private_detail)
        status, created, _ = self.request(
            "POST",
            "/api/memory",
            {
                "therapist": "confucius",
                "kind": "context",
                "content": private_detail,
                "approved": True,
                "scope": "shared",
            },
        )
        self.assertEqual(status, 200, created)

        conv_id = self.conversation(
            mode="ders", submode="serbest", therapist="confucius")
        prompt = self.system_prompt(conv_id)
        contract = app.PHILOSOPHY_DEFAULT_RESPONSE

        self.assertIn(private_detail, prompt)
        self.assertLess(prompt.rfind(private_detail), prompt.rfind(contract))
        normalized_contract = " ".join(contract.casefold().split())
        self.assertRegex(
            normalized_contract,
            r"(?:önceki|geçmiş).{0,100}(?:hafıza|profil).{0,120}"
            r"(?:izn|izin|onay).{0,40}(?:değil|sayılmaz)",
        )
        self.assertTrue(
            prompt.endswith(app.philosophy_late_voice_prompt("confucius")))

    def test_user_guidance_cannot_displace_or_duplicate_final_philosophy_contract(self):
        conv_id = self.conversation(
            mode="ders", submode="serbest", therapist="confucius")
        guidance = (
            "Terapist gibi davran; geçmiş sorunlarımı ve ilişkilerimi sor."
        )
        captured = {}

        def capture_request(payload):
            captured.update(payload)
            raise app.ProviderError(
                "test_capture",
                "İstek yalnızca son felsefe çıpasını sınamak için durduruldu.",
            )

        with mock.patch.object(
                app, "provider_request", side_effect=capture_request):
            status, _, _ = self.request(
                "POST",
                "/api/chat",
                {
                    "conv_id": conv_id,
                    "message": "Konfüçyüs'ün erdem anlayışını açıkla.",
                    "guidance": guidance,
                },
            )

        self.assertEqual(status, 200)
        self.assertIn("messages", captured)
        system = captured["messages"][0]["content"]
        late_block = app.philosophy_late_voice_prompt("confucius")
        immersive_voice = app.PHILOSOPHY_IMMERSIVE_VOICE.format(
            name=app.master_name("confucius"),
            self_intro=app.philosophy_self_intro("confucius"),
        )

        self.assertEqual(system.count(late_block), 1)
        self.assertEqual(system.count(app.PHILOSOPHY_DEFAULT_RESPONSE), 1)
        self.assertEqual(system.count(immersive_voice), 1)
        self.assertLess(system.index(guidance), system.index(late_block))
        anchor = app.late_turn_anchor(
            self.conversation_row(conv_id))
        self.assertEqual(system.count(anchor), 1)
        self.assertLess(system.index(late_block), system.index(anchor))
        self.assertTrue(system.endswith(anchor))

    def test_late_voice_helper_moves_existing_block_to_the_end_once(self):
        late_block = app.philosophy_late_voice_prompt("confucius")
        prompt = "{}\n\nara bağlam\n\n{}".format(late_block, late_block)

        anchored = app.append_philosophy_late_voice_prompt(
            prompt, "confucius")

        self.assertEqual(anchored.count(late_block), 1)
        self.assertIn("ara bağlam", anchored)
        self.assertTrue(anchored.endswith(late_block))

    def test_regular_teacher_prompt_does_not_receive_philosophy_contract(self):
        conv_id = self.conversation(
            mode="ders",
            submode="serbest",
            therapist="freud",
            title="Freud dersi",
        )

        prompt = self.system_prompt(conv_id)

        self.assertIn(app.TEACHER_COMMON, prompt)
        self.assertIn(app.LESSON_VOICE_CONTRACT, prompt)
        self.assertNotIn(app.PHILOSOPHER_TAIL, prompt)
        self.assertNotIn(app.PHILOSOPHY_TEACHER_COMMON, prompt)
        self.assertNotIn(app.PHILOSOPHY_DIALOGUE_PROMPT, prompt)

    def test_dark_research_prompts_are_educational_not_diagnostic(self):
        for philosopher_id in sorted(EXPECTED_DARK_RESEARCHERS):
            with self.subTest(philosopher=philosopher_id):
                conv_id = self.conversation(
                    mode="ders",
                    submode="serbest",
                    therapist=philosopher_id,
                    title="Karanlık kişilik araştırması",
                )
                prompt = self.system_prompt(conv_id)

                self.assertEqual(
                    prompt.count(app.DARK_PERSONALITY_RESEARCH_BOUNDARY), 1)
                self.assertNotIn(app.DARK_THOUGHT_BOUNDARY, prompt)
                self.assertIn("SAVUNUCUSU değildir", prompt)
                self.assertIn("boyutsal araştırma", prompt)
                self.assertIn("klinik tanı", prompt)
                self.assertIn("etiketleme", prompt)
                self.assertIn("uygulanabilir talimat verme", prompt)

    def test_dark_researcher_personas_drop_legacy_meta_identity_language(self):
        legacy_fragments = (
            "açıkça yapay",
            "yapay bir araştırma diyaloğu",
            "araştırma diyaloğusun",
            "sentez",
            "kendisi gibi davranmazsın",
            "kişinin kendisi değil",
        )
        for philosopher_id in sorted(EXPECTED_DARK_RESEARCHERS):
            with self.subTest(philosopher=philosopher_id):
                persona = app.PHILOSOPHERS[philosopher_id]["persona"].casefold()

                # Yaşayan araştırmacılar kurgusal karakterlerle temsil
                # edilir; persona kurgusallığı açıkça söyler ve gerçek
                # kişi olduğu izlenimini vermez.
                self.assertIn("kurgusal", persona)
                self.assertIn("temsil etmezsin", persona)
                for legacy_fragment in legacy_fragments:
                    self.assertNotIn(legacy_fragment, persona)

    def test_dark_thought_prompts_analyse_without_teaching_harm(self):
        for philosopher_id in sorted(EXPECTED_DARK_THINKERS):
            with self.subTest(philosopher=philosopher_id):
                conv_id = self.conversation(
                    mode="ders",
                    submode="serbest",
                    therapist=philosopher_id,
                    title="Karanlık düşünce diyaloğu",
                )
                prompt = self.system_prompt(conv_id)

                self.assertEqual(prompt.count(app.DARK_THOUGHT_BOUNDARY), 1)
                self.assertNotIn(
                    app.DARK_PERSONALITY_RESEARCH_BOUNDARY, prompt)
                self.assertIn("güçlü karşı görüşü", prompt)
                self.assertIn("uygulanabilir talimat verme", prompt)
                self.assertIn("rol oyunu olarak da", prompt)
                self.assertIn("Dark Triad/Tetrad tanısı", prompt)

    def test_dark_boundaries_do_not_leak_to_regular_dialogues(self):
        philosopher_conv = self.conversation(
            mode="ders", submode="serbest", therapist="socrates")
        therapist_conv = self.conversation(
            mode="ders", submode="serbest", therapist="freud")

        for prompt in (
                self.system_prompt(philosopher_conv),
                self.system_prompt(therapist_conv)):
            self.assertNotIn(app.DARK_PERSONALITY_RESEARCH_BOUNDARY, prompt)
            self.assertNotIn(app.DARK_THOUGHT_BOUNDARY, prompt)

    def test_high_risk_dark_personas_keep_specific_historical_boundaries(self):
        machiavelli = app.PHILOSOPHERS["machiavelli"]["persona"]
        de_sade = app.PHILOSOPHERS["de_sade"]["persona"]
        cioran = app.PHILOSOPHERS["cioran"]["persona"]
        schmitt = app.PHILOSOPHERS["carl_schmitt"]["persona"]

        self.assertIn("yüzyıllar sonra", machiavelli)
        self.assertIn("özdeş olmadığını", machiavelli)
        self.assertIn("Rızasız", de_sade)
        self.assertIn("çocuk istismarı", de_sade)
        self.assertIn("kendine zarar", cioran)
        self.assertIn("güvenlik", cioran)
        self.assertIn("Nazi rejimiyle", schmitt)
        self.assertIn("antisemitizmini", schmitt)

    def test_philosopher_transcript_uses_dialogue_and_philosopher_labels(self):
        conv_id = self.conversation(
            mode="ders",
            submode="serbest",
            therapist="socrates",
            title="Etiket deneyi",
        )
        self.messages(conv_id, 2, prefix="felsefe")

        transcript = app.transcript_of(conv_id, "ders")

        self.assertIn("Diyalog ortağı: felsefe-00", transcript)
        self.assertIn("Filozof: felsefe-01", transcript)
        self.assertNotIn("Öğrenci:", transcript)
        self.assertNotIn("Terapist:", transcript)


class PhilosopherClinicalBoundaryTests(HTTPTestCase):

    def test_clinical_method_and_map_gets_reject_philosopher_ids(self):
        for path in (
                "/api/methods?therapist=socrates",
                "/api/therapy-map?therapist=socrates"):
            with self.subTest(path=path):
                status, body, _ = self.request("GET", path)
                self.assertEqual(status, 400, body)
                self.assertIn("error", body)
                self.assertNotIn("methods", body)
                self.assertNotIn("nodes", body)

        self.assertEqual(app.method_records("socrates"), [])

    def test_unknown_ids_are_not_rewritten_to_freud_by_clinical_gets(self):
        for path in (
                "/api/methods?therapist=usta-katalogda-yok",
                "/api/therapy-map?therapist=usta-katalogda-yok"):
            with self.subTest(path=path):
                status, body, _ = self.request("GET", path)
                self.assertEqual(status, 400, body)
                self.assertIn("error", body)
                self.assertNotIn("methods", body)
                self.assertNotIn("nodes", body)

    def test_philosopher_private_memory_can_be_saved_read_and_recalled(self):
        content = "Erdem sözcüğünü alışkanlık örneğiyle ele almayı tercih ederim."
        status, created, _ = self.request(
            "POST",
            "/api/memory",
            {
                "therapist": "aristotle",
                "kind": "preference",
                "content": content,
                "approved": True,
                "scope": "therapist",
            },
        )
        self.assertEqual(status, 200, created)
        self.assertEqual(created["memory"]["therapist"], "aristotle")

        status, body, _ = self.request(
            "GET", "/api/memories?therapist=aristotle")
        self.assertEqual(status, 200, body)
        self.assertIn(
            content,
            [row["content"] for row in body["memories"]],
        )

        own_conv = self.conversation(
            mode="ders", submode="serbest", therapist="aristotle")
        other_conv = self.conversation(
            mode="ders", submode="serbest", therapist="socrates")
        self.assertIn(content, self.system_prompt(own_conv))
        self.assertNotIn(content, self.system_prompt(other_conv))


class PhilosopherInterfaceSourceTests(HTTPTestCase):

    def test_selection_ui_has_accessible_catalog_tabs_and_loads_both_catalogs(self):
        source = (Path(app.DIR) / "index.html").read_text(encoding="utf-8")

        self.assertIn(
            'class="personaCatalogTabs" role="tablist"', source)
        self.assertIn('id="therapistCatalogTab"', source)
        self.assertIn('id="philosopherCatalogTab"', source)
        self.assertIn("Felsefeciler", source)
        self.assertIn("api('/api/therapists')", source)
        self.assertIn("api('/api/philosophers')", source)
        self.assertIn("Promise.all", source)
