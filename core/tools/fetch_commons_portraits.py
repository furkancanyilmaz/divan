#!/usr/bin/env python3
"""Fetch reusable master portraits and their attribution from Wikimedia Commons.

The script intentionally accepts only public-domain, CC0, CC BY and CC BY-SA
files which are actually hosted on Wikimedia Commons. It never falls back to
Wikipedia fair-use images or arbitrary web photographs.
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT, "assets", "portraits")
MANIFEST_PATH = os.path.join(OUTPUT_DIR, "manifest.json")
USER_AGENT = (
    "DivanPortraitBuilder/2026.07.26 "
    "(local educational app; Wikimedia attribution retained)"
)
THUMB_WIDTH = 320
PLACEHOLDER_FILE = "representative_bust.jpg"
PLACEHOLDER_LICENSE_PAGE = "https://openai.com/policies/terms-of-use/"

# Exact English Wikipedia titles are used only to find the corresponding
# Commons file. The downloaded manifest records the Commons file page itself.
PAGES = {
    "freud": "Sigmund Freud",
    "jung": "Carl Jung",
    "klein": "Melanie Klein",
    "winnicott": "Donald Winnicott",
    "bowlby": "John Bowlby",
    "ferenczi": "Sándor Ferenczi",
    "kohut": "Heinz Kohut",
    "rogers": "Carl Rogers",
    "beck": "Aaron Beck",
    "frankl": "Viktor Frankl",
    "perls": "Fritz Perls",
    "yalom": "Irvin D. Yalom",
    "young": "Jeffrey Young (psychologist)",
    "adler": "Alfred Adler",
    "horney": "Karen Horney",
    "erickson": "Milton H. Erickson",
    "berne": "Eric Berne",
    "satir": "Virginia Satir",
    "linehan": "Marsha M. Linehan",
    "hayes": "Steven C. Hayes",
    "lacan": "Jacques Lacan",
    "bion": "Wilfred Bion",
    "kernberg": "Otto F. Kernberg",
    "fonagy": "Peter Fonagy",
    "ellis": "Albert Ellis",
    "insoo_berg": "Insoo Kim Berg",
    "white": "Michael White (psychotherapist)",
    "minuchin": "Salvador Minuchin",
    "bowen": "Murray Bowen",
    "greenberg": "Leslie Greenberg (psychologist)",
    "miller": "William R. Miller (psychologist)",
    "shapiro": "Francine Shapiro",
    "sue_johnson": "Sue Johnson (psychologist)",
    "socrates": "Socrates",
    "aristotle": "Aristotle",
    "epictetus": "Epictetus",
    "epicurus": "Epicurus",
    "farabi": "Al-Farabi",
    "ibn_sina": "Avicenna",
    "ibn_rushd": "Averroes",
    "spinoza": "Baruch Spinoza",
    "kierkegaard": "Søren Kierkegaard",
    "nietzsche": "Friedrich Nietzsche",
    "wittgenstein": "Ludwig Wittgenstein",
    "sartre": "Jean-Paul Sartre",
    "beauvoir": "Simone de Beauvoir",
    "camus": "Albert Camus",
    "arendt": "Hannah Arendt",
    "merleau_ponty": "Maurice Merleau-Ponty",
    "plato": "Plato",
    "marcus_aurelius": "Marcus Aurelius",
    "confucius": "Confucius",
    "descartes": "René Descartes",
    "hume": "David Hume",
    "kant": "Immanuel Kant",
    "foucault": "Michel Foucault",
                            "machiavelli": "Niccolò Machiavelli",
    "hobbes": "Thomas Hobbes",
    "la_rochefoucauld": "François de La Rochefoucauld",
    "de_sade": "Marquis de Sade",
    "schopenhauer": "Arthur Schopenhauer",
    "cioran": "Emil Cioran",
    "carl_schmitt": "Carl Schmitt",
                    "steve_jobs": "Steve Jobs",
}

# When a biography has no page image, or its page image is less suitable than
# an openly licensed portrait/bust, use this reviewed Commons file instead.
FILES = {
    "jung": "UBH Portr BS Jung CG 1875 6 (cropped).jpg",
    "winnicott": "Donald Woods Winnicott.jpg",
    "bowlby": "The Bowlby-Ainsworth Award.jpg",
    "minuchin": "Salvador Minuchin (2013).jpg",
    "farabi": "Al-Farabi Statue (5607260952).jpg",
    "ibn_sina": "Avicenna statue.jpg",
    "ibn_rushd": "Statue of Averroes in Córdoba, Spain.jpg",
    "marcus_aurelius": "Marcus Aurelius Louvre MR561 n02.jpg",
    "foucault": "Michel Foucault c. 1968.jpg",
    "la_rochefoucauld": "François de La Rochefoucauld.jpg",
    "cioran": "Emil Cioran, filósofo y escritor.jpg",
            # David Christian's biography has no page image. This reviewed Commons
    # video thumbnail shows him alone, so no ambiguous group-photo crop is
    # needed; MediaWiki supplies the reproducible JPEG thumbnail.
    "steve_jobs": "Steve Jobs Headshot 2010 (cropped 4).jpg",
}


def request_json(base_url, params):
    url = base_url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise
            if attempt == 4:
                raise
            delay = int(exc.headers.get("Retry-After") or 0) or 2 ** attempt
            time.sleep(min(30, max(1, delay)))


def request_bytes(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read(), response.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise
            if attempt == 4:
                raise
            delay = int(exc.headers.get("Retry-After") or 0) or 2 ** attempt
            time.sleep(min(30, max(1, delay)))


def plain_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<br\s*/?>", " · ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def metadata_value(metadata, key):
    value = metadata.get(key) or {}
    return plain_text(value.get("value"))


def accepted_license(name):
    normalized = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
    return (
        normalized.startswith("public domain")
        or normalized.startswith("cc0")
        or normalized.startswith("cc by ")
        or normalized.startswith("cc by sa ")
    )


def chunks(values, size=40):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def resolved_title(title, aliases):
    seen = set()
    while title in aliases and title not in seen:
        seen.add(title)
        title = aliases[title]
    return title


def wikipedia_page_images():
    aliases = {}
    page_by_title = {}
    titles = list(dict.fromkeys(PAGES.values()))
    for group in chunks(titles):
        data = request_json(
            "https://en.wikipedia.org/w/api.php",
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "titles": "|".join(group),
                "prop": "pageimages",
                "piprop": "name",
            },
        )
        query = data.get("query", {})
        for mapping in query.get("normalized", []) + query.get("redirects", []):
            aliases[mapping["from"]] = mapping["to"]
        for page in query.get("pages", []):
            page_by_title[page.get("title")] = page
    result = {}
    for master_id, title in PAGES.items():
        title = resolved_title(title, aliases)
        page = page_by_title.get(title) or {}
        result[master_id] = {
            "title": page.get("title") or title,
            "file_name": (
                FILES.get(master_id) or
                (None if page.get("missing") else page.get("pageimage"))
            ),
        }
    return result


def file_key(title):
    return str(title or "").replace("_", " ").casefold()


def commons_image_infos(file_names):
    result = {}
    unique = list(dict.fromkeys(file_names))
    for group in chunks(unique):
        data = request_json(
            "https://commons.wikimedia.org/w/api.php",
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "titles": "|".join("File:" + name for name in group),
                "prop": "imageinfo",
                "iiprop": "url|mime|extmetadata",
                "iiurlwidth": str(THUMB_WIDTH),
            },
        )
        for page in data.get("query", {}).get("pages", []):
            info = (page.get("imageinfo") or [None])[0]
            if not page.get("missing") and info:
                result[file_key(page.get("title"))] = (
                    page.get("title"), info
                )
    return {
        name: result.get(file_key("File:" + name))
        for name in unique
    }


def extension_for_mime(mime):
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(str(mime or "").lower())


def save_one(master_id, resolved_title, commons_title, info, previous=None):
    metadata = info.get("extmetadata") or {}
    license_name = metadata_value(metadata, "LicenseShortName")
    if not accepted_license(license_name):
        return None, "Lisans izin listesinde değil: {} ({})".format(
            license_name or "belirsiz", commons_title
        )
    download_url = info.get("thumburl") or info.get("url")
    if not download_url:
        return None, "İndirilebilir görsel URL'si yok: " + commons_title
    mime = info.get("thumbmime") or info.get("mime")
    extension = extension_for_mime(mime)
    body = None
    previous_file = str((previous or {}).get("file") or "")
    if (previous and previous.get("commons_title") == commons_title and
            previous_file and
            os.path.isfile(os.path.join(OUTPUT_DIR, previous_file))):
        file_basename = previous_file
        mime = previous.get("mime") or mime
        extension = os.path.splitext(file_basename)[1]
    else:
        body, response_mime = request_bytes(download_url)
        mime = info.get("thumbmime") or response_mime or info.get("mime")
        extension = extension_for_mime(mime)
    if not extension:
        return None, "Desteklenmeyen görsel biçimi: {}".format(mime)
    if body is not None:
        file_basename = master_id + extension
        with open(os.path.join(OUTPUT_DIR, file_basename), "wb") as output:
            output.write(body)
    encoded_title = urllib.parse.quote(
        commons_title.replace(" ", "_"), safe="():,_-."
    )
    description_url = "https://commons.wikimedia.org/wiki/" + encoded_title
    return {
        "file": file_basename,
        "mime": mime,
        "source_kind": "wikimedia_commons",
        "is_placeholder": False,
        "commons_title": commons_title,
        "source_page": description_url,
        "wikipedia_title": resolved_title,
        "artist": metadata_value(metadata, "Artist") or "Bilinmiyor",
        "credit": metadata_value(metadata, "Credit"),
        "license": license_name,
        "license_url": metadata_value(metadata, "LicenseUrl"),
        "attribution": metadata_value(metadata, "Attribution"),
        "downloaded_from": download_url,
    }, None


def placeholder_entry(master_id, resolved_title):
    """Describe the clearly non-likeness fallback bundled with Divan.

    A missing openly licensed portrait must never be replaced with a photo of
    a similarly named person. The shared faceless bust is deliberately
    non-identifying and the runtime labels it as a representative image.
    """
    return {
        "file": PLACEHOLDER_FILE,
        "mime": "image/jpeg",
        "source_kind": "local_placeholder",
        "is_placeholder": True,
        "commons_title": "",
        "source_page": PLACEHOLDER_LICENSE_PAGE,
        "wikipedia_title": resolved_title,
        "artist": "OpenAI görsel üretimi · Divan için düzenlendi",
        "credit": (
            "Temsili büst; kişiye ait gerçek fotoğraf veya benzerlik değildir."
        ),
        "license": "Divan yerel varlığı",
        "license_url": PLACEHOLDER_LICENSE_PAGE,
        "attribution": "Divan temsili büstü",
        "downloaded_from": "",
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as current:
            previous = (json.load(current).get("portraits") or {})
    except (OSError, ValueError, TypeError):
        previous = {}
    manifest = {}
    missing = {}
    print("Wikipedia portre eşleştirmeleri alınıyor…", flush=True)
    page_images = wikipedia_page_images()
    file_names = [
        record["file_name"] for record in page_images.values()
        if record["file_name"]
    ]
    print("Commons lisans bilgileri alınıyor…", flush=True)
    commons = commons_image_infos(file_names)
    for index, master_id in enumerate(PAGES, start=1):
        page = page_images[master_id]
        file_name = page["file_name"]
        try:
            if not file_name:
                entry, reason = None, (
                    "Wikipedia sayfasında portre yok: " + page["title"]
                )
            elif not commons.get(file_name):
                entry, reason = None, (
                    "Sayfa görseli Commons üzerinde değil: " + file_name
                )
            else:
                commons_title, info = commons[file_name]
                entry, reason = save_one(
                    master_id, page["title"], commons_title, info,
                    previous.get(master_id)
                )
                time.sleep(0.12)
        except Exception as exc:
            entry, reason = None, "{}: {}".format(type(exc).__name__, exc)
        if entry:
            manifest[master_id] = entry
            print("[{}/{}] {}: {}".format(
                index, len(PAGES), master_id, entry["commons_title"]
            ), flush=True)
        else:
            missing[master_id] = reason
            print("[{}/{}] {}: ATLANDI — {}".format(
                index, len(PAGES), master_id, reason
            ), flush=True)
    # “Hakikat” kurgusal bir düşünürdür. Ayrıca Commons'ta doğrulanmış açık
    # lisanslı portresi bulunamayan gerçek kişiler için yanlış bir fotoğraf
    # kullanmak yerine aynı açıkça temsili, yüzsüz yerel büst gösterilir.
    fallback_ids = set(missing)
    fallback_ids.add("truth")
    for master_id in sorted(fallback_ids):
        title = (
            "Hakikat (kurgusal düşünür)"
            if master_id == "truth"
            else page_images[master_id]["title"]
        )
        manifest[master_id] = placeholder_entry(master_id, title)
    document = {
        "schema_version": 1,
        "generated_from": (
            "Wikimedia Commons ve Divan temsili yerel varlıkları"
        ),
        "portrait_count": len(manifest),
        "portraits": manifest,
        "missing": missing,
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as output:
        json.dump(document, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
    print("\n{} görsel kaydedildi; {} kayıt temsili büst kullanıyor.".format(
        len(manifest), len(fallback_ids)
    ))
    return 0 if manifest else 1


if __name__ == "__main__":
    sys.exit(main())
