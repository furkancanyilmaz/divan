# Plan — Yaşayan Harita: Android tarama hataları

Kodu okuyup ölçtüm. Aşağıdakiler tahmin değil, doğrulanmış bulgular.
Her madde "nasıl kanıtladım" satırı taşıyor.

---

## A. TARAMA HATALARI (asıl sorun)

### A1. Geçici hata kalıcı başarısızlığa çevriliyor — EN KRİTİK
`run_living_map_backfill_job` içindeki dış `except`, **her hatayı** doğrudan
`status='failed'` yapıyor. Zaman aşımı, hız sınırı, anlık ağ kesintisi,
sağlayıcı 5xx — hepsi kalıcı ölüm sayılıyor.

Oysa aynı dosyadaki otomatik tarama (`autoscan`) bunu doğru yapıyor:
`chat_error_is_retryable(code)` ile ayırıyor ve geri çekilmeli yeniden
deneme kuruyor.

**Kanıt:** `chat_error_is_retryable` kodda 4 yerde geçiyor; backfill işinin
gövdesinde **0**. Backfill'de `attempt` sayacı da **0** — hiç yeniden deneme
mantığı yok.

**Etki:** Telefonda ağ bir saniye dalgalansa tarama ölüyor ve "bir şeyler
ters gitti" çıkıyor. Senin yaşadığın şey büyük ihtimalle bu.

**Çözüm:** Backfill'e autoscan'deki sınıflandırmayı taşı: geçici hatada
`queued` + gecikmeli yeniden kuyruk, kalıcı hatada `failed`. Deneme sayacı
ekle (3 deneme), sonra bırak.

---

### A2. Arayüz hatayı yutuyor
`startLivingMapSectionScan` içinde `try/finally` var ama **`catch` yok**.
`api()` hata fırlatınca kendi `showError`'ını gösterip fırlatıyor; bölüm
düğmesi bunu yakalamadığı için kullanıcı **hangi bölümde ne olduğunu**
öğrenemiyor, sadece genel "Bir şey ters gitti" görüyor.

**Kanıt:** o fonksiyonda `catch` sayısı = 0.

**Çözüm:** `catch` ekle; bölüm adıyla anlamlı mesaj göster ve düğmeyi
"Taramayı sürdür" durumuna al.

---

### A3. Başarısız iş kendi kendine toparlanmıyor
`schedule_living_map_backfill_job` (gecikmeli yeniden kuyruk) yalnız
"başka görüşme meşgul" durumunda çağrılıyor. İş `failed` olduktan sonra
**hiçbir otomatik yol** onu geri getirmiyor; yalnız kullanıcı düğmeye
basarsa (bu turda eklediğim sürdürme yolu) devam ediyor.

**Kanıt:** backfill gövdesinde `schedule_living_map_backfill_job` = 1 geçiş,
o da meşgul dalında.

**Çözüm:** Geçici hatada A1'deki zamanlayıcıyı kur; kullanıcı müdahalesi
gerekmesin.

---

### A4. Sağlayıcı eşleşmezse 409 — sessiz kilit
Uç nokta, istekteki `provider_id/model_id` ile sunucudakini karşılaştırıp
farklıysa 409 atıyor. Arayüz bu değerleri `historicalAnalysis.provider`'dan
alıyor; o veri bayatsa (ayarları değiştirdiysen, harita yenilenmediyse)
**her tarama 409 ile ölür** ve sebep kullanıcıya görünmez.

**Çözüm:** 409 alınca arayüz haritayı sessizce tazeleyip **bir kez**
otomatik yeniden denesin; yine olmazsa "ayarlardan modeli doğrulayın"
desin.

---

### A5. Android arka planda tarama kesiliyor (doğrulanması gereken)
İş işçileri `daemon=True` Python thread'i. Android uygulamayı arka plana
alınca süreci dondurabilir. `active_job_state()` **tüm iş türlerine**
baktığı için `ResponseKeeperJobService` tarama sırasında da uyanık
tutabiliyor — ama bu yalnız `setPendingWork` sinyali gittiyse çalışır.
Sinyal `loadJobs()` sonrası veriliyor; `loadJobs` başarısız olursa sinyal
hiç gitmez.

