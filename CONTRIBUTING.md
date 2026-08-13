# Katkı rehberi

## Kod nerede yaşar

- **Klinik ve persona kararları yalnız `core/server.py`'dedir.** Bir kuralı
  platform katmanında (Swift/Java) değil, çekirdekte düzeltin; düzeltme
  bütün platformlarda geçerli olur.
- Platform kodları yalnız görünüm ve etkileşimdir; eşik, onay zorunluluğu
  veya güvenlik bekletmesi üretmezler.

## Katman sınırları (macOS)

- `Core/` — HTTP, süreç yönetimi, tel (wire) tipleri, domain modelleri
- `App/` — Core ile UI arasındaki köprü (veri kaynağı adaptörleri)
- `UI/` — yalnız görünüm ve etkileşim
- Wire tipleri UI'a sızmaz; klinik karar View'da olmaz.
- Ayrıntı: [`macos/KATKI.md`](macos/KATKI.md)

## Test kuralı

- Klinik davranışı değiştiren her düzeltme testle birlikte gelir:
  - Çekirdek: `cd core && python3 -m unittest discover -s tests`
  - macOS: `cd macos && swift test`
- Protokole yeni metot eklenince macOS test sahteleri de güncellenir.

## Yorum dili

- Klinik ve ürün kararları ("neden bu eşik?", "kullanıcı neyi onaylıyor?")
  **Türkçe** açıklanır.
- Platform/teknik ayrıntılar (SwiftUI/AppKit, eşzamanlılık, ağ) İngilizce.
- Yorum "ne"yi değil "neden"i anlatır; düzeltme yorumlarında eski yanlış
  davranış da yazılır.

## Persona sınırı

- Yaşayan kişiler uygulamaya alınmaz; yöntemleri kurgusal karakterlerle
  temsil edilir. Yeni karakter eklerken persona metnine "kurgusal" ve
  "gerçek bir kişiyi temsil etmezsin" koşulları eklenir; gerçek benzerlik
  taşıyan görsel kullanılmaz.

## Gizlilik

- Veritabanı, yedek, günlük, cihaz kimliği veya API anahtarı içeren hiçbir
  dosya depoya girmez (`.gitignore` ve paketleme betikleri bunu denetler).
- Portre görselleri depoya işlenmez; `core/tools/fetch_commons_portraits.py`
  ile, yalnız uygun lisanslı kaynaklardan indirilir.
