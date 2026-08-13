# Mimari

Divan tek bir klinik çekirdek (`core/server.py`) etrafında kuruludur.
Bu belge, katmanları ve klinik döngünün nasıl zorlandığını anlatır.

## Katmanlar

```
┌──────────────────────────────────────────────────────────────┐
│ Platform katmanları (görünüm + etkileşim)                    │
│  macos/  SwiftUI        ios/   WKWebView + gömülü CPython    │
│  android/ WebView + Java       web  core/index.html          │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP (127.0.0.1, oturum anahtarlı)
┌──────────────────────────────▼───────────────────────────────┐
│ Klinik çekirdek — core/server.py (tek dosya, ~28k satır)     │
│                                                              │
│  1. Persona katmanı      usta sesi, yöntem, ders/tema        │
│  2. Klinik politika      tanı/ilaç/kriz/psikoz/mani sınırları│
│  3. Kanıt katmanı        yalnız kullanıcı onaylı kayıtlar    │
│  4. Sözleşmeler          kesinlik, pohpohlama, bağımlılık,   │
│                          "AI eşdeğerliği yok" kuralları      │
│  5. Onay kapısı          hafıza/formülasyon/harita girişleri │
│                                                              │
│  SQLite (freud.db) + seans sonrası iş hattı + eşitleme       │
└──────────────────────────────────────────────────────────────┘
```

Platform katmanları klinik karar **üretmez**: eşikler, onay zorunlulukları
ve güvenlik bekletmeleri çekirdekte durur; Swift/Kotlin yalnızca hazır
durumları gösterir.

## Persona ve kurgu sınırı

- **Vefat etmiş ustalar** tarihsel kişiliğiyle konuşur; biyografik
  göndermeler doğrulanabilir kamusal kaynaklarla sınırlıdır.
- **Yaşayan kişiler yer almaz.** Yaşayan ekollerin yöntemleri (şema
  terapi, DBT, ACT, EMDR, duygu odaklı terapi, motivasyonel görüşme,
  mentalizasyon…) kurgusal karakterlerle temsil edilir; karakterlerin
  kişiliği "gerçek bir kişiyi temsil etmez" koşuluyla yazılır ve gerçek
  benzerlik taşıyan görsel kullanılmaz.
- Bilimsel olguya dayalı atıflar (ör. "Dark Triad terimi 2002 çalışmasında
  adlandırıldı") kişi taklidi değildir; ders bağlamında korunur.

## Klinik döngü

1. **Gözlem** — seans içi damıtma; kanıt yalnız kullanıcının birebir
   sözleridir (alıntı olmadan sayım yapılmaz; aynı yorumun tekrarı yeni
   kanıt sayılmaz).
2. **Hipotez kartı** — dayandığı cümleler, alternatif açıklamalar, karşı
   örnekler ve "bunu çürütecek gözlem" gelen kutusunda sunulur.
3. **Kullanıcı kararı** — uyuyor / kısmen / yalnız şu bağlamda / uymuyor /
   emin değilim; ayrıca hafızaya al / özel tut / sil.
4. **Çalışma** — sandalye/imgelem protokolü: hazır oluş → açık onay →
   dur işareti → tek hedef → aşamalar → şimdi-burada → topraklanma →
   anında etki → 24 saat sonra gecikmiş etki kontrolü.
5. **Sonuç ve zarar kontrolü** — seans sonu nabzı + aşırı etkinleşme,
   uyku/işlev/güvenlik bozulması ve kontrol kaybı soruları.
6. **Onarım** — her mesajda "beni burada yanlış anladın"; daha doğru /
   kısmen / hâlâ değil / burada bırakalım.
7. **İnsana aktarım** — yalnız kullanıcının onayladığı bölümlerden oluşan
   tek sayfalık psikiyatrist hazırlık özeti.

Değişim, kullanıcının seçtiği üç ölçümle (belirti/işlev/hedef) 2-4 seans
aralığında izlenir; radar yalnız iyileşmeyi değil "güvenilir kötüleşme
olabilir" durumunu da gösterir.

## Veri akışı

- Sohbet → SSE akışı + dayanıklı kurtarma (`chat_requests` tablosu).
- Seans sonu → arka plan iş hattı: not, özet, formülasyon, Yaşayan Harita
  adayları, mektup, kavramlar. Hiçbiri kendiliğinden "olgunlaşmaz";
  hepsi kullanıcı onayı bekler.
- Modele bağlam girenler: profil (kullanıcı yazdı), onaylı notlar/anılar,
  kullanıcıca doğrulanan örüntüler, kabul edilmiş harita iddiaları.

## Yüzeyler / uç grupları

- Sohbet: `/api/new`, `/api/chat`, `/api/chat/retry|cancel|status`
- Gelen kutusu: `/api/inbox`, `/api/hypothesis/decision|memory|delete`
- Seans çalışması: `/api/session-pulse`, `/api/repair`,
  `/api/session-summary`, `/api/session-meta`
- Değişim radarı: `/api/measures`, `/api/checkin`, `/api/progress`
- Yaşantısal: `/api/chair-work`, `/api/chair-turn`,
  `/api/imagery-work`, `/api/imagery-turn`, `/api/work-followups`
- Aktarım: `/api/psych-prep`, `/api/psych-prep/summary|encrypted`,
  `/api/refer`
- Güvenlik: `/api/safety-plan`, `/api/safety-hold/review`
- Veri: `/api/backup`, `/api/restore`, `/api/export-json`,
  `/api/sync/*`, `/api/delete-all`

## Sürüm ve paketleme

- `core/server.py` → `VERSION` (çekirdek sürümü)
- `macos/Scripts/build_preview_zip.sh` → `DIVAN_NATIVE_VERSION` ile ZIP +
  SHA256 üretir; çekirdeği `../core`dan kopyalar (kişisel veri taraması
  yapar, DB/anahtar bulursa durur).
- iOS/Android paketleri aynı çekirdeği gömerek çalışır; Windows dağıtımı
  python.org gömülü çalışma zamanıyla (depoda tutulmaz) kurulur.

## Testler

- Çekirdek: `cd core && python3 -m unittest discover -s tests` (~790 test)
- macOS: `cd macos && swift test` (95 test)
- Klinik davranışı değiştiren her düzeltme testle birlikte gelir.
