# Divan macOS — kalan eksikler ve plan

## Klinik döngü v2 (2026.08.13.17) — tamamlandı

Beş parçalı sürüm hem çekirdeğe hem native katmana işlendi
(`server.py` VERSION 2026.08.13.1):

1. **İçgörü Gelen Kutusu v2** — kanıt tarihleri, karşı örnekler, çürütme
   koşulu, "Emin değilim" kararı; "Hafızaya al / Özel tut / Sil" eylemleri.
   Otomatik onaylı hafıza kaldırıldı: mikro-notlar onay bekler, anılar
   yalnız açık `approved` ile belleğe girer, aynı alıntı iki kez kanıt
   sayılmaz.
2. **Seans nabzı + onarım** — anlaşılma/hedef/yöntem/tempo soruları,
   "kaçırdığım bir şey var mı", çalışma sonrası zarar kontrolü üçlüsü;
   onarıma "Burada bırakalım" ve mesaj üstü görünür tetik eklendi.
3. **Değişim + kötüleşme radarı** — kullanıcının seçtiği 3 ölçüm
   (`/api/measures`), deterministik radar durumları, 2 seanslık hatırlatma.
4. **Sandalye/imgeleme** — anında etki kaydı ve 24 saatlik gecikmiş etki
   kontrolü (`/api/work-followups`, `followup` eylemi).
5. **Psikiyatrist aktarım özeti** — tıbbi durum, güvenlik, hedef, yöntem
   etkileri bölümleri; bölüm bazlı paylaşım onayı ve ölçüm dahil etme.

Python 792 test, Swift 95 test geçiyor.

## Kalan eksikler


Durum: **45 API ucu** Swift'te bağlı değil. Ham sayı yanıltıcı; bunlar
aslında **14 kullanıcı özelliği** + arka plan altyapısı.

Bu turda eklenenler (artık listede değil): Hakkımda, Defter (notlar +
formülasyonlar), Mektuplar + sevkler, Rüya defteri, tam metin arama,
raptiyeleme, seans özeti, geri butonu, üstte ayar butonu.

---

## A grubu — Kullanıcının doğrudan kullandığı özellikler

Öncelik sırasıyla. "İş" sütunu kabaca emek; hepsi Python tarafı hazır
olduğu için yalnızca Swift katmanı gerekiyor.

| # | Özellik | Uçlar | İş | Neden değerli |
|---|---|---|---|---|
| A1 | **🏛 Konsey** — 2-4 usta aynı konuyu tartışır | `/api/council` | Orta | Divan'ın en özgün fikri; tek ekranda çok sesli tartışma |
| A2 | **⚖️ İki Usta, Tek Soru** — aynı soruya iki ekolden yanıt | `/api/duet` | Orta | Uygulamanın tezini tek karede anlatan özellik |
| A3 | **🧭 Kime gitsem?** — derdini yaz, usta önerilsin | `/api/triage` | Düşük | Yeni kullanıcı için doğal giriş kapısı |
| A4 | **🖋 Altını çizdiklerim** — cümle seçip deftere kaydet | `/api/highlight`, `/highlight/delete`, `/highlights` | Orta | Metin seçimi + kalıcı alıntı defteri |
| A5 | **🎓 Süpervizyon** — biten seansı ustayla incele | `/api/supervise` | Düşük | Mevcut seanstan yeni bir ders oturumu açar |
| A6 | **📖 Kavram defteri** — derslerde geçen kavramlar | `/api/concepts` | Düşük | Salt okunur liste, arama kutusu |
| A7 | **🧭 Yolculuğum** — her ustanın gözünden portren | `/api/journey` | Düşük | AI çağrısı yok, mevcut formülasyonları okur |
| A8 | **🧠 Hafıza** — ustaların onayladığın kalıcı bilgileri | `/api/memories`, `/memory`, `/memory/delete` | Orta | Kullanıcı hafızayı görüp silebilmeli (gizlilik) |
| A9 | **🎯 Hedefler + kontrol noktaları** | `/api/goal`, `/api/checkin`, `/api/progress` | Yüksek | Seanslar arası süreklilik; asıl terapötik değer |
| A10 | **🎯 Pratik laboratuvarı** | `/api/practice-lab` | Yüksek | Yaşantısal çalışma; Çalışmalar ekranına 5. modül |
| A11 | **🗺 Seans rotası (therapy-map)** | `/api/therapy-map` | Orta | Sunucu zaten üretiyor, native'de hiç gösterilmiyor |
| A12 | **💾 Yedek / geri yükleme / dışa aktarma** | `/api/backup`, `/restore`, `/restore-undo`, `/export-json`, `/transfer/*` | Yüksek | Veri güvenliği; dosya seçici + onay akışı |
| A13 | **🗑 Tüm verileri sil** | `/api/delete-all` | Düşük | Gizlilik gereği; yazarak onay ister |
| A14 | **Toplu arşiv/sil** | `/api/conversations/batch` | Düşük | Listede çoklu seçim |

