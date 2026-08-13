# Üçüncü taraf bileşenler

Bu depoda dağıtılan üçüncü taraf bileşenler ve lisansları:

## qrcodegen.py

- Proje: QR Code generator library (Python)
- Yazar: Project Nayuki
- Lisans: MIT
- Kaynak: https://www.nayuki.io/page/qr-code-generator-library
- Dosya: `core/qrcodegen.py` (lisans başlığı dosya içinde korunur)

## Usta portreleri (depoda tutulmaz)

Portre görselleri bu depoya işlenmez. Uygulama çalıştırılmadan önce
[`core/tools/fetch_commons_portraits.py`](core/tools/fetch_commons_portraits.py)
aracı indirir. Araç yalnızca Wikimedia Commons üzerindeki kamu malı (public
domain), CC0, CC BY ve CC BY-SA dosyaları kabul eder ve her dosyanın
atıf bilgisini `assets/portraits/manifest.json` içinde saklar. Wikipedia
"adil kullanım" görsellerine veya rastgele web fotoğraflarına düşmez.

**Yaşayan kişiler:** Hayatta olan kişiler (psikoterapistler, düşünürler,
araştırmacılar) uygulamada gerçek adları, biyografileri ve fotoğraflarıyla
yer almaz. Bunlar, yöntemi ve düşünsel geleneği koruyan ve kurgusal
olduğu açıkça belirtilen özgün karakterlerle temsil edilir; kişilik
hakları, tanıtım hakları ve telif yasalarıyla çakışmamak için gerçek
kişi benzerliği taşıyan hiçbir görsel kullanılmaz (yerel temsili büst
kullanılır). Vefat etmiş kişiler için yalnız uygun lisanslı tarihsel
görseller kullanılır.

## Gömülü Python çalışma zamanları (depoda tutulmaz)

iOS uygulamasının `Vendor/Python.xcframework` kopyası ve Windows
dağıtımının gömülü Python'u üçüncü taraf CPython dağıtımlarıdır
(Python Software Foundation lisansı). Depo boyutunu korumak için depoda
tutulmaz; ilgili platformun README'sindeki paketleme betikleriyle yeniden
üretilir.

## Diğer

- Uygulama simgesi ve tanıtım görseli projeye aittir.
- Web arayüzü (`core/index.html`) dış CDN/font kullanmaz; tümü tek dosyada
  yereldir.
