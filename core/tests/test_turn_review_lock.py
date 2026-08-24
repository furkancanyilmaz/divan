"""Tek mesajın inceleme düğmesi görüşme geneline BAĞLANMAMALI.

Gerçek hata: `syncSchemaTurnMessageActionButton` ve
`schemaTurnActionLabel`, görüşme genelindeki geçmiş taramasının
(`turn_analysis.processing`) durumuna bakıyordu. O iş sıkışıp kalınca
(sağlayıcı hatası, zaman aşımı) HER mesajın düğmesi kalıcı olarak
kilitleniyor ve "Tur incelemesi sürüyor…" yazıp duruyordu.
"""

from support import HTTPTestCase, app


class TurnReviewLockTests(HTTPTestCase):
    def setUp(self):
        super().setUp()
        self.html = open("index.html", encoding="utf-8").read()

    def test_button_state_ignores_the_conversation_wide_scan(self):
        start = self.html.index("function syncSchemaTurnMessageActionButton(")
        body = self.html[start:start + 900]
        # Yalnız bu mesajın kendi durumu kilitler.
        self.assertIn("schemaTurnProcessingMessageIds.has(id)", body)
        self.assertNotIn("schemaTurnAnalysis().processing", body)

    def test_label_ignores_the_conversation_wide_scan(self):
        start = self.html.index("function schemaTurnActionLabel(")
        body = self.html[start:start + 600]
        self.assertNotIn("schemaTurnAnalysis().processing", body)
        # Sıkışan tarama artık her mesajda bu metni DÖNDÜREMEZ.
        # (Yorum satırında geçmesi sorun değil; `return` olmamalı.)
        self.assertNotIn("return 'Tur incelemesi sürüyor", body)

    def test_stuck_scan_still_reported_by_the_server(self):
        """Sunucu durumu bildirmeyi sürdürür; yalnız arayüz kilitlenmez.

        Geçmiş taraması sıkışsa bile kullanıcı tek tek mesajları
        inceleyebilmeli.
        """
        conv = self.conversation(therapist="young")
        with app.db() as connection:
            connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES(?,?,'running','t','t')",
                (app.LIVING_MAP_AUTOSCAN_JOB_KIND, conv))
            row = connection.execute(
                "SELECT * FROM conversations WHERE id=?", (conv,)).fetchone()
            payload = app.schema_turn_analysis_payload(connection, row)
        self.assertTrue(payload["processing"])
