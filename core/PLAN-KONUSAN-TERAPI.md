# Konuşan Terapi + Pro Mod — Plan

## Sorun

Şu an terapiyi **butonlar** yürütüyor, konuşma onlara eşlik ediyor.
Kullanıcının istediği bunun tersi: **konuşma yürütsün**, kayıt arkada
kalsın.

Ölçülen durum (`schema_path_allowed_actions`, server.py:16795):

| Faz | Ustanın prompt'ta gördüğü yönerge | İlerleten |
|---|---|---|
| explore | yok | buton (`advance`) |
| focus | **var** (tek faz) | buton |
| method | yok | buton (`choose_method`) |
| work | yok | buton ×6 |
| practice | yok | buton |
| followup | yok | buton (`close`) |

Yani Kerem 6 fazın 5'inde **o an hangi aşamada olduğunu ve ne yapması
gerektiğini bilmiyor**. Terapist gibi konuşuyor ama seansı ilerletemiyor;
ilerletme işi kullanıcıya, butonlara bırakılmış.

## Hedef

1. Kerem her fazda ne yaptığını bilsin ve seansı **konuşarak** yürütsün.
2. Fazlar arası geçiş konuşmadan doğsun; buton **yedek** olsun, zorunlu değil.
3. "Pro mod": terapist cümlesine tıklayınca **hangi tekniği** kullandığı
   görünsün.

## A. Faz yönergeleri (her faz için ustaya "şu an buradasın")

`schema_path_prompt_context` içine faz bloğu eklenir. Her faz için:
ne yapılır, ne yapılmaz, ne olunca sıradaki aşamaya geçilir.

- **explore** — dinle, tetikleyici + ihtiyacı kullanıcının kendi diliyle
  netleştir. Mod adı verme, yorum yapma. İkisi netleşince odağa geç.
- **focus** — (mevcut blok korunur) en fazla 3 yan sun, kullanıcı seçsin.
- **method** — seçilen modla nasıl çalışılacağını **birlikte** kararlaştır
  (konuşma / sandalye / yeniden yazma). Dayatma.
- **work** — asıl çalışma: moda ses ver, köken, yeniden ebeveynleme,
  sandalye. Tek adım at, sözü kullanıcıya bırak.
- **practice** — tek değişkenli, küçük, kullanıcının onayladığı bir deneme.
- **followup** — ne değişti, ne kaldı; kapanış.

**Sınır:** faz yönergesi *yöntem* söyler, *içerik* söylemez. Sahte anı,
tanı ve yaş icadı yasağı her fazda yürürlükte kalır.

## B. Konuşmadan ilerleme (butonu zorunlu olmaktan çıkarma)

Mevcut `[[MOD]]` mekanizmasının aynısı, ikinci bir işaretle:

```
[[FAZ]] hedef_faz | gerekçe (kullanıcının kendi cümlesinden)
```

- Sunucu bunu metinden ayırır (kullanıcı ham etiketi görmez).
- **Mevcut kapılar aynen çalışır**: `explore→focus` için tetikleyici+ihtiyaç
  kaydı hâlâ şart; `focus→method` için kullanıcının mod seçmesi hâlâ şart.
  Yani model kapıyı *zorlayamaz*, yalnız hazır olduğunda kapıyı çalar.
- Kapı kapalıysa geçiş sessizce reddedilir; usta o fazda kalır.

Bu, "hard coded" hissini kaldıran asıl adım: kullanıcı hiçbir butona
basmadan seans ilerler, ama klinik kapılar korunur.

## C. Pro mod (üst alanlar → terapist cümlesinde teknik)

- `messages` tablosuna teknik alanı yok. Yeni tablo:
  `message_techniques(message, phase, technique, rationale)`
- Usta yanıtının sonunda üçüncü işaret:
  `[[TEKNIK]] teknik_adı | tek cümle gerekçe`
- Sunucu ayırır, saklar. **Kullanıcıya normalde görünmez.**
- Üst alanlarda "Pro mod" anahtarı: açıkken terapist balonuna tıklayınca
  o cümlede kullanılan teknik + faz + gerekçe görünür.
- Kapalıyken hiçbir şey değişmez (varsayılan kapalı).

## Çizilmeyecek çizgi

- Faz yönergesi ustaya **ne söyleyeceğini** değil **ne yapacağını** söyler.
- Model kendi kapısını açamaz: içerik koşulları sunucuda kalır.
- Kriz (`safety_hold`) varken tüm katman susar, 112 yolu değişmez.
- Pro mod bir **açıklama** aracıdır, tanı aracı değildir.

## Sıra

| # | Adım | Etki | Emek |
|---|---|---|---|
| 1 | Faz yönergeleri (A) | Çok yüksek | Düşük |
| 2 | Konuşmadan ilerleme (B) | Çok yüksek | Orta |
| 3 | Pro mod (C) | Yüksek | Orta |

1 tek başına "terapist seansı yürütüyor" hissini verir. 2 butonu yedeğe
düşürür. 3 şeffaflık katmanıdır.

## Doğrulama

- Her fazda prompt'ta o fazın yönergesi görünmeli.
- `[[FAZ]]` ile explore→focus: tetikleyici+ihtiyaç **yokken** geçmemeli,
  **varken** geçmeli.
- `[[FAZ]]` ile focus→method: kullanıcı mod seçmemişken geçmemeli.
- Ham `[[FAZ]]` / `[[TEKNIK]]` etiketi kullanıcıya **asla** görünmemeli
  (akış sırasında da).
- Pro mod kapalıyken teknik verisi arayüze sızmamalı.
- safety_hold'da tüm katman susmalı.
- Mevcut 1316 test yeşil kalmalı.
