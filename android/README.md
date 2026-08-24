# Divan Android

Divan’ın mevcut Python/SQLite uygulamasını tek simgeli bir Android
uygulamasında çalıştıran özel APK projesidir.

## Telefonda kullanım

1. `Divan-Android-2026.08.22.15.apk` dosyasını telefona gönderin.
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

## Mobil görünüm

- Ana sayfanın başlığı ve konuşma listesi aynı düz renktedir; başlıkta yalnız
  minimal Divan simgesi ile küçük `divan` adı bulunur. Sohbetler, Ustalar ve
  Araçlar ekranın altındaki tanıdık mobil gezinmeyle açılır.
- Ana listede her kişi yalnız bir güncel satırla görünür. Eski seanslar kişi
  sohbetindeki **Sohbet geçmişi** sayfasındadır. Sabitlenen kişi satırı ayrı
  renge boyanmaz; yalnız sırası ve küçük sabit simgesi değişir.
- Usta mesajı sağa çekilerek alıntılı yanıt başlatılabilir. Aynı işlem
  TalkBack için mesaj eylemlerindeki **Yanıtla** düğmesiyle de yapılabilir.
- Sohbet başlığındaki usta portresine veya adına dokunulduğunda, yalnız
  yayımlanmış katalog bilgisinden oluşturulan kısa **Usta Profili** açılır.
  Profil; yaşam tarihlerini, temel görüşleri, yöntemleri ve AI canlandırması
  sınırını gösterir; konuşma ya da kullanıcı verisini bu sayfaya taşımaz.
- **Ayarlar ve araçlar** ayrı, kaydırılabilir bir mobil sayfadır; eski yan
  paneldeki defter, hafıza, ilerleme, çalışma ve veri araçlarının tamamı
  burada korunur. Sağ kenardan çekerek panel açma davranışı kaldırılmıştır.
- Konuşmaları seçme modunda bir veya birden fazla güncel sohbet atomik olarak
  sabitlenebilir. Sabitlenenler açık/bitmiş sırasını bozmadan kendi bölümünün
  üstüne gelir; arşivlenen konuşmanın sabiti otomatik kalkar.
- Mobilde **Beyaz**, **Sarı kâğıt** ve **Karanlık** olmak üzere üç düz tema
  bulunur; degrade yüzey kullanılmaz. Sistem çubukları seçilen temayla aynı
  paleti kullanır. Sohbet alanında düz, noktalı, çizgili veya yalnız cihazda
  saklanan kişisel JPEG/PNG/WebP arka plan seçilebilir. Metin boyutu %80–200
  arasında ayarlanabilir. Ana dokunma hedefleri en az 44–48 dp'dir.

## Yapılandırılmış çalışma modülleri

- **TUS Çalışma**, açık ADHD Koçu görüşmesinde **+ → TUS Çalışma** ile açılan
  doğal bir sohbet modudur; ayrı bir çalışma alanına geçmez. Koç ders, konu
  okuma alanı, soru alanı, kullanılabilir süre ve başlama güçlüğünü sırayla
  sohbet balonlarında sorar; kullanıcının yanıtları da aynı konuşmada balon
  olarak kalır. Yalnız uzun ders ve konu listeleri küçük bir seçim penceresi
  (popup) olarak açılabilir. Plan güncel adımı öne çıkarır ve gelecekteki
  adımları kapalı tutar.
  TümTUS’tan paketlenen katalog yalnız ders/alan adları ve sayısal adetler
  içerir; ham soru, cümle, seçenek, yanıt veya açıklama APK’ya alınmaz. Filtre
  sonuç vermediğinde arama taslağı korunur ve kullanıcı **Tümünü göster** ile
  listeye dönebilir.
