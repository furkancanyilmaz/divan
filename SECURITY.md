# Güvenlik

Divan yerel çalışan bir uygulamadır; bu belge veri sınırlarını ve güvenlik
sözleşmesini özetler.

## Veriler nerede durur

- SQLite veritabanı (`freud.db`) yalnız cihazdadır; yedekler de öyle.
- Depoda veri yoktur: veritabanı, yedekler, günlükler ve cihaz kimliği
  dosyaları `.gitignore` ile dışarıdadır.
- API anahtarları kaynak kodda tutulmaz; uygulama içi Ayarlar'dan girilir,
  macOS'ta Anahtar Zinciri servisinde saklanır.

## Ağ sınırı

- Çekirdek yalnız loopback (127.0.0.1) üzerinde, işletim sisteminin
  seçtiği rastgele portta dinler.
- API çağrıları 256 bitlik oturum anahtarıyla korunur (HttpOnly çerez).
- Dışa açılan tek akış: kullanıcının seçtiği LLM sağlayıcısına, onun
  onayıyla giden istekler.

## Klinik güvenlik sözleşmesi

- **Onaylı hafıza:** modele bağlam giren her kayıt (not, anı, örüntü,
  harita iddiası) kullanıcı onayından geçer; otomatik onay yoktur.
- **Güvenlik bekletmesi:** kriz sinyalinde persona ve yorum modu kapanır;
  kullanıcının kendi güvenlik planı ve insan kaynakları öne çıkar.
- **Zarar kontrolü:** seans sonunda aşırı etkinleşme, uyku/işlev/güvenlik
  bozulması ve uygulamaya dönme kontrolü sorulur; radar kötüleşmeyi de
  gösterir.
- **AI sınırı:** AI eşdeğerlik, bağımlılık üreten yakınlık veya "kesinlik"
  iddiası prompt sözleşmeleriyle yasaklanır.
- **Kriz:** pozitif tarama sohbetin kendiliğinden devamı için yeterli
  değildir; uygulama insan kaynaklarına (112, acil servis, güvenilen
  kişiler) yönlendirir. Güvenlik sözleşmeleri ("zarar vermeyeceğine söz
  ver") kullanılmaz.

## Güvenlik açığı bildirimi

Bir açık bulursanız lütfen önce e-posta ile bildirin; düzeltme yayımlanana
kadar ayrıntıyı herkese açık paylaşmayın.
