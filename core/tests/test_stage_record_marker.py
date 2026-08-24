"""Kerem `explore` kapısını KONUŞARAK açabilmeli ([[KAYIT]]).

Gerçek tıkanma: tetikleyici/ihtiyaç kaydı yalnız kullanıcının butona
basmasıyla oluşuyordu. Kayıt olmayınca `explore` kapısı hiç açılmıyor,
seans yöntem aşamasına ulaşamıyor, terapi metotları hiç gelmiyordu.

Sınır korunur: değer kullanıcının kendi cümlesinden gelir ve ilk kayıt
üzerine yazılmaz.
"""

from support import HTTPTestCase, app


class StageRecordParseTests(HTTPTestCase):
    def test_records_are_parsed_and_stripped(self):
        text, _, _, _, _, records = app.split_schema_markers(
            "Bunu duydum.\n"
            "[[KAYIT]] tetikleyici | patron bağırdı\n"
            "[[KAYIT]] ihtiyac | güvende hissetmek")
        self.assertEqual(text, "Bunu duydum.")
        self.assertEqual(
            [r["kind"] for r in records], ["current_trigger", "need"])
        for mark in app.SCHEMA_ALL_MARKS:
            self.assertNotIn(mark, text)

    def test_unknown_kind_is_dropped(self):
        text, _, _, _, _, records = app.split_schema_markers(
            "Merhaba.\n[[KAYIT]] uydurma | bir şey")
        self.assertEqual(text, "Merhaba.")
        self.assertEqual(records, [])

    def test_empty_value_is_skipped(self):
        self.assertEqual(
            app.collect_stage_records("[[KAYIT]] tetikleyici | "), [])


class StageRecordWriteTests(HTTPTestCase):
    stamp = "2026-08-20 19:30"

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        with app.db() as connection:
            # Kayıt yalnız kullanıcının KENDİ sözüne dayanabilir
            # (sahte anı yasağı); dayanak metni burada oluşur.
            connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'user',"
                "'patron bağırdı, güvende hissetmek istiyorum',?,"
                "'completed')", (self.conv, self.stamp))
            claim = connection.execute(
                "INSERT INTO psych_claims(source_conv,therapist,lens,"
                "claim_type,title,statement,trigger_text,experience_text,"
                "response_text,short_term_effect,long_term_effect,"
                "need_text,counterexample_text,context_label,review_note,"
                "status,scope,sensitive,user_edited,reviewed_evidence_id,"
                "created,updated) VALUES(?,'young','','schema_hypothesis',"
                "'b','i','','','','','','','','','','confirmed','session',"
                "0,0,0,?,?)",
                (self.conv, self.stamp, self.stamp)).lastrowid
            self.path = connection.execute(
                "INSERT INTO schema_paths(conv,therapist,claim,phase,"
                "status,revision,created,updated) "
                "VALUES(?,'young',?,'explore','active',1,?,?)",
                (self.conv, claim, self.stamp, self.stamp)).lastrowid

    def path_row(self, connection):
        return connection.execute(
            "SELECT * FROM schema_paths WHERE id=?", (self.path,)).fetchone()

    def test_records_open_the_explore_gate(self):
        with app.db() as connection:
            self.assertEqual(
                app.schema_phase_gate_blocked(
                    connection, self.path_row(connection)),
                "trigger_need_missing")
            app._record_stage_values(connection, self.conv, [
                {"kind": "current_trigger", "value": "patron bağırdı"},
                {"kind": "need", "value": "güvende hissetmek"}])
            # Kapı artık açık: seans yöntem aşamasına ilerleyebilir.
            self.assertIsNone(
                app.schema_phase_gate_blocked(
                    connection, self.path_row(connection)))

    def test_record_is_attributed_to_the_user(self):
        # Değer kullanıcının kendi cümlesidir; kayıt da öyle işaretlenir.
        with app.db() as connection:
            app._record_stage_values(connection, self.conv, [
                {"kind": "current_trigger", "value": "patron bağırdı"}])
            row = connection.execute(
                "SELECT authored_by,value FROM schema_path_events "
                "WHERE action='record' AND path=?", (self.path,)).fetchone()
        self.assertEqual(row["authored_by"], "user")
        self.assertEqual(row["value"], "patron bağırdı")

    def test_existing_record_is_not_overwritten(self):
        with app.db() as connection:
            app._record_stage_values(connection, self.conv, [
                {"kind": "current_trigger", "value": "patron bağırdı"}])
            app._record_stage_values(connection, self.conv, [
                {"kind": "current_trigger", "value": "güvende hissetmek"}])
            values = app.schema_path_record_values(connection, self.path)
        self.assertEqual(values["current_trigger"], ["patron bağırdı"])


    def test_fabricated_memory_is_rejected(self):
        """SAHTE ANI YASAĞI: model uydurduğu sahneyi kaydedemez.

        Kayıt `authored_by='user'` olarak yazılıyor. Model kullanıcının
        hiç söylemediği bir çocukluk sahnesini buraya yazarsa, uydurma
        bir anı kullanıcının kendi sözü gibi kalıcılaşır.
        """
        with app.db() as connection:
            app._record_stage_values(connection, self.conv, [
                {"kind": "current_trigger",
                 "value": "babam yedi yaşımda sofrada beni aşağıladı"}])
            values = app.schema_path_record_values(connection, self.path)
        self.assertNotIn("current_trigger", values)

    def test_user_own_words_are_accepted(self):
        with app.db() as connection:
            app._record_stage_values(connection, self.conv, [
                {"kind": "current_trigger", "value": "patron bağırdı"}])
            values = app.schema_path_record_values(connection, self.path)
        self.assertEqual(values["current_trigger"], ["patron bağırdı"])
