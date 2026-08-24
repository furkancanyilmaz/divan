# Plan — Şema terapisini tamamen sohbete taşımak (Android)

Kodu okuyup canlı ölçtüm. Her madde kanıtlı; tahmin yok.

---

## NEDEN "SEÇENEKLER HAZIRLANIYOR" TAKILIYOR

Kart, ustanın mesaj balonuna **iliştiriliyor** (`.row.therapist` altına).
Çizim sırası şöyle:

1. Sohbet açılır → izin verisi henüz gelmemiştir
2. Kart çizilir → izin yok → "Seçenekler hazırlanıyor…" yazılır
3. İzin sonradan gelir → **kart yeniden çizilmez** → yazı orada kalır

`loadSchemaPathDashboard` içinde yeniden çizim var ama yükleme
`schemaPathBusy` yüzünden atlanmışsa hiç tetiklenmiyor.

**Kök çözüm senin önerin:** kartı mesaja iliştirmeyi bırakmak. Input
üstünde sabit tek bir kart, kendi durumunu kendi yönetir; hangi mesajın
altında olduğu önemsizleşir ve bu kırılganlık ortadan kalkar.

---

## A. SABİT ÖNERİ KARTI (input üstü)

### A1. Yerleşim
Mesaj balonuna iliştirme kalkar. Composer'ın hemen üstünde, sohbetle
birlikte kaymayan tek kart:

- Başlık: *"Bir çalışma olasılığı fark ettim"*
- Gövde: adayın kendi cümlenle gerekçesi
- Eylemler: **Bunu çalışalım · Şimdilik değil**
- Sağ üstte **kapatma (×)**

"Seçenekler hazırlanıyor" durumu tamamen kalkar: izin gelmeden kart
**hiç gösterilmez**. Gelince kart belirir; düğme her zaman canlıdır.

### A2. Kapatılabilirlik
× ile kapatılan aday o oturumda bir daha gösterilmez (yerel işaret).
Sunucuya "dismiss" gitmez — kullanıcı yalnız görünümü kapatmış olur;
kararı sonra verebilir.

### A3. Tek kart kuralı
Aynı anda en fazla bir öneri. Birden çok aday varsa en güçlüsü
gösterilir, altta "2 olasılık daha" satırı olur.

---

## B. SOHBET İÇİ ŞEMA AKIŞI (panel yok)

Senin sıralaman, mevcut altyapıya oturuyor:

| Senin adımın | Kodda karşılığı | Durum |
|---|---|---|
| şemayı inceleme / başlangıç | `explore` fazı | var |
| mod seçimi | `focus` fazı | var (bu turda eklendi) |
| sandalye çalışması | `chair-dialogue` + 9 aşama | var, **panelde** |
| yeniden ebeveynleme | `limited-reparenting` yöntemi | var |
| yıl yıl büyütme | `schema_growth` tablosu | var (bu turda eklendi) |
| Sağlıklı Yetişkin gücü | `healthy_adult_marks` | var (bu turda eklendi) |
| ödev ve sonlanış | `practice` + `followup` fazları | var |

**Yani mimari hazır; eksik olan tek şey bunların sohbette akması.**

### B1. En büyük engel: sandalye turları sohbete gitmiyor
Ölçtüm: sandalye replikleri `chair_turns` tablosuna yazılıyor,
`messages` tablosuna **yazılmıyor**. Bu yüzden sohbette görünmüyorlar
ve kullanıcı paneli açmak zorunda kalıyor.

**Çözüm (iki seçenek):**
- **(a) Köprü:** sandalye turu eklenince aynı içerik `messages`'a da
  mod etiketiyle yazılır. Sohbette normal balon olarak görünür.
  Mevcut sandalye mantığı, onaylar ve geri alma bozulmaz.
- **(b) Taşıma:** `chair_turns` tamamen kaldırılıp her şey `messages`
  olur. Temiz ama geri alma, revizyon ve protokol durumu yeniden
  yazılır — riskli ve pahalı.

**Öneri: (a).** Tek yönlü köprü, veri kaybı yok, geri dönülebilir.

### B2. Aşama şeridi
`modeWorkStrip` genişletilir: hangi adımda olduğunu ve **sıradaki tek
eylemi** gösterir. Ekranı kaplamaz.

Örnek: *"Sandalye çalışması · Kırılgan Çocuk konuşuyor"* + **Devam**

### B3. Adım geçişleri sohbette
Her faz geçişi sohbette tek bir kartla sorulur, panelde değil:
- odak seçimi → mod kartları (bu turda yapıldı, sohbete taşınacak)
- yöntem seçimi → en fazla 2 öneri
- sandalye → hangi mod konuşsun
- ödev → tek değişkenli pratik
- kapanış → onay noktası (mevcut, korunur)

### B4. Panel telefonda gizlenir
`schemaPathOverlay` Android'de görünmez olur. Masaüstünde kalır.

---

## C. KORUNACAK SINIRLAR (değişmez)

- Onay kapıları: sandalye/imgelem hâlâ açık onayla başlar.
- Güvenlik ön kontrolü ve yoğunluk tavanı aynen çalışır.
- `safety_hold` varken tüm katman susar.
- Kapanış onay noktası atlanmaz — sohbete taşımak "onayı kaldırmak"
  değildir.
- Sahte anı yasağı: köken yalnız kullanıcının anlattığından dolar.

---

## SIRALAMA

| # | İş | Etki | Emek | Risk |
|---|---|---|---|---|
| 1 | **A1** sabit kart + "hazırlanıyor"u kaldır | Çok yüksek | Orta | Düşük |
| 2 | **A2/A3** kapatma + tek kart | Yüksek | Düşük | Düşük |
| 3 | **B1(a)** sandalye→sohbet köprüsü | Çok yüksek | Orta | Orta |
| 4 | **B2** aşama şeridi | Yüksek | Düşük | Düşük |
| 5 | **B3** geçişleri sohbete taşı | Yüksek | Yüksek | Orta |
| 6 | **B4** paneli telefonda gizle | Orta | Düşük | Düşük |

**1-2 birlikte** bugünkü şikâyetini bitirir: sabit, kapatılabilir kart
ve canlı düğmeler.
**3-4** sandalyeyi sohbete getirir — panelden çıkma zorunluluğu biter.
**5-6** akışın tamamını sohbete taşır.

## Doğrulama
- "Seçenekler hazırlanıyor" hiçbir durumda görünmemeli.
- Kart input üstünde sabit kalmalı, sohbetle kaymamalı, × ile kapanmalı.
- Sandalye repliği sohbette mod etiketiyle balon olarak görünmeli.
- Panel Android'de hiç açılmamalı.
- Onay kapıları ve güvenlik kontrolleri bozulmamalı.
- Mevcut 1286 test yeşil kalmalı.
