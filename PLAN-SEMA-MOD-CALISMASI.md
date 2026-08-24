# Plan — Şema Terapi: Mod Çalışması Katmanı

Hedef: kullanıcı konuşur → usta dinler → "şu modlar/şemalar belirdi, hangisini
çalışalım?" diye **buton** sunar → seçilen mod üzerinde köken yaşı bulunur →
küçük hale sınırlı yeniden ebeveynleme + imgelemle yeniden yazma + sandalyede
mod sesleri + empatik yüzleştirme → yaş yaş büyütme → eski hal ↔ bugünkü hal
farkı fark ettirilir → Sağlıklı Yetişkin güçlendirilir.

Karar: mevcut `schema_paths` faz makinesinin **üstüne** katman. Onay kapıları,
güvenlik ön-kontrolü, senkron şeması ve 1182 test korunur.

---

## Kodda ölçülen mevcut durum

| Parça | Durum |
|---|---|
| Faz makinesi (`explore→method→work→practice→followup→complete`) | var |
| `schema_paths` + `schema_path_events` (idempotent, revizyonlu) | var |
| Onay kapıları, `safety_hold`, tek aktif yol kilidi | var |
| Sandalye altyapısı (`chair_runs`/`chair_participants`/`chair_turns`) | var, `actor_kind='part'` destekli |
| İmgeleme (`imagery-rescripting`) | var |
| Şema kataloğu | 4 şema (terk edilme, kusurluluk, boyun eğme, yüksek standartlar) |
| **Mod kataloğu** | **yok** — 4 mod düz listede, `kind` ayrımı yok |
| **Mod seçim ekranı** | **yok** |
| **Köken yaşı** | **yok** (`child_age`/`age_at` = 0 geçiş) |
| **Sınırlı yeniden ebeveynleme** | çok zayıf (11 geçiş, ayrı aşama değil) |
| **Empatik yüzleştirme** | **1 geçiş** — pratikte yok |
| **Yaş yaş büyütme / hal karşılaştırma** | **yok** |
| **Sağlıklı Yetişkin güç ölçüsü** | **yok** |

---

## A. Mod ve şema kataloğunu ayır, genişlet

`THERAPY_CONCEPTS["young"]` 8 satırlık düz liste; şema ile mod aynı torbada,
`kind` alanı yok. Ayrılacak:

```python
SCHEMA_CATALOG = {...}   # kind="schema", alan (domain) + karşılanmayan ihtiyaç
MODE_CATALOG   = {...}   # kind="mode",  family + ses + tipik cümle
```

