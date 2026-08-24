# Plan — Kerem Genç terapisi: adım adım ne olacak

Kodu okuyup ölçtüm. Önce **şu an gerçekte ne oluyor**, sonra **ne olmalı**.

---

## ŞU AN GERÇEKTE NE OLUYOR (ölçüldü)

| Adım | Durum |
|---|---|
| Giriş soruları ("bugün ne yapalım", yoğunluk) | ✅ Kaldırıldı |
| Terapi/ders seçimi (Kerem'de) | ✅ Kaldırıldı |
| Şema modu | ✅ Otomatik açık |
| Aday üretimi | ✅ **Otomatik** — `confirm()` kalktı |
| Odak (mod) kartları | ✅ **Kendiliğinden beliriyor** |
| `explore` tıkanması | ✅ Kaydet düğmesi eklendi |
| Faz kartı | ✅ Sohbette çalışıyor |
| Sandalye | ✅ Sohbette görünüyor (istemci köprüsü) |

**Adım 1-3 tamamlandı.** Kalanlar: sandalyeyi sohbetten onaylı başlatma (4)
ve köken/büyütme/Sağlıklı Yetişkin'i karta bağlama (5).

**İki kritik boşluk:**

1. **`offer_focus` ölü uç.** `grep` ile doğruladım: ne arayüzde ne
   sunucuda çağrılıyor. Yani "Neyi çalışalım?" kartı ancak ben elle
   tetiklersem çıkıyor — gerçek kullanımda **asla** çıkmaz.
2. **Aday üretimi otomatik değil.** Kullanıcı her mesajdan sonra
   mesaja basıp "Şema ve harita için incele" demek zorunda, üstüne bir
   de tarayıcı `confirm()` kutusu çıkıyor. Kimse bunu yapmaz.

Otomatik tarama (`living_map_autoscan`) altyapısı **var** ve Kerem
terapi görüşmesinde uygun; şema modunu da tanıyor. Yani bağlanması
gereken bir hat, sıfırdan kurulacak bir şey değil.

---

## KULLANICI TIKLAYINCA NE OLMALI

### 0. Girişte
Kerem Genç'e tıklar → **hiçbir kapı yok** (bu turda yapıldı).
Sohbet açılır, mod arkada açıktır. Kullanıcı yazmaya başlar.

### 1. Dinleme (`explore`)
Kullanıcı anlatır, Kerem yanıtlar. **Hiçbir kart çıkmaz.**
Erken etiketleme yasağı: eşik dolmadan (3 tamamlanmış tur) mod adı geçmez.

*Değişecek:* Her tamamlanmış turdan sonra tarama **kendiliğinden**
koşar. Kullanıcı hiçbir şeye basmaz, `confirm()` görmez.

### 2. İlk kart: "Bir çalışma olasılığı fark ettim"
Eşik dolunca ve kanıt birikince input üstünde kart(lar) belirir.
Birden çoksa yana kaydırılır, her biri ayrı kapatılabilir.

Seçenekler: **Bunu çalışalım · Şimdilik değil**

### 3. Çalışma yolu açılır (`explore` fazı)
"Bunu çalışalım" → aday kabul edilir → kart "Çalışma yolunu aç"a döner
→ basınca yol açılır.

Aşama kartı: *"Bugünkü döngüyü birlikte yazalım"*

*Değişecek:* Şu an "Önce bugünkü olayı ve ihtiyacını yaz" diyor ama
**nereye yazacağını söylemiyor ve düğme yok** — kullanıcı tıkanıyor.
Kart, kullanıcının sohbete yazdığı cümleden tetikleyici/ihtiyaç
önerip **tek dokunuşla kaydettirmeli**.

### 4. Odak: "Neyi çalışalım?" (`focus`)
Usta en fazla 3 mod kartı sunar; kullanıcı butonla seçer.
**Hiçbiri** her zaman seçenektir.

*Değişecek:* `offer_focus` şu an ölü. Faza girildiğinde usta
adayları **kendiliğinden** sunmalı.

### 5. Yöntem: "Nasıl çalışalım?" (`method`)
En fazla 2 yol sohbette sunulur (Mod haritası, Empatik yüzleştirme).
Ön kontrol isteyenler (sandalye, imgeleme) burada listelenmez —
sessizce başlatılamazlar.

*Değişecek:* Sandalye çalışmasına sohbetten geçilebilmeli, ama
**onay adımıyla**: "Bu çalışma daha yoğun; başlamadan önce kısa bir
kontrol yapalım mı?" → onay → sandalye sohbette başlar.

### 6. Çalışma (`work`)
Seçilen yöntem yürür. Sandalye seçildiyse replikler sohbette mod
etiketiyle görünür ("Kırılgan Çocuk: …"). Üstte minik şerit kimin
konuştuğunu söyler; "Bitti" kapanış onayına gider.

Bu fazda ayrıca: köken yaşı, yıl yıl büyütme, Sağlıklı Yetişkin izi.

*Değişecek:* Bu üçü şu an yalnız API'de var, sohbette sorulmuyor.
Aşama kartı sırayla sormalı.

### 7. Pratik (`practice`)
Tek değişkenli küçük bir deneme. "Bu haftaya tek ve küçük bir şey."
İsteğe bağlı — atlanabilir.

### 8. Takip ve kapanış (`followup` → `complete`)
Kapanış **onay noktasından** geçer (mevcut, korunur).
Kazanımlar haritaya işlenir, sohbet olduğu yerden devam eder.

---

## SIRALAMA

| # | İş | Etki | Emek | Risk |
|---|---|---|---|---|
| 1 | Aday üretimini otomatikleştir (`confirm()` kalksın) | Çok yüksek | Orta | Orta |
| 2 | `offer_focus`'u faza girince kendiliğinden çağır | Çok yüksek | Orta | Düşük |
| 3 | `explore` kartına kaydet düğmesi (tıkanma biter) | Yüksek | Orta | Düşük |
| 4 | Sandalyeyi sohbetten onaylı başlat | Yüksek | Yüksek | Orta |
| 5 | Köken / büyütme / Sağlıklı Yetişkin'i karta bağla | Orta-yüksek | Orta | Düşük |

**1-3 birlikte** akışı ilk kez uçtan uca kendiliğinden yürütür.
Şu an zincir 2. adımda kopuyor.

## KORUNACAK SINIRLAR
- Erken etiketleme yasağı (eşik dolmadan mod adı yok)
- Sahte anı yasağı (yaş/sahne yalnız kullanıcıdan)
- Ön kontrol isteyen yöntemler sessizce başlamaz
- Kapanış onay noktası atlanmaz
- `safety_hold` varken tüm katman susar
- Mevcut 1294 test yeşil kalmalı

## DOĞRULAMA
- Kullanıcı hiçbir yere basmadan, sadece konuşarak 3. adıma gelebilmeli.
- Hiçbir noktada tarayıcı `confirm()` kutusu çıkmamalı.
- `explore` kartında ne yapacağı belirsiz kalmamalı.
- Panel Android'de hiç açılmamalı.
