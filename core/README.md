# Divan — Ustalarla Terapi ve Ders (eski adıyla: Freud — Berggasse 19)

Yerel, sıfır bağımlılık (yalnızca Python stdlib) terapi, ders ve felsefi
diyalog uygulaması.
Varsayılan olarak DeepSeek (deepseek-v4-pro) ile çalışır; **⚙ Ayarlar**
içinden OpenAI, Claude (Anthropic) veya LM Studio/OpenAI uyumlu yerel model
seçilebilir. Anahtarlar kaynak kodda tutulmaz. Görüşmeler yerel SQLite
veritabanında saklanır; bulut sağlayıcısı seçilirse yanıt üretmek için mesaj
içeriği o sağlayıcıya gönderilir. Yerel sağlayıcı seçildiğinde model trafiği
yalnız bilgisayarın loopback adresinde kalır ve uygulama sessizce buluta
geçmez.

## Çalıştırma

**Kolay yol:** `Freud.command` dosyasına çift tıkla. Sunucu çalışmıyorsa
başlatır; zaten çalışıyorsa sadece tarayıcıyı açar.

**Terminalden:** `cd ~/Desktop/freud && python3 server.py`
→ http://127.0.0.1:8768 (port doluysa: `PORT=8770 python3 server.py`)

## Ustalar (sol üst köşeden seçilir; tema da değişir)

**Terapistler** sekmesinde 34 koltuk vardır. İlk kataloğa Bion, Kernberg,
Fonagy, Albert Ellis, Insoo Kim Berg, Michael White, Minuchin, Bowen,
Leslie Greenberg, William Miller, Francine Shapiro ve Sue Johnson eklendi.
Böylece modern psikodinamik, mentalizasyon, REBT, çözüm odaklı, anlatı,
yapısal ve kuşaklararası aile terapisi, duygu odaklı terapi, motivasyonel
görüşme, EMDR hazırlığı ve duygu odaklı çift terapisi de ayrı yöntem
haritaları ve ayrı klinik seslerle temsil edilir.

**Felsefeciler** sekmesinde 36 düşünce ve araştırma ustası vardır: Sokrates, Platon,
Aristoteles, Epiktetos, Marcus Aurelius, Epikuros, Konfüçyüs, Fârâbî,
İbn Sînâ, İbn Rüşd, Descartes, Spinoza, Hume, Kant, Kierkegaard, Nietzsche,
Wittgenstein, Sartre, Simone de Beauvoir, Camus, Hannah Arendt,
Merleau-Ponty ve Foucault. Bunlara ek olarak **Karanlık Düşünürler**
grubunda Machiavelli, Hobbes, La Rochefoucauld, Marquis de Sade,
Schopenhauer, Cioran ve Carl Schmitt; **Karanlık Kişilik Araştırmacıları**
grubunda Delroy Paulhus, Kevin Williams, Erin Buckels, Daniel Jones,
Henri Chabrol ve Morten Moshagen bulunur. Çağdaş araştırmacılar inceledikleri
özelliklerin savunucuları gibi sunulmaz; konuşmaları yayımlanmış çalışmaların
eğitimsel sentezidir. Her birinin kavramlarına özgü dört düşünme hareketi ve
ayrı bir konuşma ritmi bulunur. Felsefeciler ve araştırmacılar yalnız
ders/felsefi diyalog kipinde çalışır; terapi, tanı, sevk, rüya yorumu ve
klinik teknik araçlarına erişmez.

**Hakikat**, kurucusu olmayan ayrı bir terapi koltuğudur. Kelimelerin
ötesine bakmaya eşlik eden isimsiz ses az ve yavaş konuşur; karanlık/mum
ışığı temasıyla gelir.

Hangi ustanın uygun olduğundan emin değilsen: **🧭 Kime gitsem?** —
derdini yaz, kapı görevlisi üç usta önersin.

Tarihsel kişiler açıkça tarihsel bir canlandırma olarak uyarlanır:
üslupları ve temel kavramları kendi eserlerinden gelir, sonraki bilgi ve
yorumlar bunlardan ayrılır. Her ustanın defteri, notları ve hafızası
AYRIDIR.

## Modlar ve özellikler