**Mod aileleri** (Young'ın standart dördü):
- `child` — Kırılgan/Öfkeli/Dürtüsel/Mutlu Çocuk
- `coping` — Kopuk Koruyucu, Boyun Eğen Teslimci, Aşırı Telafici
- `parent` — Cezalandırıcı Ebeveyn, Talepkâr Ebeveyn
- `healthy` — Sağlıklı Yetişkin

Her mod kaydı: `key`, `name`, `family`, `cue` (metinde tanınma ipucu),
`voice` (sandalyede nasıl konuşur), `need` (altındaki karşılanmamış ihtiyaç).

**Sınır:** model yalnız katalogdaki anahtarları adlandırabilir; etiket
sunucuda türetilir (mevcut `SCHEMA_CANDIDATE_CATALOG` disiplini aynen sürer).

## B. Dinle → aday sun → kullanıcı seçsin

Yeni faz: `explore` ile `method` arasına **`focus`**.

- Usta yeterli malzeme birikmeden aday sunmaz (mevcut kanıt eşiği kuralı).
- Eşiğe gelince en fazla **3 mod + 2 şema** adayı, her biri
  *kullanıcının kendi cümlesiyle* gerekçelendirilmiş kart olarak sunulur.
- Kullanıcı **butonla** seçer (telefon + Mac). "Hiçbiri" ve "şimdi değil"
  her zaman seçenektir.
- Yeni eylemler: `offer_focus` (sunucu üretir), `choose_focus` (kullanıcı seçer).

Tablo: `schema_focus_offers(path, conv, candidates_json, chosen_key,
chosen_kind, status, created)` — sunulan adaylar kayda geçer ki
"model sonradan başka bir şey uydurdu" olmasın.

## C. Köken yaşı ve küçük hal

Seçilen mod için `work` fazında:

```sql
schema_origin(path, conv, mode_key,
  age_reported INTEGER,      -- yalnız kullanıcı söylediyse
  age_range TEXT,            -- "6-8" gibi belirsizlik kabul
  scene TEXT,                -- kullanıcının anlattığı sahne
  unmet_need TEXT,           -- o sahnede karşılanmayan ihtiyaç
  confidence TEXT)           -- reported | uncertain | unknown
```

**Sahte anı yasağı (sabit sınır):** `age_reported` ve `scene` **yalnız
kullanıcının anlattığından** dolar. Model tarih, yaş veya sahne icat edemez;
kullanıcı bilmiyorsa `unknown` kalır ve çalışma yaşsız yürür. Bu, mevcut
"sahte anı üretimi yasağı" hattıyla aynıdır.

## D. Sınırlı yeniden ebeveynleme (limited reparenting)

`work` fazında ayrı bir çalışma türü. Usta, o yaştaki çocuğa **ustanın kendi
sesiyle** ihtiyacı karşılayan cümleyi kurar ("O an biri sana şunu söylemeliydi:
…"). Kullanıcıya dayatılmaz; "bu cümle sana nasıl geldi?" diye sınanır.

Sınır: usta gerçek ebeveyn rolü oynamaz, geçmişi değiştirdiğini iddia etmez;
yaptığı **şimdi karşılanan bir ihtiyaç deneyimi**dir.

## E. Sandalyede mod sesleri

`chair_participants.slot_key` = mod anahtarı, `label` = mod adı.
Var olan sandalye altyapısı bunu zaten taşıyor — yeni tablo gerekmez.

Akış: usta hangi modun konuşacağını **yönlendirir**; o mod tek seferde
konuşur; sonra usta **empatik yüzleştirme** yapar:

> *"Seni koruduğunu anlıyorum — yıllarca işe de yaradı. Ama şu an
> ödettiği bedeli birlikte görelim mi?"*

Empatik yüzleştirmenin iki yarısı zorunlu: **önce geçerlilik, sonra bedel**.
Yalnız bedel = suçlama; yalnız geçerlilik = pekiştirme. Tek yarım çıkarsa
prompt seviyesinde reddedilir.

Yoğunluk tavanı: mevcut `WorkspaceSafety.intensityBlocksResume` ve
`intensityLimit` aynen geçerli — Cezalandırıcı Ebeveyn sesi bu tavana tabidir
ve kriz anında hiç konuşturulmaz.

## F. Yaş yaş büyütme + hal karşılaştırma

```sql
schema_growth(path, conv, mode_key, stage_age INTEGER,
  then_response TEXT,    -- o yaşta ne yapabiliyordu
  now_response TEXT,     -- bugün ne yapabiliyor
  difference TEXT,       -- kullanıcının fark ettiği fark
  created TEXT)
```

Usta küçük halden bugüne **basamak basamak** çıkar (örn. 7 → 12 → 17 → bugün).
Her basamakta tek soru: *"O yaşta elinden ne gelirdi? Bugün ne geliyor?"*
Fark **kullanıcı tarafından** söylenir; usta özetler, yerine koymaz.

Bu, planın en güçlü parçası: içgörü "sana şunu söyleyeyim"den değil,
kişinin kendi iki cevabını yan yana görmesinden doğar.

## G. Sağlıklı Yetişkin güç ölçüsü

```sql
healthy_adult_marks(conv, path, source, evidence TEXT, created TEXT)
```

Sağlıklı Yetişkin bir puan değil, **kanıt sayacı**dır: kullanıcı kendi
kendine sınır koyduğunda, ihtiyacını dile getirdiğinde, cezalandırıcı sese
karşı çıktığında bir iz düşer — hep kullanıcının kendi cümlesiyle.

Prompta tek satır:

> *Sağlıklı Yetişkin sesi bu görüşmede 4 kez göründü; en son: "bu sefer
> hayır dedim."*

**Sayı hedef değildir**, kota gösterilmez (sakin-derin ilkesi). Yalnız
kullanıcı isterse gösterilir.

---

## Çıkarılacak / azaltılacak

1. **Erken etiketleme.** Kanıt eşiği dolmadan mod adı geçmez. "Bu Kopuk
   Koruyucu" demek, tanımak değil kapatmaktır.
2. **Jargon gösterisi.** Mod adı bir kez ortak dil olarak kurulur, sonra
   kullanıcının kendi adlandırması tercih edilir ("o duvar", "o soğuk hâl").
3. **Mod sesini kullanıcıya dayatma.** Sandalyeye oturmak her zaman
   isteğe bağlıdır; "istemiyorum" tam bir cevaptır.
4. **Aynı anda çok mod.** Bir oturumda tek mod çalışılır.

## Çizilmemesi gereken çizgi

- **Sahte anı yasağı** — yaş/sahne yalnız kullanıcıdan.
- **Tanı yasağı** — mod klinik dikkat aracıdır, teşhis değil.
- **Kriz önceliği** — `safety_hold` varken tüm katman susar; sandalye ve
  imgeleme açılmaz.
- **Cezalandırıcı Ebeveyn sesi** yoğunluk tavanına tabidir ve asla
  kullanıcıya yönelik gerçek bir suçlamaya dönüşmez.

---

## Adım sıralaması

| # | Adım | Klinik etki | Emek | Bağımlılık |
|---|---|---|---|---|
| 1 | Mod/şema kataloğunu ayır + genişlet (A) | Yüksek | Düşük | — |
| 2 | `focus` fazı: aday sun + buton seçimi (B) | Çok yüksek | Orta | 1 |
| 3 | Köken yaşı + küçük hal (C) | Yüksek | Orta | 2 |
| 4 | Sandalyede mod sesi + empatik yüzleştirme (E) | Çok yüksek | Orta | 1,2 |
| 5 | Sınırlı yeniden ebeveynleme (D) | Yüksek | Orta | 3 |
| 6 | Yaş yaş büyütme + hal farkı (F) | Çok yüksek | Orta | 3 |
| 7 | Sağlıklı Yetişkin kanıt sayacı (G) | Orta-yüksek | Düşük | 1 |

**Kesme noktası:** 1-2 birlikte tek turda biter ve tek başına hissedilir
fark yaratır (dinleyen + aday sunan + seçtiren usta). 3-4-5 ikinci tur —
asıl yaşantısal iş burada. 6-7 üçüncü.

## Doğrulama

- **Aday sunma:** kanıt eşiği dolmadan mod adı çıkmamalı (kasıtlı test).
- **Seçim:** "hiçbiri" ve "şimdi değil" her zaman seçilebilmeli.
- **Sahte anı:** kullanıcının söylemediği yaş/sahne `schema_origin`'e
  **asla** yazılmamalı (kasıtlı test).
- **Empatik yüzleştirme:** yalnız-bedel veya yalnız-geçerlilik üreten yanıt
  reddedilmeli.
- **Güvenlik:** `safety_hold` varken sandalye/imgeleme/mod sesi açılmamalı,
  112 yolu değişmemeli.
- **Yoğunluk:** Cezalandırıcı Ebeveyn sesi tavan üstünde konuşturulmamalı.
- Mevcut 1182 Python testi yeşil kalmalı.