- **ADHD Ritimleri**, tek seferlik hatırlatmanın yanında haftalık ve kullanıcı
  seçimiyle ilerleyen küçük alışkanlık deneyleri sunar. Kullanıcı bir ritmi
  hemen başlatabilir, açıkça isterse belirli bir zamana planlayabilir ve sonucu
  **Tamamlandı**, **Kısmen** veya **Bugün değil** olarak kaydedebilir. Seri,
  ceza, utandırma veya otomatik hedef artırma kullanılmaz.
- **Dış Beyin Defteri**, serbest yazı ile takılma noktası ve sonraki görünür
  hareketi kaydetmek için ayrı bir alandır. Defter girdileri varsayılan olarak
  hassas ve özeldir; ancak kullanıcı ayrıca paylaşmayı seçer ve hassas
  işaretini kaldırırsa koç bağlamına sınırlı biçimde girer. Defter acil olarak
  izlenen bir kanal değildir.
- **Şema Terapi Yolu**, yalnız ilk adayın altındaki kısa **Evet/Hayır**
  seçimiyle başlar. Evet’ten sonra ayrı kart, puanlama, yöntem seçimi veya
  şema kontrol düğmesi gösterilmez; çalışma sıradan sohbet balonlarında ilerler.
  Kerem somut sahnede kişi, yer, mesafe, destek, güç dengesi veya çıkış
  olanağından yalnız birini varsayımsal olarak değiştirerek asıl tetikleyeni
  araştırır, yöntemi terapist olarak kendisi seçer ve kökeni kısa tek soruluk
  yaş–yer–olay–deneyim–ihtiyaç sırasıyla konuşur. Teknik, Sağlıklı Yetişkin,
  çevreyi yeniden yazma, bugüne taşıma, isteğe bağlı pratik ve kapanış yine
  doğal mesajlarla ilerler. Duraklatma, bitirme, geri dönme ve şimdiye dönme
  yalnız kullanıcının yazdığı doğal komutlardır.
- Bu modüller tanı veya tedavi sonucu iddiası değildir; kullanıcının kendi
  gözlemlerini yapılandırmasına ve gerçek klinik görüşmeye hazırlanmasına yardım
  eden, duraklatılabilir çalışma alanlarıdır.
- Eşitleme protokolü v8, ADHD ritim tanımlarını, yalnız tamamlanmış çalışma
  olaylarını ve Şema Path v5’in dar ortak devam durumunu taşıyabilir. Özel
  prompt planı/sonucu, kontrol noktası iç ayrıntıları, köken/değişken kayıtları
  ve teknik konuşma dökümleri cihazda kalır. Defter metni ancak kullanıcı
  açıkça koçla paylaşmışsa ve kayıt hassas değilse eşitlenir. Hatırlatıcı,
  alarm, iş kuyruğu ve teslim durumu da cihazda kalır; böylece iki cihaz aynı
  bildirimi üretmez.
- Şema modu tercihi diğer cihaza taşınabilir; ancak yeni cihaz, kendi seçili
  sağlayıcısı ve modeli için ayrıca açık kullanıcı onayı almadan hiçbir şema
  incelemesi başlatmaz. Şema Yolu ve Yaşayan Harita kayıtları ise bundan ayrı
  olan **Şema ve Yaşayan Harita çalışmalarını eşitle** seçimi açılmadıkça bu
  cihazda kalır. Bu seçim her cihazda ayrıca doğrulanır. Aynı klinik kayıt iki
  cihazda eşzamanlı değişirse içerik karşılaştırılmadan hangi cihazdaki sürümün
  tutulacağı kullanıcıya sorulur; normal konuşmalar en yeni sürümle otomatik
  birleşmeye devam eder.
- v8 eşleştirmesi başlamadan önce iki cihaz da
  `schema_checkpoint_v1` ve `schema_path_chat_v5` yeteneklerini karşılıklı,
  tam olarak doğrular. Destek yoksa hiçbir konuşma kaydı, eşitleme imleci veya
  klinik kayıt aktarılmaz; iki uygulama da güncellendikten sonra yeni QR
  oluşturulmalıdır. v7 ve daha eski uygulamalar v8 verisi alamaz. Alıcı cihaz
  özel Şema geçmişini uydurmaz: ortak yol güvenli bir kontrol sınırında
  duraklatılır; kullanıcı doğal olarak **Devam** yazdığında bu cihazdaki model
  sağlayıcısından yeni, kalıcı bir Kerem sorusu üretilir.
