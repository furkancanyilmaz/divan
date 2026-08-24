# Plan — Şema modunu sohbete taşımak + bulunan hatalar

Kodu okuyup canlı sunucuda ölçtüm. Aşağıdakiler tahmin değil; her madde
"nasıl kanıtladım" satırı taşıyor.

---

## BULUNAN HATALAR

### H1. Butonlara basılamıyor — kök neden bulundu
Sohbetteki "Bunu çalışalım / Sonraki görüşmeye bırak / Şimdilik değil"
düğmeleri `schemaActionAllowed('review_candidate')` ile kilitleniyor.
Bu, sunucudan gelen `allowed_actions` listesine bakıyor.

**Ölçüm (canlı sunucu, yeni görüşme):**
- Şema modu KAPALI → `allowed_actions = ['set_mode']`
  → `review_candidate` yok → **bütün düğmeler disabled**
- Şema modu AÇIK → `allowed_actions = ['review_candidate','start']`
  → düğmeler çalışır

**Sonuç:** Düğmeler bozuk değil; **şema modu kapalı olduğu için** kilitli.
Kart yine de gösteriliyor — kullanıcıya basılamayan düğme sunuluyor. Asıl
kusur bu: ya mod açık olmalı, ya kart "önce modu aç" demeli.

### H2. Modu açan anahtar yalnız ayrı panelde
`schemaModeToggle` onay kutusu sadece Şema Yolu overlay'inin içinde.
Sohbetten erişilemiyor. Kullanıcı kartı sohbette görüyor ama modu
açmak için ayrı sayfayı bulup açmak zorunda.

**Kanıt:** `setSchemaMode(` yalnız 2 yerde geçiyor; ikisi de overlay içi.

### H3. Modele 18 şemanın yalnız 4'ü sunuluyor — CİDDİ
`SCHEMA_CANDIDATE_CATALOG` hâlâ eski dar listeden türüyor:
terk edilme, kusurluluk, boyun eğme, yüksek standartlar.

**Ölçüm:** `len(SCHEMA_CANDIDATE_CATALOG) == 4`, oysa
`len(SCHEMA_DEFINITIONS) == 18`. Mod tarafı 21'e çıkmış, şema tarafı
güncellenmemiş.

**Etki:** "Değişken değiştirerek tam şemayı buluyor mu?" sorunun cevabı
**hayır**. Model duygusal yoksunluk, güvensizlik, başarısızlık,
kendini feda gibi 14 şemayı adlandıramıyor; en yakın 4'ten birine
zorlanıyor. Yanlış etiket üretmesinin sebebi bu.

### H4. Terapi/ders seçimi tek yerden açılıyor
`showMobileStartChoice` **yalnız arama sonucundan** çağrılıyor (1 çağrı
noktası). Ana akıştaki yeni görüşme yolu (`newConversationForCurrentMaster`)
bu seçimi hiç göstermiyor; `preferredMode` yoksa doğrudan terapiye,
felsefeciyse derse gidiyor.

**Not:** Senin "direkt ders açılıyor" gözlemini birebir üretemedim —
kodda varsayılan terapi. Bu maddeyi **önce yeniden üretmemiz** gerek:
hangi ekrandaki artıya bastığını bilmem lazım (ana liste mi, sohbet içi
artı mı, arama mı).

---

## ŞEMA MODUNU SOHBETE TAŞIMA

Hedef: mod açıkken **her şey sohbetin içinde**; ayrı sayfa yok.

### S1. Modu sohbetten aç/kapat
Sohbet içi kartın üstünde tek satır: *"Şema terapisi modu kapalı —
açmak ister misiniz?"* + tek düğme. Basınca `set_mode` çağrılır, kart
düğmeleri aynı anda açılır.

Böylece H1 ve H2 birlikte çözülür: kullanıcı kilitli düğmeye bakmaz,
kilidi açan şey elinin altındadır.

### S2. Aday kartı sohbette tam işlevli
Zaten sohbette çiziliyor (`renderSchemaInlineCandidates`). Eksik olan
yalnız izin. S1 sonrası "Bunu çalışalım" çalışır ve **çalışma yolu
sohbette açılır**, overlay açılmaz.

### S3. Odak seçimi sohbette
`focus` aşamasındaki mod kartları overlay yerine sohbete gömülür —
mevcut aday kartıyla aynı bileşen, aynı yerleşim. Kullanıcı butonla
seçer, sohbet akmaya devam eder.

### S4. Aşama şeridi
Mevcut `modeWorkStrip` genişletilir: hangi aşamada olduğunu (Araştır →
Odak → Yöntem → Çalışma) ve sıradaki tek eylemi gösterir. Ekranı
kaplamaz, tek satır.

### S5. Overlay'i emekliye ayır
Şema Yolu overlay'i telefonda gizlenir; içeriği S1–S4 ile sohbete taşınır.
Masaüstünde kalabilir (geniş ekranda yan panel mantıklı).

**Sınır:** Onay kapıları, güvenlik ön kontrolü ve yoğunluk tavanı
aynen korunur. Sohbete taşımak "onayı atlamak" demek değildir; yalnız
aynı onayı aynı yerde sormaktır.

---

## SIRALAMA

| # | İş | Etki | Emek |
|---|---|---|---|
| 1 | **H3** kataloğu 18 şemaya çıkar | Çok yüksek | Düşük |
| 2 | **S1** modu sohbetten aç (H1+H2 çözülür) | Çok yüksek | Düşük |
| 3 | **S2** aday kartı tam işlevli | Yüksek | Düşük |
| 4 | **S3** odak seçimi sohbette | Yüksek | Orta |
| 5 | **S4** aşama şeridi | Orta | Düşük |
| 6 | **S5** overlay'i telefonda gizle | Orta | Düşük |
| 7 | **H4** terapi/ders — önce birlikte yeniden üret | ? | ? |

**1-2 birlikte** senin bugün yaşadığın iki şikâyeti bitirir: model doğru
şemayı bulabilir ve düğmeler basılabilir olur.

## Doğrulama
- 18 şemanın hepsi modele sunulan katalogda görünmeli.
- Mod kapalıyken kart "modu aç" davetiyle gelmeli, ölü düğmeyle değil.
- Mod açılınca aynı kartın düğmeleri anında etkinleşmeli.
- Çalışma yolu açılınca overlay AÇILMAMALI; sohbet akmaya devam etmeli.
- Onay kapıları ve güvenlik kontrolleri bozulmamalı.
- Mevcut 1283 test yeşil kalmalı.
