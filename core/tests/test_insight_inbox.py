import unittest

from support import HTTPTestCase, app


class InsightInboxTests(HTTPTestCase):

    def test_inbox_lists_proposed_concepts_and_unverified_hypotheses(self):
        conv_id = self.conversation(therapist="freud")
        stamp = app.now()
        with app.db() as c:
            c.execute(
                "INSERT INTO concept_observations("
                "conv,therapist,concept_key,evidence_quote,strength,status,"
                "stage,created,updated) VALUES(?,'freud','transference',"
                "'kanıt',0.6,'proposed','tracking',?,?)",
                (conv_id, stamp, stamp))
            c.execute(
                "INSERT INTO hypotheses(conv,therapist,text,status,"
                "through_message_id,created,updated) "
                "VALUES(?,'freud','Doğrulanmamış örüntü','active',1,?,?)",
                (conv_id, stamp, stamp))
        status, body, _ = self.request(
            "GET", "/api/inbox?therapist=freud")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["proposed_concepts"]), 1)
        self.assertEqual(body["proposed_concepts"][0]["concept_key"],
                         "transference")
        self.assertEqual(len(body["hypotheses"]), 1)
        self.assertEqual(body["hypotheses"][0]["text"],
                         "Doğrulanmamış örüntü")

    def test_verified_hypothesis_leaves_inbox(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO hypotheses(conv,therapist,text,status,"
                "user_decision,decision_at,through_message_id,created,updated) "
                "VALUES(?,'freud','Doğrulanmış','verified','uyuyor',?,1,?,?)",
                (conv_id, app.now(), app.now(), app.now()))
        status, body, _ = self.request(
            "GET", "/api/inbox?therapist=freud")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["hypotheses"]), 0)


if __name__ == "__main__":
    unittest.main()