- Tamamlanmış bir kullanıcı–usta dönüşü, iki mesajda aynı olan içeriksiz
  `turn_pair_public_id` ile kanıtlanır. Yerel uygulama bu kimliği yalnız kalıcı,
  tamamlanmış sohbet isteğinden üretir; istek kimliği, sağlayıcı ve iş kaydı
  eşitlenmez. Karşı cihaz bu alanı ancak v8 kimlik doğrulaması ve yukarıdaki
  capability kapısı geçen eşleşmiş cihazın beyanı olarak kabul eder. Bu güven
  sınırı, eşleşmiş cihazın mesaj içeriğini kötü niyetle üretmesini ayrıca
  kanıtlamaz. Eski pairsiz kayıt yalnız doğrudan nedensel sonraki revizyonda
  bir kez geçerli kimlik kazanabilir; dolu kimlik daha sonra değiştirilemez ya
  da temizlenemez ve aynı kimlikte aynı rol iki kez bulunamaz.

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
- Ayarlar’daki **“Yanıt hazır olduğunda bildir”** seçeneği varsayılan olarak
  kapalıdır. Açılır ve Android bildirim izni verilirse, uygulama görünür değilken
  yalnız `Divan — Yanıtınız hazır` biçiminde nötr bildirim üretir.
- **Kişi ve yanıt önizlemesi** ayrı ve varsayılanı kapalı bir tercihtir. Açık
  olsa bile kullanıcı mesajı ve konuşma geçmişi bildirime yazılmaz; yalnız son
  tamamlanmış AI yanıtı Android'in gerçek `MessagingStyle` konuşma görünümüyle
  gösterilebilir. Stil içindeki `Siz` kişisi uygulama kullanıcısıdır; mesajın
  göndereni `Usta adı · AI canlandırması` olarak işaretlenmiş bot kişidir.
  Böylece Android mesajı doğru kişiyle ilişkilendirir ve canlandırmayı gerçek
  insan sanmaz. Markdown/HTML işaretleri ve tıklanabilir span'ler kaldırılır;
  linkin yalnız görünen adı kalır. Android/NotificationCompat'in 5.120 UTF-16
  birimlik Binder sınırına güvenli pay bırakmak için 5.000 karakter platform
  tavanıdır; daha uzun yanıtta bildirim açıkça tam metin için Divan'ı açmaya
  yönlendirir. Uygulama PIN'i, misafir kapsamı veya güvenlik tutuşu varsa
  önizleme sunucu tarafında nötre düşürülür.
- Zengin bildirim her sohbet için tam konuşma kimliğini taşıyan ayrı
  `(tag,id)` çifti kullanır; hash/modulo çakışması başka ustanın bildirimini
  ezemez. Android 7.1 ve sonrasında conversation shortcut, Android 10 ve
  sonrasında locus bağı kurulur. Birden çok sohbet sessiz, içeriksiz bir Divan
  özeti altında gruplanır; asıl yeni child mesaj normal mesaj önceliğiyle
  uyarır. Android 7.0'da shortcut/locus yoktur fakat `MessagingStyle`,
  gruplama, doğru sohbete açılış ve doğrudan yanıt compat katmanında çalışır.
  Android 13 ve sonrasında sistem bildirim izni ayrıca zorunludur.
