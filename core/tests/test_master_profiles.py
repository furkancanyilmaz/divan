import json
from unittest import mock

from support import HTTPTestCase, app


PROFILE_FIELDS = {
    "id", "name", "role", "school", "subtitle", "portrait",
    "lifespan", "birth", "death", "core_views", "approaches",
    "introduction", "ai_boundary",
}


class MasterProfileModelTests(HTTPTestCase):

    def all_master_ids(self):
        return [*app.THERAPISTS, *app.PHILOSOPHERS, *app.COACHES]

    def test_every_public_catalog_entry_has_one_deterministic_profile(self):
        expected_ids = (
            set(app.THERAPISTS)
            | set(app.PHILOSOPHERS)
            | set(app.COACHES)
        )
        profiles = {
            master_id: app.public_master_profile(master_id)
            for master_id in self.all_master_ids()
        }

        self.assertEqual(set(profiles), expected_ids)
        self.assertEqual(len(profiles), 76)
        for master_id, profile in profiles.items():
            with self.subTest(master=master_id):
                self.assertIsNotNone(profile)
                self.assertEqual(
                    profile, app.public_master_profile(master_id))
                self.assertEqual(set(profile), PROFILE_FIELDS)
                self.assertEqual(profile["id"], master_id)
                if master_id in app.THERAPISTS:
                    role, record = "therapist", app.THERAPISTS[master_id]
                    methods = app.THERAPY_METHODS[master_id]
                elif master_id in app.PHILOSOPHERS:
                    role, record = "philosopher", app.PHILOSOPHERS[master_id]
                    methods = app.PHILOSOPHY_METHODS[master_id]
                else:
                    role, record = "coach", app.COACHES[master_id]
                    methods = ()
                self.assertEqual(profile["role"], role)
                self.assertEqual(profile["name"], record["name"])
                self.assertEqual(profile["school"], record["school"])
                dates = app.master_profile_lifespan(record["sub"])
                self.assertEqual(
                    profile["subtitle"],
                    app.master_profile_subtitle(
                        record["sub"], dates["lifespan"]),
                )
                self.assertEqual(profile["core_views"][0], record["quote"])
                self.assertGreaterEqual(len(profile["core_views"]), 2)
                self.assertLessEqual(
                    len(profile["core_views"]),
                    app.MASTER_PROFILE_CORE_VIEW_LIMIT)
                if methods:
                    self.assertEqual(
                        profile["approaches"],
                        [item[0] for item in methods][
                            :app.MASTER_PROFILE_APPROACH_LIMIT],
                    )
                else:
                    self.assertEqual(
                        profile["approaches"],
                        [part.strip() for part in record["school"].split("·")],
                    )
                self.assertFalse(
                    {item.casefold() for item in profile["core_views"]}
                    & {item.casefold() for item in profile["approaches"]}
                )
                self.assertTrue(profile["introduction"])
                self.assertTrue(profile["ai_boundary"])

    def test_lifespan_labels_preserve_circa_bce_and_unknown_dates(self):
        expected = {
            "freud": ("1856–1939", "1856", "1939"),
            "kernberg": ("1928–", "1928", None),
            "socrates": ("y. MÖ 469–399", "y. MÖ 469", "MÖ 399"),
            "aristotle": ("MÖ 384–322", "MÖ 384", "MÖ 322"),
            "epictetus": ("y. 50–135", "y. 50", "135"),
            "yalom": (None, None, None),
            "truth": (None, None, None),
            "adhd": (None, None, None),
        }
        for master_id, dates in expected.items():
            with self.subTest(master=master_id):
                profile = app.public_master_profile(master_id)
                self.assertEqual(
                    (profile["lifespan"], profile["birth"], profile["death"]),
                    dates,
                )

    def test_profile_never_reads_persona_or_method_instruction_text(self):
        secret = "SYSTEM-PERSONA-INSTRUCTION-MUST-NOT-LEAK"
        methods = tuple(
            (name, secret + str(index))
            for index, (name, _) in enumerate(app.THERAPY_METHODS["freud"])
        )
        with mock.patch.dict(
                app.THERAPISTS["freud"], {"persona": secret}), \
                mock.patch.dict(app.THERAPY_METHODS, {"freud": methods}):
            profile = app.public_master_profile("freud")

        serialized = json.dumps(profile, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("persona", profile)
        self.assertNotIn("theme", profile)
        self.assertNotIn("greet_terapi", profile)
        self.assertEqual(
            profile["approaches"], [item[0] for item in methods])

    def test_all_profile_fields_and_lists_have_hard_output_budgets(self):
        long_methods = tuple(
            (("yaklaşım-{:02d}-".format(index) + "x" * 300),
             "hidden-instruction-" + "z" * 500)
            for index in range(20)
        )
        long_record = {
            "name": "N" * 600,
            "school": "S" * 600,
            "sub": "U" * 600,
            "quote": "Q" * 600,
        }
        long_portrait = {
            "url": "/assets/" + "p" * 5000,
            "credit": "c" * 5000,
            "is_placeholder": False,
        }
        with mock.patch.dict(app.THERAPISTS["freud"], long_record), \
                mock.patch.dict(
                    app.THERAPY_METHODS, {"freud": long_methods}), \
                mock.patch.dict(
                    app.PORTRAIT_CATALOG, {"freud": long_portrait}):
            profile = app.public_master_profile("freud")

        for field in ("id", "name", "school", "subtitle",
                      "introduction", "ai_boundary"):
            self.assertLessEqual(
                len(profile[field]),
                app.MASTER_PROFILE_TEXT_LIMITS[field])
        for field in ("lifespan", "birth", "death"):
            if profile[field] is not None:
                self.assertLessEqual(
                    len(profile[field]),
                    app.MASTER_PROFILE_TEXT_LIMITS[field])
        self.assertEqual(
            len(profile["approaches"]),
            app.MASTER_PROFILE_APPROACH_LIMIT)
        self.assertEqual(len(profile["core_views"]), 2)
        for value in profile["approaches"]:
            self.assertLessEqual(
                len(value), app.MASTER_PROFILE_TEXT_LIMITS["approach"])
        for value in profile["core_views"]:
            self.assertLessEqual(
                len(value), app.MASTER_PROFILE_TEXT_LIMITS["core_view"])
        for key, value in profile["portrait"].items():
            if isinstance(value, str):
                self.assertLessEqual(
                    len(value),
                    app.MASTER_PROFILE_TEXT_LIMITS["portrait_value"],
                    key,
                )

    def test_ai_boundary_distinguishes_historical_and_fictional_profiles(self):
        freud = app.public_master_profile("freud")
        yalom = app.public_master_profile("yalom")
        socrates = app.public_master_profile("socrates")

        self.assertIn("Sigmund Freud değildir", freud["ai_boundary"])
        self.assertIn("yapay zekâ canlandırması", freud["ai_boundary"])
        self.assertIn("Tanı, tedavi", freud["ai_boundary"])
        self.assertIn("kurgusal", yalom["ai_boundary"])
        self.assertIn("Doğrudan alıntı", socrates["ai_boundary"])


class MasterProfileEndpointTests(HTTPTestCase):

    def test_endpoint_returns_the_exact_public_profile_contract(self):
        status, profile, headers = self.request(
            "GET", "/api/master-profile?id=freud")

        self.assertEqual(status, 200, profile)
        self.assertEqual(profile, app.public_master_profile("freud"))
        self.assertEqual(set(profile), PROFILE_FIELDS)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("application/json", headers["Content-Type"])

    def test_missing_ambiguous_and_unknown_ids_fail_closed(self):
        cases = (
            ("/api/master-profile", 400),
            ("/api/master-profile?id=", 400),
            ("/api/master-profile?id=freud&extra=1", 400),
            ("/api/master-profile?id=freud&id=jung", 400),
            ("/api/master-profile?id=FREUD", 404),
            ("/api/master-profile?id=../freud", 404),
            ("/api/master-profile?id=unknown_master", 404),
            ("/api/master-profile?id=" + "a" * 65, 404),
        )
        for path, expected_status in cases:
            with self.subTest(path=path):
                status, body, _ = self.request("GET", path)
                self.assertEqual(status, expected_status, body)
                self.assertEqual(set(body), {"error"})

    def test_profile_is_public_under_pin_and_guest_without_personal_data(self):
        secret = "PRIVATE-USER-PROFILE-MUST-NOT-LEAK"
        app.set_setting("pin_hash", app.pin_hash("2468"))
        app.set_setting("guest_mode", "1")
        app.set_setting("profile", secret)
        conv_id = self.conversation(therapist="freud")
        with app.db() as connection:
            connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", secret, "2026-08-17 12:00"),
            )

        status, profile, _ = self.request(
            "GET", "/api/master-profile?id=freud")
        protected_status, _, _ = self.request("GET", "/api/conversations")

        self.assertEqual(status, 200, profile)
        self.assertEqual(profile, app.public_master_profile("freud"))
        self.assertNotIn(secret, json.dumps(profile, ensure_ascii=False))
        self.assertEqual(protected_status, 423)

    def test_endpoint_enforces_embedded_cookie_local_host_and_origin(self):
        app.EMBEDDED_SESSION_TOKEN = "master-profile-session-token"
        cookie = "{}={}".format(
            app.EMBEDDED_SESSION_COOKIE, app.EMBEDDED_SESSION_TOKEN)
        path = "/api/master-profile?id=socrates"

        status, body, _ = self.request("GET", path)
        self.assertEqual(status, 403, body)

        status, body, _ = self.request(
            "GET", path, headers={"Cookie": cookie})
        self.assertEqual(status, 200, body)

        status, body, _ = self.request(
            "GET", path,
            headers={"Cookie": cookie, "Host": "example.com"})
        self.assertEqual(status, 403, body)

        status, body, _ = self.request(
            "GET", path,
            headers={"Cookie": cookie, "Origin": "https://example.com"})
        self.assertEqual(status, 403, body)
        self.assertIn("çapraz", body["error"])

        status, body, _ = self.request(
            "GET", path,
            headers={
                "Cookie": cookie,
                "Origin": "http://127.0.0.1:{}".format(app.PORT),
            })
        self.assertEqual(status, 200, body)


if __name__ == "__main__":
    import unittest
    unittest.main()
