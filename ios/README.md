# Divan iOS

Divan'ın bağımsız iPhone/iPad kabuğudur. SwiftUI uygulaması gömülü CPython
3.13 çalışma zamanını başlatır; mevcut sıfır-bağımlılık Python sunucusunu yalnız
`127.0.0.1` üzerinde rastgele bir portta açar ve arayüzü `WKWebView` içinde
gösterir.

Bu kaynak ağacı ortak Divan **2026.08.10.2** sürümüne karşılık gelir. iOS
paketinde Apple sürüm biçimiyle `2026.8.10` pazarlama sürümü ve önceki paketten
yüksek `5` derleme numarası kullanılır.

Arayüz, veritabanı, hafıza, eşitleme motoru ve HTTP sunucusu cihazın içindedir;
masaüstü Divan'ın açık kalmasına ihtiyaç duymaz. Model yanıtı için kullanıcı
Ayarlardan bir bulut sağlayıcısı seçebilir. LM Studio'nun `127.0.0.1` adresi
iPhone'un kendisini ifade ettiği için, telefonda ayrıca bir model sunucusu
çalışmıyorsa LM Studio bağımsız telefon seçeneği değildir.

## Mimari

- `Divan/Runtime`: CPython yaşam döngüsü, rastgele oturum anahtarı ve Keychain
  köprüsü. SwiftUI katmanı Python ayrıntılarını `PythonRuntimeBackend` arkasından
  görür.
- `Divan/Web`: yalnız yapılandırılmış loopback originine izin veren WebView ve
  main-frame/origin doğrulamalı native mesaj köprüsü.
- `DivanPython/ios_entry.py`: ortak `server.py` uygulamasını iOS içinde başlatır.
- `Scripts/prepare_python_bundle.sh`: her derlemede ortak Divan kaynaklarını
  kullanıcı verisi olmadan kopyalar; kaynakları ortak dosyalarla bayt bayt
  karşılaştırır, sync v2 ile DB/API anahtarı korumalarını denetler, ardından
  Python stdlib/paketlerini yerleştirir ve native uzantıları iOS frameworklerine
  dönüştürür.
- `Vendor/Python.xcframework`: cihaz ve simülatör CPython 3.13 dilimleri.

Kaynak paketine `freud.db`, yedekler veya masaüstündeki API anahtarları girmez.
Yeni iOS veritabanı Application Support altında ve dosya korumasıyla oluşturulur;
sağlayıcı sırları iOS Keychain'de tutulur. Divan veri klasörü sistem cihaz
yedeklerinden hariçtir; uygulama içi yedekler ayrıca tam dosya koruması alır.
Paylaşım için üretilen geçici dosyalar da tam korumalıdır ve işlem bitince silinir.

## İlk çalıştırma

1. Xcode'u bir kez açıp ilk kurulum bileşenlerini tamamlayın.
2. Simülatör kullanılacaksa Xcode > Settings > Components içinden bir iOS
   Simulator runtime kurun.
3. `Divan.xcodeproj` dosyasını açın ve `Divan` şemasını seçin.
4. Gerçek telefonda çalıştırmak için Signing & Capabilities bölümünde kendi
   Team'inizi seçin; gerekirse `PRODUCT_BUNDLE_IDENTIFIER` değerini benzersiz
   bir adla değiştirin.
5. iPhone'u bağlayıp güven verin ve telefonda Developer Mode'u açın; ardından
   Xcode'dan Run'a basın.

Komut satırında imzasız cihaz derlemesi:

```sh
xcodebuild -project Divan.xcodeproj \
  -scheme Divan \
  -configuration Debug \
  -destination 'generic/platform=iOS' \
  -derivedDataPath DerivedData \
  CODE_SIGNING_ALLOWED=NO build
```

Bu Mac'te iOS Simulator bileşeni kurulu değilse yalnız cihaz kodunu doğrulamak
için hedef doğrudan derlenebilir:

```sh
xcodebuild -project Divan.xcodeproj -target Divan \
  -configuration Release -sdk iphoneos \
  CODE_SIGNING_ALLOWED=NO \
  EXCLUDED_SOURCE_FILE_NAMES=Assets.xcassets \
  ASSETCATALOG_COMPILER_APPICON_NAME= \
  SYMROOT=Build-release OBJROOT=Build-release/Intermediates build
```

Sonuç paketi `Scripts/verify_bundle.sh` ile denetlenebilir. Bu denetim paket
sürümünü, ortak `server.py`/`index.html`/sync dosyalarının güncelliğini, sync v2
işaretini ve pakette DB ya da anahtar benzeri içerik bulunmadığını da doğrular.
İmzasız geliştirici IPA'sı `Scripts/package_unsigned_ipa.sh` ile
`dist/Divan-iOS-2026.08.10.2-Standalone-Unsigned.ipa` adına hazırlanır; bu IPA
kod doğrulaması içindir ve normal iPhone'a kurulmadan önce Apple hesabıyla
imzalanmalıdır.

TestFlight/dağıtım için ücretli Apple Developer üyeliği, App Store Connect
kaydı, benzersiz Bundle ID, dağıtım imzası ve güncel gizlilik metadatası gerekir.

## Güvenlik sınırları

- WebView yalnız `http(s)://localhost`, `127.0.0.1` veya `::1` tabanlı ve
  başlatılan endpoint ile aynı origin olan sayfalarda gezinir.
- Native köprü yalnız ana frame ve aynı origin mesajlarını kabul eder; payload
  boyutları sınırlıdır.
- Harici HTTP(S) bağlantılar WebView içine alınmaz, sistem tarayıcısına verilir.
- ATS genel ağ yüklemelerine açılmaz; yalnız yerel ağ istisnası tanımlıdır.

Apple Privacy Manifest uygulama ve gömülü Python frameworkleri için pakete
eklenmiştir. App Store öncesinde herkese açık gizlilik politikası adresi,
kalıcı veritabanı şifreleme, erişilebilirlik/klavye gerçek cihaz testleri ve
uygulama ikonunun nihai tasarımı ayrıca tamamlanmalıdır.