- **Bildirimden kısa yanıt** üçüncü, bağımsız ve varsayılanı kapalı tercihtir.
  Yalnız ana profilde, uygulama PIN'i yokken ve bildirimin bağlandığı son
  asistan mesajı hâlâ güncelse görünür. Android RemoteInput alıcısı metni
  modele veya Python sunucusuna göndermez: sekiz buçuk saniyelik receiver
  penceresinde tam zarfı ayrı bir Android Keystore AES-GCM anahtarıyla
  şifreleyip `no_backup` alanındaki atomik native outbox'a `fsync` eder.
  Persisted JobService bunu aynı idempotent kimlikle SQLite sohbet kuyruğuna
  aktarır; ağ/cold-start/5xx kesintisinde ciphertext ve artan aralıklı sistem
  işi kalır. Kesin kabulden veya terminal 4xx reddinden sonra outbox kaydı
  silinir. Boot, paket güncellemesi ve sonraki uygulama açılışı yarım kalmış
  kayıtları yeniden planlar. PIN, misafir modu, güvenlik tutuşu,
  kapanmış/arşivlenmiş görüşme ve bayat bildirim POST anında yeniden reddedilir.
- Önizleme, bildirimden yanıt veya tamamlanma bildirimi kapatıldığında; yeni
  PIN kurulduğunda; uygulama kilit, misafir veya güvenlik tutuşuna geçtiğinde
  Divan'ın o anda tepside gösterdiği bildirimler paket sınırları içinde topluca
  kaldırılır. Bu temizlik şifreli, henüz gönderilmemiş yanıt outbox'ını silmez.
  “Yanıt hazırlanıyor” durumu ayrıca görüşme ve idempotent istek kimliğiyle
  eşleştirilir; tamamlandı/başarısız/iptal sonuçlarında Android 7.x dahil kesin
  kapanır ve aynı görüşmenin daha yeni isteğine dokunmaz.
- Bildirimlerde yapay bir **Okundu** eylemi yoktur. Android bildiriminin
  silinmesi veya açılması, sohbet balonunun gerçekten okunmuş olduğunu güvenle
  kanıtlamaz; mevcut yerel şemada cihazlar arası, kalıcı ve idempotent bir okuma
  cursor'ı bulunmaz. Yalnız tepsiyi kapatan bir düğmeye “Okundu” demek yanlış
  okundu durumu yaratacağından, böyle bir sözleşme eklenene kadar bildirim
  dokunuşu yalnız doğru sohbeti açar.
- Görev hatırlatıcıları model/persona metnini kilit ekranına taşımaz. Görüşmeye
  bağlı, önceden tamamlanmış AI süre-sonu mesajı alarm anında yerel ve
  içeriksiz bir API çağrısıyla ilgili sohbete tam bir kez yazılır; bildirim
  aynı mesaj kimliğine bağlanır. Üretim sürüyorsa kısmi içerik gösterilmez ve
  kalıcı alarm kaydı artan aralıklarla yeniden dener. Üretim başarısızsa veya
  görüşmesiz basit bir görevse assistant mesajı uydurulmaz; yalnız nötr
  `Bir görev hatırlatıcınız var` bildirimi kullanılır. Uygulama yalnız açık bir
  “hatırlat / alarm kur / zamanla” isteğini sohbetten otomatik hatırlatıcıya
  dönüştürür. Güvenli ve açık önizleme izni bulunan AI süre-sonu mesajı sıradan
  alarm gibi değil, aynı sohbetin `MessagingStyle` child bildirimi olarak
  görünür ve aynı güvenli doğrudan-yanıt yolunu kullanır. Görüşmesiz veya
  redakte edilmiş görev kişi/shortcut/RemoteInput taşımayan `REMINDER`
  kategorisinde kalır.
- Kalıcı bildirim gerektiren bir foreground service kullanılmaz. Sistem işi
  yalnız yanıt sürerken kısa yürütme pencereleri alır; kullanıcı uygulamayı
  zorla durdurursa Android'in normal güvenlik kuralı gereği sonraki açılışa
  kadar hiçbir arka plan bileşeni çalışmaz.
- Uygulamanın Android bulut yedeği ve cihazdan cihaza otomatik veri aktarımı
  kapalıdır. Kullanıcı yalnız açıkça indirdiği Divan yedeğini taşır.
