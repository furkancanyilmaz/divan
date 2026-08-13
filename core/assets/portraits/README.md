# Portreler

Usta portre görselleri telif nedeniyle depoya işlenmez.

İndirmek için:

```bash
cd core
python3 tools/fetch_commons_portraits.py
```

Araç yalnızca Wikimedia Commons üzerindeki kamu malı (public domain),
CC0, CC BY ve CC BY-SA dosyaları kabul eder; her görselin atıf bilgisi
`manifest.json` içinde saklanır ve uygulamada gösterilir. Wikipedia
"adil kullanım" görselleri veya rastgele web fotoğrafları kullanılmaz.

**Yaşayan kişilerin gerçek fotoğrafları indirilmez** — kurgusal
karakterler için yerel temsili büst kullanılır. Ayrıntı:
`../THIRD_PARTY_NOTICES.md`
