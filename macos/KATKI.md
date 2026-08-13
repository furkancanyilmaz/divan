# Divan macOS — kod düzeni ve yazım kuralları

Bu belge, kod tabanında zaten uygulanan ama yazılı olmayan kuralları
kayda geçirir. Amaç, sonraki değişikliklerin aynı çizgide kalması.

## Yorum dili

Kod tabanı iki dilli ve bu **kasıtlı**:

- **Türkçe** — klinik ve ürün kararları. "Neden bu eşik?", "kullanıcı
  neyi onaylıyor?", "hangi metin kullanıcıya görünür?" gibi sorular
  Türkçe yanıtlanır. Kullanıcıya görünen tüm metinler zaten Türkçedir.
- **İngilizce** — platform ve teknik ayrıntılar. SwiftUI/AppKit davranışı,
  eşzamanlılık, bellek, ağ katmanı.

Karar veremiyorsan şunu sor: *bu yorumu bir klinisyen okumalı mı, bir
Swift geliştiricisi mi?* Klinisyen ise Türkçe.

## Yorum ne anlatmalı

"Ne" değil **"neden"**. Kod zaten ne yaptığını söyler.

İyi:
```swift
// Reddedilen portre kataloğu asla bloke etmez. Baş harfler görünür
// kalır ve başarısız URL her render'da yeniden denenmez.
portraitFailures.insert(master.id)
```

Gereksiz:
```swift
// sayacı artır
count += 1
```

Bir hatayı düzeltiyorsan, yorumda **eski yanlış davranışı** da yaz —
aksi hâlde biri onu "sadeleştirme" adına geri getirir. Örnek:
`WorkspaceSafety` ve `DivanStrings` tanımlarına bakın.

## Katman sınırları

```
Core/     → HTTP, süreç yönetimi, tel (wire) tipleri, domain modelleri
App/      → Core ile UI arasındaki köprü (veri kaynağı adaptörleri)
UI/       → yalnız görünüm ve etkileşim
```

Kurallar:

- **Wire tipleri `internal` kalır.** UI, `…Wire` tiplerini asla görmez;
  `App/` katmanı onları UI modellerine çevirir.
- **Klinik karar View'da olmaz.** Yoğunluk eşiği, onay zorunluluğu,
  güvenlik bekletmesi gibi kurallar modelde/ViewModel'de durur; View
  yalnızca hazır bir `Bool` okur. Bkz. `WorkspaceSafety`.
  (Bu kural bir hatadan doğdu: eşik iki View'a elle yazılmıştı ve
  imgelem yolu sunucu sınırını hiç kontrol etmiyordu.)
- `AdvancedWorkspaceView` navigasyonu bilmez; çıkış yolu host uygulama
  tarafından `onExit` ile verilir.

## Paylaşılan metinler

Birden fazla yerde geçen kullanıcı metni `Core/DivanStrings.swift`
içine girer. Tek kullanımlık metin kendi View'ında kalabilir.

Gerekçe: aynı cümle elle tekrarlandığında sessizce sapıyor —
"Yanıt tamamlanamadı." yedi yerde vardı, birinde nokta eksikti.

## Dosya boyutu

Kesin bir sınır yok, ama **800 satırı aşan dosya bölünmeyi hak eder**.
Bakılacak şey satır sayısı değil, dosyanın kaç ayrı işi olduğudur.

Bölme yapılırken tipler değiştirilmez, yalnızca yerleşim değişir
(aynı modül içinde erişim etkilenmez). Örnek: `AdvancedAPIPayloads.swift`
(1214 satır, 53 tel tipi) alanlarına göre altı dosyaya ayrıldı.

Hâlâ büyük olanlar ve önerilen bölünme:

| Dosya | Satır | Öneri |
|---|---|---|
| `CoreAdvancedWorkspaceDataSource.swift` | 1415 | Chair / Imagery / Living / Sync extension'ları |
| `ChairWorkView.swift` | 1292 | `ChairClosureSheet` + bileşenler ayrı dosyaya |
| `ConversationViews.swift` | 1281 | Library / Chat / Bubble / ScrollObserver |
| `DivanViewModel.swift` | 1113 | Ayarlar ve portre yükleme ayrı sınıflara |

## Test

`swift test` — 81 test. Klinik davranışı değiştiren her düzeltme
**test ile birlikte** gelir (`WorkspaceSafetyTests` örnektir: iki yolun
aynı sözleşmeye uyduğunu 100 kombinasyonda doğrular).

Test sahteleri (`RootConversationDataSource` vb.) protokolü uygular;
protokole yeni metot eklerken üç sahteyi de güncellemek gerekir.

## Paketleme

```
Scripts/build_preview_zip.sh      # dist/Divan-macOS-<sürüm>.zip + SHA256
```

`prepare_core.sh` çekirdeği kopyalarken veritabanı, yedek, günlük,
cihaz kimliği veya anahtar benzeri içerik bulursa **durur**.

Bilinen eksik: `verify_package.sh` gizli anahtar taramasında `rg`
kullanıyor; `rg` kurulu değilse bu kontrol sessizce atlanır. Elle
karşılığı:

```bash
grep -rEl 'sk-(proj-)?[A-Za-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY-----' \
  --include='*.py' --include='*.html' --include='*.json' \
  Divan.app/Contents/Resources/Divan
```