- WebView yalnız Divan’ın kendi loopback adresini yükler. İnternet
  bağlantıları telefonun normal tarayıcısında açılır.
- APK’nın içinde kullanıcı veritabanı veya API anahtarı bulunmaz.

### Bildirim köprüsü ve yerel JSON sözleşmesi

Mobil web katmanı Android köprüsünde şu yöntemleri kullanır:

```text
notificationInlineReplyEnabled() -> boolean
notificationInlineReplyAvailable() -> boolean
setNotificationInlineReplyEnabled(boolean) -> void
```

`notificationInlineReplyEnabled` kayıtlı ve etkin tercihi; `Available` ise
sunucunun anlık, içeriksiz PIN/kapsam kararını döndürür. Bunlar güvenlik sınırı
değildir: her bildirim `reply_allowed` ile oluşturulur ve kabul endpoint'i
aynı politikayı tekrar doğrular.

```text
GET  /api/notification-reply-capability
     -> {allowed, pin_enabled, scope}
GET  /api/notification-contexts?...&allow_preview=0|1
     -> preview tercihi ve PIN/kapsam/güvenlik birlikte uygunsa tam assistant
        content; aksi durumda content="", preview_allowed=false
POST /api/notification-reply
     <- {conversation_id, message, request_id, source_id, reply_to}
     -> {accepted, duplicate, request_id, job_id, status,
         reply_to, source_id}

POST /api/reminders/deliver
     <- {id, allow_preview}
     -> {state, conversation_id, message_id, source_id,
         reply_allowed, preview_allowed, master_name, revealed_now, preview?}
POST /api/reminders/deliver-ack
     <- {id, message_id, source_id}
     -> {ok, id}
```

`request_id`, tekrar eden broadcast'i aynı sohbet isteğine bağlar.
`source_id + reply_to`, yanıtın doğru ve güncel assistant mesajına ait
olduğunu kanıtlar. Hatırlatıcı teslim/ack uçları yalnız loopback üzerindeki
gömülü oturum çereziyle çalışır. Görev, kullanıcı mesajı ve geçmiş hiçbir
zaman dönmez; `preview` yalnız açık native tercih ile sunucunun PIN/ana
profil/güvenlik denetimi birlikte geçtiğinde tamamlanmış assistant metnidir.

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

Güncel `../freud-dev/server.py`, `index.html`, eşitleme modülleri, portre,
imgeleme ve TUS metadata varlıkları her derlemeden önce `syncDivanSources`
göreviyle pakete kopyalanır.
Ardından `verifyDivanEmbedding`, ortak kaynaklarla gömülü kopyaları bayt bayt
karşılaştırır; ayrıca bu sürüm için dondurulan SHA-256 allowlistine ve eşitleme
protokolünün v8 olduğuna veya sabit Şema Path v5 sözleşme fixture’ına uymayan
tek bir kaynakta derlemeyi durdurur. Kullanıcı
veritabanı, API anahtarı veya özel anahtar benzeri içerik de paketlemeyi
engeller. `freud.db` hiçbir zaman kopyalanmaz.

```text
./gradlew clean verifyDivanEmbedding lintDebug assembleDebug
./gradlew clean verifyDivanEmbedding lintRelease assembleRelease
```

Çıktılar:

```text
app/build/outputs/apk/debug/app-debug.apk
app/build/outputs/apk/release/app-release.apk
```

Release APK bu Mac’in kişisel imza anahtarıyla imzalanır. Sonraki sürümlerin
mevcut uygulamanın üstüne kurulabilmesi için aynı imza anahtarının korunması
gerekir. Hazırlama komutu beklenen anahtarın SHA-256 özeti uyuşmazsa yeni bir
anahtarla uyumsuz paket üretmek yerine derlemeyi durdurur. Bu yapı Google Play
yayını değil, kişisel doğrudan kurulum içindir.

Bu kaynak ağacının sürümü **2026.08.22.15**’tir (`versionCode 2026082215`).
