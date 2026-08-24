from pathlib import Path
import unittest


PROJECT_DIR = Path(__file__).resolve().parents[1]


class LivingMapUISourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")

    def test_desktop_and_mobile_entries_expose_pending_count(self):
        self.assertIn('id="livingMapBtn"', self.html)
        self.assertIn('id="mobileLivingMapBtn"', self.html)
        self.assertIn('id="livingMapBadge"', self.html)
        self.assertIn('id="mobileLivingMapBadge"', self.html)
        self.assertIn("setLivingMapPendingCount", self.html)

    def test_review_queue_never_treats_silence_as_consent(self):
        self.assertIn('id="livingMapPendingCards"', self.html)
        self.assertIn("Sessizlik onay", self.html)
        self.assertIn("Uyuyor','confirm'", self.html)
        self.assertIn("Kısmen','partial'", self.html)
        self.assertIn("Yalnız şu bağlamda','context'", self.html)
        self.assertIn("pendingEvidence?'Yeni kanıt uymuyor':'Uymuyor'",
                      self.html)
        self.assertIn("pendingEvidence?item.rejectAction:'reject'", self.html)
        self.assertIn("Artık geçerli değil','retire'", self.html)

    def test_new_evidence_is_explained_without_rejecting_the_old_claim(self):
        self.assertIn("raw.pending_evidence_count", self.html)
        self.assertIn("data.pending_evidence_reviews", self.html)
        self.assertIn("raw.reject_action", self.html)
        self.assertIn("Yeni kanıt incelemesi", self.html)
        self.assertIn("siz karar verene kadar bu notu güçlendirmez", self.html)
        self.assertIn("Yeni kanıt uyuyor", self.html)
        self.assertIn("Yeni kanıt uymuyor", self.html)
        self.assertIn("önceki çalışma notu korundu", self.html)
        self.assertIn("reject_evidence:'Yeni kanıt kullanılmayacak", self.html)
        self.assertIn("row.review_status==='pending'", self.html)
        self.assertIn("pending.textContent='Onay bekliyor'", self.html)
        self.assertIn("if(!pendingEvidence)actions.append", self.html)

    def test_formulation_and_private_controls_are_visible(self):
        self.assertIn("Formülasyon taslağı", self.html)
        self.assertIn("kalıcı haritada ya da", self.html)
        self.assertIn("Özel tut / modelden çıkar", self.html)
        self.assertIn("excluded_from_model", self.html)

    def test_evidence_view_only_renders_user_authored_sources(self):
        self.assertIn('id="livingMapDetailOverlay"', self.html)
        self.assertIn("livingMapEvidenceRows", self.html)
        self.assertIn("'user','client','kullanıcı','danışan'", self.html)
        self.assertIn("Asistan yanıtları ve eski model özetleri", self.html)

    def test_api_contract_is_central_and_mobile_modal_scrolls(self):
        self.assertIn("const LIVING_MAP_API = Object.freeze", self.html)
        self.assertIn("overview:'/api/living-map'", self.html)
        self.assertIn("review:'/api/living-map/review'", self.html)
        self.assertIn("detail:'/api/living-map/detail'", self.html)
        self.assertIn(".livingMapScroll{", self.html)
        self.assertIn("overscroll-behavior-y:contain", self.html)
        self.assertIn("height:var(--mobile-vvh,100dvh)", self.html)

    def test_backend_cycle_fields_and_artifact_identity_are_supported(self):
        for field in (
            "trigger_text",
            "response_text",
            "short_term_effect",
            "long_term_effect",
            "need_text",
            "counterexample_text",
            "context_label",
            "review_note",
        ):
            self.assertIn(field, self.html)
        self.assertIn("artifact_type:item.type", self.html)
        self.assertIn("public_id:item.publicId||item.id", self.html)
        self.assertIn("contextual:'Bağlama özgü'", self.html)

    def test_historical_scan_discloses_full_model_payload_and_recovers_button(self):
        self.assertIn("'tarihleri ve kayıt kimliklerinin; konuşulan usta", self.html)
        self.assertIn("'ustaya ait mevcut Yaşayan Harita notlarının '", self.html)
        self.assertIn("button.disabled=!$('livingMapHistoryConsentInput').checked", self.html)

    def test_historical_scan_waits_for_busy_work_and_refreshes_badge(self):
        self.assertIn('waitingForOtherWork', self.html)
        self.assertIn('refreshLivingMapBadge();', self.html)
        self.assertIn("loadLivingMap({loading:false});", self.html)

    def test_historical_scan_is_turn_based_and_skips_unsafe_partial_content(self):
        for field in (
                "eligible_turn_count", "analyzed_turn_count",
                "remaining_turn_count", "failed_turn_count",
                "safety_skipped_turn_count"):
            self.assertIn(field, self.html)
        for copy in (
                "Her tamamlanmış kullanıcı–usta mesaj çifti ayrı incelenir",
                "yarım yanıtlar ve özel/modelden çıkarılmış turlar atlanır",
                "tur tur gönderileceğini",
                "Geçmiş turları incelemeyi başlat"):
            self.assertIn(copy, self.html)
        self.assertNotIn("Her görüşme ayrı incelenir", self.html)
        self.assertNotIn("görüşme görüşme gönderileceğini", self.html)

    def test_active_order_is_applied_to_desktop_and_mobile_lists(self):
        self.assertIn('function orderActiveConversationRows(rows)', self.html)
        self.assertIn(
            "const orderedRows=mobileConversationView==='archived'\n"
            "      ?[...(Array.isArray(rows)?rows:[])]:"
            "orderActiveConversationRows(rows);",
            self.html)
        self.assertIn('latestMobileConversationRows(orderedRows)', self.html)
        self.assertIn(
            "const orderedRows=requestedView==='archived'\n    ?rows:orderActiveConversationRows(rows);",
            self.html)


if __name__ == "__main__":
    unittest.main()
