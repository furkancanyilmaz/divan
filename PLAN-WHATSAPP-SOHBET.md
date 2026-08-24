# Plan — WhatsApp Tarzı Zamanlanmış Usta Mesajları

**Hedef:** "1 dk sonra uyar" dendiğinde sistem, o ana özel bir **AI mesajı**
önceden üretsin (koç/terapist/felsefeci kişiliğinde); mesaj sohbette
**bildirim gelene kadar görünmesin**, süre dolunca hem WhatsApp gibi
**portreli bildirim** olarak gelsin hem de sohbetin altına otomatik eklensin.
Bildirimden yanıt yazılınca yanıt sohbete düşsün, AI cevabı arka planda
üretilip yine sohbete ve bildirime gelsin. Kullanıcı yazdıktan sonra
uygulamayı kapatsa bile her şey çalışsın.

---

## 1. Çekirdek fikir: "Zamanlanmış gizli mesaj"

- Mesaj, hatırlatıcı kurulduğu anda **arka planda üretilir** ama
  `messages` tablosuna değil, yeni **`scheduled_messages`** tablosuna yazılır.
  Böylece sohbet listesinde görünmez (kullanıcı isteği: "bildirim gelene
  kadar listelenmesin").
- Süre dolduğunda "açığa çıkarma" (reveal) işlemi mesajı `messages`
  tablosuna taşır → sohbetin altında belirir; aynı anda bildirim de
  o mesajın metniyle gider.
- Üretim önceden yapıldığı için bildirim **saniyesi saniyesine** zamanında
  ve tam metinle gelir (üretim süresi bildirimi geciktirmez).

## 2. Backend (freud-dev/server.py)

1. **Yeni tablo `scheduled_messages`**: id, conv, therapist, content, status
   (`generating` → `ready` → `revealed` / `discarded`), due_at, revealed_at,
   is_guest, created/updated. (Eski veritabanları için otomatik migration.)
2. **Yeni dayanıklı iş türü `scheduled_message`**: model çağrısını mevcut
   kuyruk altyapısıyla yapar. İstem (prompt):
   - Kişilik = görüşmenin ustası (koç için "şefkatli, akılcı, kanıta dayalı
     ADHD koçluğu"; terapist/felsefeci kendi persona + ses sözleşmesiyle).
   - Bağlam = o görüşmenin özeti/notları + görev metni + "şu an süre doldu"
     çerçevesi (örn. koç: *"Kitap okumak istiyordun… şimdi 5 dakikayla
     başlamak ister misin?"*).
   - Güvenlik kapıları aynen geçerli.
3. **Hatırlatıcı kurulunca otomatik bağlantı**:
   - Koç sohbetinden gelen hatırlatıcı (`source_conv` dolu) → birlikte bir
     `scheduled_messages` satırı + üretim işi kuyruğa.
   - Panelden kurulan ve bir görüşmeye bağlı hatırlatıcı → aynı yol.
   - Hatırlatıcı silinir/yanıtlanırsa → bekleyen mesaj `discarded` olur
     (boşa üretim önlenir; üretim tamamlanmışsa iptal edilir).
4. **Yeni uç `/api/reminders/reveal`** (idempotent):
   - Süresi gelen hatırlatıcı için çağrılır; mesajı `messages`'a taşır
     (sohbetin altına eklenir), hatırlatıcıyı `due`→`notified` yapar.
   - Döner: mesaj metni + usta adı + portre URL'si + görüşme id.
   - Aynı hatırlatıcı için ikinci çağrı aynı sonucu verir (çift bildirim yok).
   - Üretim hâlâ sürüyorsa: genel "süren doldu" metniyle reveal; üretim
     bitince bildirim **güncellenir** ve mesaj sohbete eklenir.
5. Testler: tablo/migration, üretim işi, reveal idempotansı, iptal,
   misafir kapsamı.

## 3. Android (WhatsApp deneyimi)

1. **Alarm ateşlenince** (ReminderReceiver, uygulama kapalı olsa bile):
   - Gömülü sunucuyu uyandırır → `/api/reminders/reveal` çağırır.
   - Aldığı metinle **MessagingStyle bildirimi**: ustanın **portresi**
     (yerel sunucudan çekilir veya pakete gömülü avatar seti), mesaj,
     konuşma başlığı = usta adı, altında **"Yanıtla"** kutusu.
2. **Bildirimden yanıt** (mevcut altyapı): yanıt `/api/chat`'e gider →
   dayanıklı kuyruk → sohbete kullanıcı mesajı düşer → AI cevabı arka
   planda üretilir → `ResponseKeeperJobService` tamamlanınca **aynı
   bildirime** cevap eklenir (WhatsApp konuşma görünümü). Kullanıcı
   uygulamayı açarsa sohbetin altında her şey sıralı durur.
3. Bildirime dokununca ilgili görüşme açılır (mevcut derin bağlantı).
4. Terapist ve felsefeci yanıtları da aynı bildirim akışını kullanır
   (zaten aynı `/api/chat` hattı).

## 4. Web arayüzü (uygulama açıkken)

- 20 sn'lik yoklama, süresi gelen "zamanlanmış mesajlı" hatırlatıcıyı
  görünce `/api/reminders/reveal` çağırır → mesaj açık olan sohbette
  **otomatik alta eklenir** + kısa bildirim/toast.
- Panelde mesaj durumu: "mesajın hazırlanıyor… / yazıldı · şu saatte
  gelecek".
- Yanıt butonları (Yaptım/Yapamadım/Ertele) aynen kalır; "Ertele" mesajı
  da yeniden zamanlar.

## 5. Sıra (uygulama adımları)

1. Backend: `scheduled_messages` + üretim işi + reveal ucu + testler.
2. Android: alarm → reveal → portreli WhatsApp bildirimi (+ yanıt akışı
   doğrulaması).
3. Web: açık sohbette otomatik ekleme + panel durumları.
4. Telefonda uçtan uca canlı test: koça "1 dk sonra uyar" → uygulamayı
   kapat → 1. dakikada portreli bildirim → bildirimden yanıt → sohbette
   ve bildirimde karşılıklı mesajlaşma.

## 6. Bilinen sınırlar / notlar

- **iOS**: Apple bildirimde metin yazmaya izin vermiyor; orada "Cevapla"
  butonu uygulamayı açar (önceki plandaki gibi). Zamanlanmış mesaj +
  reveal aynen çalışır.
- Üretim için model çağrısı kullanıldığından, sağlayıcı kapalıysa reveal
  genel metinle düşer, üretim bitince bildirim güncellenir (kullanıcı
  bilgilendirilir).
- Gizlilik: üretim yalnız o görüşmenin bağlamını kullanır; misafir
  kapsamı aynen korunur.