**Durum:** Altyapı doğru kurulmuş görünüyor; kırılma noktası sinyalin
gitmemesi. Telefonda logcat ile ölçmek gerek.

**Çözüm:** Tarama başlatınca `signalNativePendingWork()`'ü `loadJobs`
başarısından bağımsız olarak doğrudan çağır.

---

### A6. "Tek tek mesajları tarayacaktı" — beklenti farkı
Tarama zaten tur tur ilerliyor (`_next_unanalyzed_map_turn`) ve her turdan
sonra kuyruğa dönüyor; ilerleme `through_message_id` ile kalıcı. Yani
"baştan başlıyor" hissi ilerlemenin kaybolmasından değil, **A1 yüzünden
işin ölmesinden** geliyor.

**Çözüm:** A1 çözülünce bu his de kaybolur. Ayrıca ilerlemeyi arayüzde
"14/37 tur tarandı" gibi göstermek gerek — şu an yalnız görüşme sayısı var.

---

## B. ANDROID TASARIM HATALARI

### B1. Bölüm taraması ile genel tarama çakışıyor
Üstte "Şimdiye kadarki turları incele" paneli, altta her bölümde "Tarama
başlat". İkisi de **aynı** backfill ucuna gidiyor. Kullanıcı hangisinin ne
yaptığını bilmiyor; ikisi aynı anda basılırsa biri "zaten sürüyor" diyor.

**Çözüm:** Telefonda genel paneli tamamen gizle; bölüm düğmeleri tek yol
olsun. Genel tarama masaüstünde kalsın.

### B2. Bölüm odağı ilerlemeyi paylaşıyor
Dört bölümün düğmesi var ama hepsi **tek bir iş** üzerinde çalışıyor.
"Güçler" taraması başlatınca "Değerler" düğmesi de "sürüyor" olup
kilitleniyor. Kullanıcı için bu bozuk görünüyor.

**Çözüm:** Ya bölüm başına ayrı ilerleme tut, ya da arayüzde açıkça
"tek tarama sırayla tüm bölümleri işler; odak sırayı belirler" de.
İkincisi daha dürüst ve daha az kod.

### B3. Not satırı boş kalıyor
`data-living-map-scan-note` alanları ilk açılışta boş geliyor
(ölçtüm: `["","",""]`), çünkü `renderLivingMapScanControls` yalnız
`renderLivingMap` içinde çağrılıyor ve harita yüklenmeden çalışıyor.

**Çözüm:** Overlay açılışında da çağır.

### B4. Yapışkan sekmeler içeriği örtüyor
Bu turda kısmen düzelttim (`scroll-margin-top`), ama "İçgörü Gelen Kutusu"
başlığı hâlâ şeridin altında kalıyor.

---

## SIRALAMA

| # | İş | Etki | Emek |
|---|---|---|---|
| 1 | **A1** geçici/kalıcı hata ayrımı + yeniden deneme | Çok yüksek | Orta |
| 2 | **A2** arayüzde catch + anlamlı mesaj | Yüksek | Düşük |
| 3 | **A4** 409'da otomatik tazeleme | Yüksek | Düşük |
| 4 | **A5** sinyali doğrudan gönder | Yüksek | Düşük |
| 5 | **B1** telefonda genel paneli gizle | Orta-yüksek | Düşük |
| 6 | **B2** tek-iş gerçeğini arayüzde dürüstçe göster | Orta | Düşük |
| 7 | **A6** tur ilerlemesini göster | Orta | Düşük |
| 8 | **B3/B4** not satırı + örtme | Düşük | Düşük |

**1-4 birlikte** asıl şikâyetini bitirir: tarama artık geçici hatada ölmez,
öldüyse sebebini söyler ve kaldığı yerden sürer.

## Doğrulama
- Sağlayıcıyı bilerek bozup tarama başlat → iş `failed` değil `queued`
  olmalı, geri çekilmeyle yeniden denemeli.
- Kalıcı hata (geçersiz anahtar) → `failed` olmalı ve mesaj sebebi söylemeli.
- Tarama sırasında uygulamayı arka plana al → logcat'te ResponseKeeper
  uyanık kalmalı, dönünce ilerleme korunmuş olmalı.
- Mevcut 1278 test yeşil kalmalı.