## B grubu — Arka plan / sistem uçları

Kullanıcıya ekran olarak görünmez ama davranışı iyileştirir.

- `/api/jobs`, `/api/job/retry` — arka plan işleri (not/mektup üretimi)
  durumunu göstermek ve başarısızları yeniden denemek
- `/api/provider/models`, `/api/provider-test` — Ayarlar'da model listesini
  sunucudan çekmek ve bağlantıyı test etmek
- `/api/diagnostics` — sorun bildirimi için tanı raporu
- `/api/session-meta`, `/session-pulse`, `/session-rationale`,
  `/process-target`, `/focus-route`, `/ambivalence`, `/repair`,
  `/safety-hold/review`, `/note-control`, `/cases`, `/refer`,
  `/living-map/backfill`, `/session-work`, `/unlock` — klinik altyapı;
  bir kısmı zaten Çalışmalar ekranının içinden dolaylı kullanılıyor

---

## Önerilen sıra

**Tur 1 — hızlı kazanımlar (hepsi düşük iş, tek oturumda biter)**
A3 (Kime gitsem) · A5 (Süpervizyon) · A6 (Kavramlar) · A7 (Yolculuğum) ·
A13 (Tümünü sil)

Dördü salt okunur liste ya da tek çağrı; mevcut `LibraryViews.swift`
kalıbı doğrudan yeniden kullanılır.

**Tur 2 — Divan'ın imza özellikleri**
A1 (Konsey) · A2 (İki Usta)

İkisi de yeni sohbet türü açıyor; konsey `submode=konsey` ile mevcut
sohbet altyapısını kullanır, duet paralel iki çağrı yapar.

**Tur 3 — kalıcı değer**
A8 (Hafıza) · A4 (Altını çizdiklerim) · A11 (Seans rotası)

**Tur 4 — ağır işler**
A9 (Hedefler) · A12 (Yedek/aktarım) · A10 (Pratik laboratuvarı)

A12 dosya sistemi ve geri alma akışı gerektirir; A9 ve A10 yeni ekran
aileleri. Bunlar ayrı ve dikkatli ele alınmalı.

**Tur 5 — B grubu altyapı**
Önce `/api/provider/models` + `/provider-test` (Ayarlar'ı gerçekten
kullanışlı yapar), sonra `/api/jobs` + `/job/retry`.

---

## Her tur için değişmeyen iş kalemleri

1. Wire modeli → `Core/…Payloads.swift`
2. Domain modeli → `Core/…Models.swift`
3. API metodu → `Core/…APIClient.swift` (uzantı)
4. Protokol satırı → `UI/Services/DivanUIDataSource.swift`
5. Uygulama → `App/CoreDivanUIDataSource.swift`
6. Durum + eylem → `UI/ViewModels/DivanViewModel.swift`
7. Ekran → `UI/Views/…`
8. Hedef enum + menü + yönlendirme → `DivanRootView.swift`
9. **Üç test sahtesini güncelle** (protokole metot eklenince derleme kırılır)
10. `swift test` (81 test) + `swift build`

## Notlar

- Python tarafı hepsinde hazır; sunucuya dokunmak gerekmiyor
  (raptiyelemede gerekmişti, orada `pinned_at` kolonu eklendi).
- Klinik karar View'a yazılmaz — bkz. `KATKI.md` ve `WorkspaceSafety`.
- Paylaşılan metin `DivanStrings`'e girer.
