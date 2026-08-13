# Windows dağıtımı

Windows için Divan, "taşınabilir klasör" biçiminde dağıtılır: gömülü Python
çalışma zamanı + çekirdek kopyası + başlatıcı. Bu depoda yalnız **kaynak**
tutulur; çalışma zamanı ve veritabanı depoya girmez.

## Depodaki içerik

- `DIVAN_BASLAT.bat` — çift tık başlatıcı. Gömülü Python'u kullanır, yerel
  model (LMStudio) varsayılanlıdır ve bulut anahtarlarını bilerek temizler.

## Paket nasıl üretilir

1. [python.org](https://www.python.org/downloads/windows/) adresinden
   "Windows embeddable package" (ör. Python 3.12, 64-bit) indirin.
2. Klasör düzenini kurun:

   ```
   Divan/
   ├── DIVAN_BASLAT.bat
   └── Sistem_Dosyalari/
       ├── python/          ← gömülü Python (python.exe, DLL, stdlib)
       ├── server.py        ← core/server.py kopyası
       ├── index.html       ← core/index.html kopyası
       └── assets/          ← core/assets (portreler hariç; bkz. THIRD_PARTY)
   ```

3. Portreler depoda yoktur; istenirse
   `core/tools/fetch_commons_portraits.py` çalıştırılıp
   `assets/portraits/` buraya kopyalanır (lisansı uygun kaynaklardan).
4. Klasörü ZIP'leyin; kullanıcı her yerde açıp çift tıklar.

## Notlar

- Başlatıcı yalnız yerel model (LMStudio) kullanır; çevrimiçi sağlayıcı
  istenirse uygulama içi Ayarlar'dan eklenir.
- Veriler uygulama veri klasöründe saklanır; paylaşılan sürümlerde
  kişisel veri bulunmaz.
