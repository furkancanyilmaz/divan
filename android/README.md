# Divan Android

Divan’ın mevcut Python/SQLite uygulamasını tek simgeli bir Android
uygulamasında çalıştıran özel APK projesidir.

## Telefonda kullanım

1. `Divan-Android-2026.08.10.2.apk` dosyasını telefona gönderin.
2. Telefonda dosyaya dokunun. Android isterse kullandığınız Dosyalar
   uygulamasına “bilinmeyen uygulama yükleme” izni verin.
3. **Yükle**, ardından **Aç** seçeneğine dokunun.
4. İlk açılışta Python çalışma alanı hazırlanırken yaklaşık 10–30 saniye
   bekleyin. Sonraki açılışlar daha hızlıdır.
5. Divan’ın ilk bilgilendirmesini okuyup Ayarlar’dan DeepSeek, OpenAI veya
   Claude anahtarınızı girin.

Eski bilgisayar kayıtlarını taşımak için bilgisayardaki **Yedek** düğmesiyle
SQLite yedeği alın, dosyayı güvenli biçimde telefona gönderin ve Android
Divan’da **Ayarlar → Yedeği geri yükle** yolunu kullanın.

## Android’e özgü güvenlik

- HTTP sunucusu yalnız `127.0.0.1` üzerinde rastgele bir portta çalışır.
- Her uygulama açılışında 256 bitlik yeni bir oturum belirteci üretilir.
  API istekleri bu belirtecin HttpOnly çerezini taşımadan kabul edilmez.
- Görüşme veritabanı Android’in `no_backup` özel uygulama alanındadır.
- Sağlayıcı API anahtarları SQLite’a yazılmaz. Android Keystore içindeki
  dışarı aktarılamayan AES anahtarıyla şifrelenir ve kayıt tamamlanmadan
  Ayarlar isteği başarılı sayılmaz.
- Android’in son uygulamalar görünümünde konuşma önizlemesi gösterilmez;
  bilinçli ekran görüntüsü alma ve Divan hikâyesi paylaşma çalışmaya devam eder.
- Geri hareketi uygulamayı sonlandırmak yerine arka plana taşır. Kabul edilmiş
  yanıtlar Android'in sistem iş zamanlayıcısına da kaydedilir; bu pencere yerel
  Python kuyruğunu canlı tutar ve süreç yarıda kesilirse işi yeniden çalıştırır.
  Kalıcı bir foreground-service bildirimi kullanılmaz. Asıl istek ve sonuç
  SQLite'taki tek kalıcı iş kaydından yürüdüğü için yeniden çalışma ikinci bir
  kullanıcı mesajı veya paralel sağlayıcı isteği oluşturmaz.
- WebView'in ayrı görüntü süreci Android tarafından kapatılırsa uygulamanın
  tamamı çökmek yerine sohbet ekranı yeniden kurulur; kalıcı mesaj ve iş
  kayıtları aynı yerel oturumdan geri yüklenir.
- Ayarlar’daki “İşlem tamamlandığında nötr bildirim” seçeneği varsayılan olarak
  kapalıdır. Açılır ve Android bildirim izni verilirse, uygulama görünür değilken
  işlem tamamlandığında içerik göstermeyen tek bir bildirim üretir.
- Kalıcı bildirim gerektiren bir foreground service kullanılmaz. Sistem işi
  yalnız yanıt sürerken kısa yürütme pencereleri alır; kullanıcı uygulamayı
  zorla durdurursa Android'in normal güvenlik kuralı gereği sonraki açılışa
  kadar hiçbir arka plan bileşeni çalışmaz.
- Uygulamanın Android bulut yedeği ve cihazdan cihaza otomatik veri aktarımı
  kapalıdır. Kullanıcı yalnız açıkça indirdiği Divan yedeğini taşır.
- WebView yalnız Divan’ın kendi loopback adresini yükler. İnternet
  bağlantıları telefonun normal tarayıcısında açılır.
- APK’nın içinde kullanıcı veritabanı veya API anahtarı bulunmaz.

Bulut modeli seçildiğinde mesaj ve seçilmiş bağlam yanıt üretimi için ilgili
sağlayıcıya gönderilir. Tamamen çevrimdışı model kullanmak için aynı Android
telefonda ayrıca OpenAI uyumlu bir yerel model sunucusu gerekir.

## Geliştirici derlemesi

Gerekenler:

- JDK 17
- Android SDK 36
- Android Gradle Plugin 8.13.2 / Gradle 8.13
- Chaquopy 17.0 / Python 3.10 (32 ve 64 bit Android uyumu)
- Tek APK içinde `arm64-v8a` ve `armeabi-v7a` telefon desteği

Güncel `../core/server.py`, `index.html`, eşitleme modülleri ve portre
varlıkları her derlemeden önce `syncDivanSources` göreviyle pakete kopyalanır.
Ardından `verifyDivanEmbedding`, ortak kaynaklarla gömülü kopyaları bayt bayt
karşılaştırır, eşitleme protokolünün v2 olduğunu doğrular ve kullanıcı
veritabanı, API anahtarı veya özel anahtar benzeri bir içerik bulursa derlemeyi
durdurur. `freud.db` hiçbir zaman kopyalanmaz.

```text
./gradlew clean assembleDebug
./gradlew assembleRelease
```

Çıktılar:

```text
app/build/outputs/apk/debug/app-debug.apk
app/build/outputs/apk/release/app-release.apk
```

Release APK bu Mac’in kişisel imza anahtarıyla imzalanır. Sonraki sürümlerin
mevcut uygulamanın üstüne kurulabilmesi için aynı imza anahtarının korunması
gerekir. Bu yapı Google Play yayını değil, kişisel doğrudan kurulum içindir.

Bu kaynak ağacının sürümü **2026.08.10.2**’dir (`versionCode 2026081002`).
