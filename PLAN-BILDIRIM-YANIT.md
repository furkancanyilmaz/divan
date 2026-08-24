# Plan — WhatsApp Tarzı Bildirim Yanıtı (Tüm Ustalar için)

**Hedef:** Bildirimden doğrudan yanıt yazılabilsin; ustanın (terapist, felsefeci
ve ADHD koçu dahil) yanıtı hazır olunca aynı bildirime düşsün.

---

## 1. Platform gerçekleri (önce bunu netleştirelim)

| | Bildirimden yanıt yazma | Yanıtın bildirime düşmesi |
|---|---|---|
| **Android** | ✅ Tam destek (MessagingStyle + RemoteInput) — WhatsApp ile birebir | ✅ Aynı bildirim konuşma olarak güncellenir |
| **iOS** | ❌ Apple API'si buna izin vermiyor (WhatsApp iOS'ta da bildirimden yazamaz) | ✅ Yapılabilecek: "Cevapla" aksiyon butonu uygulamayı açar ve sohbete odaklanır; yanıt hazır olunca ayrı/güncellenmiş bildirim gelir |

iOS'ta en yakın deneyim: bildirime **"Cevapla"** butonu → uygulama açılır →
ilgili görüşme hazır → klavye odaklı. Bu Apple'ın platform sınırı, kod
eksikliği değil.

## 2. Mimari

### 2.1 Backend (freud-dev/server.py) — neredeyse hazır
- Bildirim yanıtı aslında sıradan bir mesaj: mevcut **`/api/chat`** dayanıklı
  kuyruğa yazar; güvenlik kapıları, yeniden deneme, misafir kapsamı ve retry
  mantığı aynen geçerli. **Yeni uç gerekmez.**
- Eklenecek küçük parça: **`/api/notification-context`** → aktif görüşme
  (varsa), usta adı, son istek kimliği ve son yanıt metni. Android'in bildirimi
  doğru başlıkla kurması ve yanıtı okuması için.
- Yanıt metni zaten `/api/chat-status` ile alınıyor (mevcut).

### 2.2 Android — tam WhatsApp akışı
1. **Yeni kanal** `divan_messages` (mesajlaşma, yüksek önem, ses).
2. **`ChatNotificationController`** (yeni sınıf):
   - `Notification.MessagingStyle`: konuşma başlığı = ustanın adı, kişi = usta.
   - `RemoteInput` ile **"Yanıtla"** aksiyonu (metin kutusu).
3. **`ChatReplyReceiver`** (yeni BroadcastReceiver):
   - RemoteInput metnini alır → gömülü Python'u uyandırır →
     **`/api/chat`** POST (yeni request_id) → kullanıcı mesajı dayanıklı
     kayda girer → `ResponseKeeperJobService.schedule()` ile arka plan koruması.
4. **`ResponseKeeperJobService`** genişletmesi:
   - İş bitince (IDLE) son durum için `/api/chat-status` çekilir → yanıt metni
     **aynı bildirime** `addMessage` ile eklenir ("yazıyor…" → yanıt).
   - Hata olursa kısa hata satırı bildirime yazılır.
   - Uygulama ön plandaysa bildirim gösterilmez (mevcut davranışa uygun).
5. **Derin bağlantı:** bildirime dokununca ilgili görüşme açılır
   (WebView'e `divanOpenConversation(id)` JS çağrısı).
6. **Ayar:** mevcut "yanıt hazır" bildirim tercihi genişletilir:
   *Her yanıt* / *yalnız uygulama kapalıyken* / *kapalı*.

### 2.3 iOS — platformun izin verdiği en iyi akış
- Bildirim kategorisi **`divan.chat`** + **"Cevapla"** aksiyonu:
  dokununca uygulama açılır, `userInfo` içindeki görüşme kimliğiyle sohbet
  ekrana gelir (WebView derin bağlantısı).
- Yanıt üretimi arka planda tamamlanırsa (mevcut background task akışı)
  yanıt metniyle bildirim **güncellenir/eklenir**.
- Dokümantasyonda açıkça belirtilir: iOS'ta bildirim içine metin yazmak
  Apple tarafından desteklenmiyor.

### 2.4 Web arayüzü (index.html)
- `divanOpenConversation(id)` derin bağlantı işleyicisi (Android + iOS).
- Bildirim tercihi arayüzü (yukarıdaki üç seçenek).
- Aktif görüşme yokken gelen "Yanıtla" yanıtı: kullanıcıya "önce bir görüşme
  aç" yönlendirmeli bildirim.

## 3. Ustalar için geçerli olması
- Bildirim başlığı/kişi = seçili usta (terapist, felsefeci, ADHD koçu — hepsi
  aynı `/api/chat` hattından geçer; ek iş yok).
- Yanıt, aktif görüşmeye kullanıcı mesajı olarak düşer; usta cevabı aynı
  bildirime gelir. Misafir modunda sunucu kapsamı aynen korur.

## 4. Uygulama sırası
1. Backend: `/api/notification-context` + Python testleri.
2. Android: kanal + MessagingStyle + RemoteInput + ChatReplyReceiver +
   ResponseKeeperJobService yanıt entegrasyonu + derin bağlantı.
3. iOS: kategori/aksiyon + derin bağlantı + yanıt bildirimi.
4. Web: ayar + derin bağlantı JS.
5. Canlı test: telefonda uçtan uca (önceki turda yaptığımız gibi:
   bildirimden yanıt yaz → usta cevabı bildirime düşsün).

## 5. Riskler / notlar
- Samsung/OEM batarya kısıtları: mevcut dayanıklı kuyruk + expedited job +
  exact alarm altyapısıyla aynı şekilde yönetilecek.
- Bildirim yanıtı da her zamanki güvenlik kapısından geçer (kriz metni
  bildirimden yazılsa bile sunucudaki koruma devrededir).
- iOS kısıtı kullanıcıya açıkça anlatılmalı.