- **Dört model seçeneği:** DeepSeek, OpenAI, Claude ve LM Studio/yerel
  OpenAI-uyumlu sunucu. Her sağlayıcının modeli ve anahtarı ayrı saklanır.
  Yerel model ekranı LM Studio (`1234`), Ollama (`11434`) ve llama.cpp
  (`8080`) için bilinen loopback adreslerini otomatik tarayabilir. Farklı
  loopback portu elle girilebilir; LAN veya internet adresi kabul edilmez.
  Ortam değişkenleri de desteklenir: `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `LMSTUDIO_API_KEY`, `LMSTUDIO_BASE_URL`,
  `LMSTUDIO_MODEL` ve `DIVAN_LLM_PROVIDER`.

- **🛋️ Terapi:** kısa yanıt ve en fazla tek soru/yönerge; ekolün tekniği
  içeriden uygulanır. Her ustanın ilk dikkat alanı, klinik hamlesi, ritmi,
  imza soru türü ve kaçınacağı karikatürleşme ayrıdır; etkin çalışmada
  yalnız seçilen yöntemin ayrıntısı öne çıkar. 🌙 düğmesiyle rüya anlatılır
  (önce çağrışım, sonra yorum). Kriz sezilirse gerçek yardıma yönlendirir
  (112). Üstteki iki hedef/çalışma şeridi **▴ Hedefler** düğmesiyle birlikte
  gizlenip yeniden gösterilebilir; seçim bu tarayıcıda hatırlanır.
- **📖 Ders:** dört alt mod — Müfredatlı Yolculuk (durak göstergesi üstte;
  tıklayınca harita), Serbest Sohbet, Vaka Üzerinden ve **Kaynaklı Ders**.
  Kaynaklı anlatım tarihsel görüşü, güncel kanıtı ve belirsizliği ayırır.
- **🕯 Seansı/Dersi bitir:** kapanış sözü söylenir, görüşme mühürlenir
  (salt-okunur olur); not, özet, mektup ve kavram işleri arka planda sürer.
- **🎓 Süpervizyon:** biten (≥4 mesaj) bir terapi seansının üstünden,
  terapist süpervizör şapkasıyla o seansta ne yaptığını ve neden yaptığını
  anlatır. Ders sekmesinde görünür.
- **🧠 Hafıza Merkezi:** ustaların hatırlayacağı bilgileri ekleyebilir,
  düzenleyebilir, onaylayabilir veya tamamen dışarıda bırakabilirsin.
  Bir kayıt yalnız seçili ustayla ya da tüm ustalarla paylaşılabilir;
  “Hassas — modele gönderme” açıksa kayıt bilgisayarda kalır. Otomatik seans notları önce
  taslak olur ve onaylanmadan yeni sohbetlerin bağlamına girmez.
- **Hafıza zinciri:** konuşmalar `freud.db`'de (SQLite). Onaylanmış her 5
  yeni notta defter bir **aday vaka formülasyonuna** damıtılır. Taslak,
  kullanıcı ayrıca onaylamadan sonraki görüşmelerin bağlamına girmez;
  önceki model formülasyonları yeni formülasyona kanıt olarak aktarılmaz.
- **✦ Yaşayan Harita ve İçgörü Gelen Kutusu:** kapanan terapi görüşmelerinin
  doğrudan kullanıcı mesajlarından en fazla üç düzeltilebilir aday çıkarır.
  Kullanıcı “Uyuyor”, “Kısmen”, “Yalnız şu bağlamda”, “Uymuyor” veya
  “Artık geçerli değil” diyebilir; sessizlik onay sayılmaz. Her içgörünün
  tarihli kullanıcı kaynakları görülebilir. Şema ve savunma hipotezleri iki
  ayrı görüşmede desteklenmeden görünür örüntü veya model bağlamı olmaz.
  Onaylanan kayıtlardan yalnız o konuşmayla ilgili en fazla ikisi terapi
  promptuna girer; felsefi diyaloglara klinik harita gönderilmez. Bir kaynak
  silinirse ondan türetilmiş sentez de silinir.
- **🏛 Vaka Konseyi:** 2-4 usta seç; aynı vakayı/konuyu farklı ekollerin
  gözünden tartışırlar, birbirlerine itiraz ederler. İstersen açık terapi
  seansını vaka olarak konseyin önüne koyabilirsin.
- **🌙 Rüya Defteri:** tüm seanslarda anlattığın rüyalar tek yerde;
  "Motifleri yorumlat" ile aktif usta tekrarlayan motifleri yorumlar.
- **🧭 Kime gitsem?:** tarafsız triyaj — derdine göre üç usta önerisi.
- **🔎 Arama:** tüm konuşmalar ve defter notlarında tam metin arama
  (kenar çubuğundaki kutu, Enter ile).
- **🗄 Görüşme arşivi:** terapi ve ders listelerinde `Güncel | Arşiv`
  arasında geçiş yapılabilir. Arşivlemek yalnız görünürlüğü değiştirir;
  mesajlar, notlar, haritalar ve çalışmalar korunur. Arşivlenen görüşmeler
  isteğe bağlı otomatik süre temizliğinden muaftır. Kalıcı silme ayrı bir
  onay penceresiyle sunulur.
- **🧭 Yolculuk:** defterde formülasyonlar eskiden yeniye listelenir —
  zaman içindeki değişimin haritası.
- **💾 Yedek:** freud.db'yi tarihli dosya olarak indir.
- **⌁ Aynı Wi‑Fi eşitleme:** Ayarlar'dan bilgisayarda beş dakikalık,
  tek kullanımlık bir QR oluşturulur; Android Divan bu kodu tarayıp iki
  cihazdaki görüşme, mesaj, çalışma notu, hafıza, hedef, check-in ve seans
  özetlerini kayıt düzeyinde birleştirir. Ham SQLite dosyası kopyalanmaz.
  Ana sohbet sunucusu yalnız `127.0.0.1` üzerinde kalır; eşitleme için ayrı,
  kısa ömürlü TLS kanalı açılır ve sertifikası QR içindeki parmak iziyle
  doğrulanır. API anahtarları, PIN, sağlayıcı/model ayarları, açık model
  işleri ve oturum belirteçleri aktarılmaz. Birleştirme öncesi otomatik geri
  dönüş noktası alınır; aynı çalışma notu iki cihazda değişmişse kullanıcıya
  sorulur. Dış sunucu ve Divan hesabı gerekmez.
- **⚙ Gizlilik ve güvenlik:** ilk açılış bilgilendirmesi, isteğe bağlı PIN
  kilidi, kaynak kod dışında ve sağlayıcı başına ayrı API anahtarı, sabit
  kriz güvenliği akışı. JSON dışa aktarımı anahtarları içermez; tam SQLite
  yedeği ayarları da taşıdığı için kişisel ve gizli tutulmalıdır.
- **Uyarlanabilir görünüm:** araç çubuğu, hedef/çalışma şeritleri, sohbet
  balonları ve yazma alanı pencere genişliğine göre küçülür veya satıra
  geçer. Uzun bağlantılar ile birleşik sözcükler kullanıcı mesajını ekranın
  dışına itemez. Dar pencerede sol menü çekmeceye, sandalye ve imgelem
  çalışmaları da sohbeti ezmeden üst katmana dönüşür.
- **Seans öncesi kısa kontrol:** terapi başlamadan odak, duygu/gerginlik,
  istenen tempo, yoğunluk sınırı ve o gün uzak durulacak konular isteğe bağlı
  olarak belirlenebilir. Bu çerçeve yalnız o seansa aittir.
- **Birlikte çalışma pusulası:** seans içinde anlaşılmış hissetme, hedefi
  sahiplenme, yöntemin uygunluğu ve temponun güvenliği ayrı ayrı 0–10
  işaretlenebilir. Yalnız aynı koşullarda alınmış ardışık iki kayıt
  karşılaştırılır; sonuç bir tanı, başarı puanı veya kötüleşme hükmü değil,
  birlikte yeniden bakma davetidir.
- **Yapılandırılmış onarım:** “Yanlış anladın” geri bildirimi sohbetin içine
  kaybolmaz. Kullanıcı neyin kaçtığını ve neye ihtiyaç duyduğunu yazar;
  terapist anladığını sınar, kullanıcı doğrulamadan onarım tamamlanmış
  sayılmaz. Açık bir kopukluk varken yeni bir teknik ilerletilmez; durma,
  toparlanma ve seansı bitirme her zaman kullanılabilir.
- **Kullanıcı onaylı süreç haritası:** bütün yöntemler farkındalık, kaçınma,
  düşünceyle kaynaşma, öz-eleştiri, davranışsal katılım, ilişkisel bağ,
  değer yönelimli eylem, duygu düzenleme, ihtiyaç/sınır ve anlam bütünlüğü
  gibi ortak süreçlere bağlanır. Seans hedefi önce taslak olur, ayrıca
  onaylanır ve yalnız kullanıcının verdiği “ulaşıldı / kısmen / duraklatıldı /
  değişmedi” işaretiyle ilerler; yapay yüzde veya nedensellik üretilmez.
- **Ortak gerekçe ve kararsızlık çalışması:** tetikleyici–tepki–kısa/uzun
  vadeli etki zinciri düzenlenebilir bir hipotez olarak görünür. Değişme ve
  aynı kalma gerekçeleri ayrı tutulur; terapist kullanıcıyı ikna etmeye ya
  da “gizli gerçeği” bildiğini söylemeye çalışmaz.
- **Young ile imgeleme ve yeniden ebeveynlik alanı:** açık teknik onayına ek
  olarak ayrı yönelim/durma sinyali onayı ister. Kullanıcı sahneyi, ihtiyacı
  ve koruyucu yanıtı kendi sözcükleriyle yazar; sağ panelde terapistin
  kaynaklı gözlemi, kısa yönergesi ve kontrol sorusu ayrı görünür. Sınır,
  etkinleştirme, koruyucu yanıt, anlam, şimdiye dönme ve takip aşamaları
  ileri/geri alınabilir; uygulama anı veya geçmişi icat etmez. Yüksek
  yoğunlukta çalışma durur, kriz sinyalinde model çağrılmadan güvenliğe
  geçilir.
- **Tek temaslık odak:** 15, 25 veya 45 dakikalık düşük riskli bir odak;
  çerçeve, çalışma ve kapanış adımlarıyla yürür. İsteğe bağlı 2–7 günlük
  yerel takip notu eklenebilir. Bu alan “tek seansta tedavi” vaadi taşımaz.
- **Pratik Laboratuvarı:** ilişki onarımı, yansıtma, Sokratik keşif ve
  kararsızlıkla çalışma becerileri terapi seansından ayrı bir alanda prova
  edilir. Prova turları terapi hafızasına, süreç haritasına veya seans
  ilerlemesine yazılmaz; çevrimiçi model yoksa güvenli yerel geri bildirim
  kullanılır.
- **◎ Seans çerçevesi:** odak, başlangıç/bitiş duygu puanı, kullanıcının kendi
  özeti, faydalı/faydasız geri bildirimi ve sonraki küçük adım.
- **Kullanıcı onaylı özet:** seans sonrası hazırlanan kısa özet önce taslak
  olarak bekler; düzenlenip onaylanmadan kalıcı hafızaya girmez.
- **◎ İlerlemem:** hedefler, tamamlanma durumu ve 1–10 günlük check-in geçmişi.
- **Yanıt kontrolleri:** daha sade, daha somut, yavaşla, sadece dinle,
  yanlış anladın; derslerde kaynak ve tarihsel/güncel görüş ayrımı.
- **Veri taşınabilirliği:** SQLite yedeği, geri yükleme, gizli anahtarları
  dışarıda bırakan JSON aktarımı ve otomatik yedekler dahil tüm görüşme
  verilerini silme.
- **Otomatik yedek:** uygulama açılışında günde bir kez `yedekler/` klasörüne
  tarihli veritabanı kopyası alınır; son 7 günlük kopya tutulur. İstenirse
  görüşmeler 30/90/365 gün gibi kullanıcı tarafından seçilen bir süreden
  sonra otomatik temizlenebilir; süresi dolan veri yedeğe alınmadan silinir.
- **⏳ İşlem Merkezi:** kapanış sözü hemen gösterilir; not, formülasyon,
  mektup, kavram ve özet işleri arka planda izlenir. Başarısız bir iş,
  diğerlerini durdurmaz ve yeniden denenebilir.
- **🧰 Durumlu terapi çalışmaları:** seçilen çalışma teklif, açık onay,
  uygulama, toparlanma ve tamamlanma aşamalarıyla izlenir. Yoğunluk her an
  güncellenebilir; kullanıcı tek tuşla durabilir ve şimdiye dönebilir.
  Açık onay verilene kadar başlatma düğmesi kapalıdır; onay alanının tamamı
  tıklanabilir ve durum metni çalışmanın başlayıp başlayamayacağını açıkça
  gösterir.
- **🪑 Canlı sandalye çalışma alanı:** Young’ın Sandalye Diyaloğu,
  Perls’ün Boş Sandalye ve İki Sandalye Çatışması ile Satir’in Parçalar
  Partisi açık onaydan sonra sağ panelde yürütülür. Konuşacak parçayı
  kullanıcı seçer ve sözünü doğrudan kendisi yazar; terapist parçanın yerine
  konuşmadan ayrı bir sütunda gözlem, kısa yönerge ve kontrol sorusu verir.
  Parçalar adlandırılabilir, son tur geri alınabilir, yoğunluk yükselince
  çalışma durup şimdiye döner. Aynı seansta yapılan birden çok çalışma ayrı
  kayıtlarda saklanır ve Markdown aktarımına eklenir.
- **Teknik önerileri:** uygulama yalnız açık seans odağına ve son mesajlara
  bakarak mevcut ustanın repertuvarından en uygun çalışmaları gerekçeleriyle
  öne çıkarır; hiçbir tekniği kendiliğinden başlatmaz.
- **📚 Kaynaklı Vaka Kütüphanesi:** Anna O., Dora, Küçük Hans, Gloria ve
  farklı ekollerden eleştirel/güncel vaka başlangıçları; tarihsel kurum,
  meslek örgütü ve araştırma bağlantıları kartlarda görülebilir.
- **🩺 Bağlam Tanılama:** açık görüşmede modele hangi tür bağlamların
  girdiğini, sınırları, aktif tekniği, sevk durumunu ve yaklaşık bağlam
  büyüklüğünü kişisel metinleri ifşa etmeden gösterir.
- **Sade görünüm:** temel görüşme düğmelerini öne çıkarır; ileri araçları
  silmeden yalnızca arayüz kalabalığını azaltır.
- **🔊 Sesli okuma:** açık görüşmedeki son usta yanıtını tarayıcının yerleşik
  Türkçe ses motoruyla okur.
- **Otomatik gece:** Ayarlar'dan 20.00–07.00 arasında otomatik gece modu.
- **Yerel güncelleme:** güvenilir bir güncelleme zip'i `Guncelle.command`
  üzerine verilir; kod yedeklenir, paket doğrulanır ve `freud.db` korunur.
- **Erişilebilirlik:** mobil açılır menü, klavye kullanımı, yüksek kontrast,
  hareketleri azaltma ve kalıcı yazı boyutu/gece modu tercihleri.
- **🪪 Hakkımda:** her terapistin her görüşmede bildiği sabit bilgiler.
- **⬇ Dışa aktar:** açık görüşmeyi Markdown indir. **⛶** tam ekran.
  **■ Durdur:** akışı keser (cevabın tamamı yine de kaydedilir).

## Dosyalar
- `server.py` — sunucu + çoklu model sağlayıcı katmanı + SQLite +
  not/formülasyon üretimi
- `index.html` — arayüz (tek dosya, terapist temaları sunucudan gelir)
- `sync_service.py`, `sync_engine.py`, `secure_sync_transport.py` —
  kullanıcı başlatmalı cihaz eşitleme, kayıpsız birleştirme ve şifreli yerel
  ağ kanalı
- `sync_qr.py`, `qrcodegen.py` — dış servise başvurmadan yerelde QR üretimi
- `freud.db` — konuşmalar, defterler, formülasyonlar, profil
- `tests/` — canlı veritabanına ve dış ağa dokunmayan otomatik gerileme
  testleri

## Kalite kontrolü

Geliştirici testi: `python3 -m unittest discover -s tests -v`
