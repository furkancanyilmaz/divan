# Divan

Ustalarla terapi ve ders: yerel çalışan, gizlilik öncelikli bir psikolojik
çalışma sistemi. Freud, Ferenczi, Jung gibi terapi ustaları ve
felsefecilerle konuşursunuz; seanslar SQLite'ta yerel kalır, API anahtarları
sizin cihazınızda tutulur.

Divan kendini "daha kesin yorum yapan bir AI" olarak değil, yorumlarından
şüphe edebilen bir çalışma sistemi olarak kurar: gözlem → sınanabilir
hipotez → **kullanıcı onayı** → küçük çalışma → sonuç ve zarar kontrolü →
onarım → gerekirse insana aktarım.

> Divan bir tıbbi cihaz değildir; tanı koymaz, ilaç önermez ve insan
> terapistin yerini aldığını iddia etmez. Acil durumlar için 112 veya en
> yakın acil servis.

## Kişiler ve kurgu sınırı

Vefat etmiş ustalar (Freud, Jung, Frankl, Lacan…) tarihsel kişiliğiyle
konuşur. **Hayatta olan hiçbir kişi kendi adı, biyografisi veya
fotoğrafıyla yer almaz** — Yalom, Young, Linehan, Hayes gibi yaşayan
ekollerin yöntemleri, açıkça kurgusal olduğu belirtilen özgün karakterlerle
temsil edilir (İlya Yalın, Kerem Genç, Meral Çizgi, Selim Yolsever…).
Kişilik hakları ve telifle çakışmamak için gerçek benzerlik taşıyan
görseller kullanılmaz.

## Depo düzeni (monorepo)

| Klasör | Nedir | Dil |
|---|---|---|
| [`core/`](core/) | **Tek klinik çekirdek.** Personalar, güvenlik, klinik döngü, API ve web arayüzü. Tüm platformlar buna bağlanır. | Python + HTML/JS |
| [`macos/`](macos/) | macOS 13+ SwiftUI uygulaması. Çekirdeği loopback üzerinden konuşturur; klinik karar üretmez. | Swift |
| [`ios/`](ios/) | iOS uygulaması (gömülü CPython + WKWebView köprüsü). | Swift/ObjC |
| [`android/`](android/) | Android APK projesi (WebView sarmalayıcı + gömülü çekirdek kopyası). | Java |
| [`windows/`](windows/) | Windows dağıtım başlatıcısı (kaynak; gömülü Python çalışma zamanı depoda tutulmaz). | Batch |

## Mimari — tek cümlede

**Klinik çekirdek bir kez yazıldı (Python); her platform ona bağlanıyor.**
Platform katmanları yalnız arayüzdür; persona, güvenlik kuralı veya klinik
karar üretmezler. Ayrıntı: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Hızlı başlangıç

Çekirdek tek başına (web arayüzü açılır):

```bash
cd core
python3 server.py            # tarayıcı otomatik açılır
python3 -m unittest discover -s tests    # test kümesi (790+)
```

macOS uygulaması:

```bash
cd macos
swift test
swift run Divan
```

Gereksinimler: Python 3.9+ (stdlib yeterli); macOS için Xcode/Swift 5.9+,
iOS için Xcode, Android için JDK + Android SDK.

## Gizlilik ve veri sınırı

- Veriler yereldir (`freud.db`); uygulama dışına yalnız sizin seçtiğiniz
  model sağlayıcısına sizin onayınızla mesaj akışı gider.
- API anahtarları kaynak kodda **yoktur**; uygulama içi Ayarlar'dan girilir,
  macOS'ta Anahtar Zinciri'nde saklanır.
- Hafızaya giren her kayıt kullanıcı onayından geçer; otomatik onay yoktur.
- Ayrıntı: [`SECURITY.md`](SECURITY.md).

## Lisans ve üçüncü taraf bileşenler

- Proje kodu: [CC0-1.0](LICENSE) — herkes istediği gibi kullanabilir;
  hiçbir koşul veya atıf zorunluluğu yoktur.
- Usta portreleri **depoda tutulmaz**; yalnızca uygun lisanslı kaynaklardan
  indiren araç vardır:
  [`core/tools/fetch_commons_portraits.py`](core/tools/fetch_commons_portraits.py).
- `qrcodegen.py` Project Nayuki (MIT). Ayrıntı:
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Katkı

Geliştirme kuralları ve katman sınırları:
[`CONTRIBUTING.md`](CONTRIBUTING.md) ve
[`macos/KATKI.md`](macos/KATKI.md).
