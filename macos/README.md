# Divan for macOS

Divan'ın macOS 13 ve sonrasına yönelik gerçek SwiftUI uygulamasıdır.
Windows, Android, iOS ve web arayüzünün kullandığı klinik/persona çekirdeğini
yeniden yazmaz. Native ekranlar güvenli bir rastgele loopback bağlantısı
üzerinden paketlenen ortak Python çekirdeğine bağlanır.

## Güvenli veri sınırı

- Varsayılan veri klasörü şimdilik
  `~/Library/Application Support/Divan Native Preview`; ürün adı yalnızca
  **Divan** olsa da önceki kurulumdaki veriler açık aktarım/eşitleme olmadan
  kendiliğinden açılmaz.
- Kararlı Divan'ın veritabanı otomatik okunmaz veya değiştirilmez.
- Sağlayıcı anahtarları bu kuruluma özel
  `com.furkancanyilmaz.divan.native-preview.provider-credentials` Keychain
  servisinde tutulur.
- Terminaldeki başka Divan API anahtarları veya sağlayıcı seçimi bu kuruluma
  miras bırakılmaz.
- Sunucu `PORT=0` ile işletim sisteminin seçtiği loopback portunda açılır;
  256 bitlik oturum anahtarı HttpOnly çereze çevrilmeden API kabul edilmez.
- Swift katmanı SQLite dosyasını doğrudan açmaz. Bütün yazılar ortak Python
  çekirdeğinin denenmiş işlem sınırlarından geçer.

## Geliştirici kullanımı

Gerekenler:

- macOS 13+
- Xcode/Swift 5.9+
- Python 3.9+ (`/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin` ve `PATH`
  güvenli biçimde taranır)

```text
swift test
swift run Divan
```

Kaynak geliştirme ağacında çalışırken çekirdek varsayılan olarak kardeş
`../core` klasöründen bulunur. Açık bir test çekirdeği için
`RuntimeConfiguration(coreDirectory:dataDirectory:pythonExecutable:)` kullanın.
Canlı kullanıcı DB'siyle geliştirme yapmayın.

## Native özellikler

- Ustalar içinde terapist/felsefeci sekmeleri, isim–ekol–yaklaşım araması,
  portreli native liste ve ayrıntı görünümü.
- Sohbet, arşiv, silme, mesaj sayfalama, dayanıklı arka plan yanıtı ve
  Return ile gönderme / Shift-Return ile yeni satır.
- Mesaj seçerek 1080×1920 Divan hikâyesi oluşturma, tema–yazı–saat seçenekleri,
  PNG kaydetme ve macOS paylaşım menüsü.
- Dinamik sandalye/parça çalışması, sınırlı yeniden ebeveynlik ve güvenli
  imgelem adımları.
- Kullanıcı incelemeli yaşayan harita ve aynı Wi-Fi üzerinden QR eşitleme.
- Klinik döngü v2: sınanabilir hipotez gelen kutusu (kanıt tarihi, karşı
  örnek, çürütme koşulu, "emin değilim", hafızaya al/özel tut/sil), seans
  sonu görüşme uyumu nabzı ve mesaj başına onarım ("Burada bırakalım" dahil),
  kullanıcının seçtiği üç ölçümle değişim/kötüleşme radarı, sandalye ve
  imgeleme için anında etki + 24 saatlik gecikmiş etki kontrolü, bölüm onaylı
  psikiyatrist aktarım özeti. Hafıza yalnız açık kullanıcı onayıyla oluşur.

## Mimari sınır

- `CoreRuntime`: Python süreci, özel dosya izinleri, kilit/metadata, günlük
  döndürme, güvenli kapanış ve sağlık doğrulaması.
- `APIClient`: sürümlü bootstrap, geriye uyumlu katalog/ayarlar, sohbet
  listesi/sayfalama, yazma işlemleri, oturumlu portre yükleme ve dayanıklı SSE
  sohbet kurtarma.
- `DivanService`: SwiftUI view-model katmanının bağımlı olduğu public sözleşme.
- `UI` ve `App`: yalnız native görünüm/etkileşim; klinik karar üretmez.

SSE ekran akışı koparsa model işi durdurulmaz. İstemci aynı `request_id` ile
`/api/chat-status` sorgulayarak tamamlanmış/başarısız/iptal durumuna kadar
toparlanır. Açık işlemin son durumu konuşma sayfasındaki `chat_request` alanında
da bulunur.

Portreler genel ağ istemcisiyle açılmaz. SwiftUI, `portraitData(url:)` üzerinden
aynı oturumlu istemciyi kullanır; yalnız aynı loopback kökenindeki
`/assets/portraits/` dosyaları, JPEG/PNG/WebP türleri ve en çok 10 MB kabul
edilir.

## Temiz kaynak hazırlama

```text
Scripts/prepare_core.sh
```

Yalnız şu dosyalar kopyalanır: `server.py`, `index.html`, eşitleme modülleri,
QR modülleri, `macos_keychain.py` ve portre kataloğu. DB, yedek, günlük,
cihaz kimliği, API anahtarı ve özel anahtar benzeri içerik bulunursa işlem
durur.

## ZIP paketi

```text
Scripts/build_preview_zip.sh
```

`dist/Divan-macOS-<sürüm>.zip` ve SHA-256 dosyası üretilir.
Paket ad-hoc imzalıdır; kullanıcı verisi içermez ve **DMG üretmez**. Pakette
ortak Python uygulama kaynakları bulunur; çalıştırılan Mac'te Python
3.9+ gerekir. Üretim sürümünde Developer ID, noterleme ve istersek universal
gömülü CPython ayrı dağıtım katmanı olarak eklenebilir.
