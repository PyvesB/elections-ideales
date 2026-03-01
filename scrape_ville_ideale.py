#!/usr/bin/env python3
"""
Scraper for ville-ideale.fr town ratings.

Builds the list of politically classified communes from 2020 municipal
election results (first and second round), constructs their ville-ideale.fr
URL, scrapes ratings, and enriches with political data.

Fetches pages using tls_client with a Chrome TLS fingerprint and sends the
sijs() JS callback after each page to avoid bot detection. Works in batches
of 95 pages; between batches, toggles Wi-Fi off/on to get a fresh IP from
the mobile hotspot.

Usage:
    python3 scrape_ville_ideale.py              # Fetch missing pages + build JSON
    python3 scrape_ville_ideale.py --wifi       # Reset Wi-Fi between batches for fresh IP
    python3 scrape_ville_ideale.py --delay 5    # Custom delay (seconds)
"""

import csv
import json
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

# --- Configuration -----------------------------------------------------------

BASE_URL = "https://www.ville-ideale.fr"
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "villes_ratings.json"
HTML_DIR = SCRIPT_DIR / "html_pages"
T1_FILE = SCRIPT_DIR / "2020-05-18-resultats-communes-de-1000-et-plus.txt"
T1_URL = "https://www.data.gouv.fr/fr/datasets/r/5129e7cf-2999-4eaf-8dd7-3bcda37bd0a3"
T2_FILE = SCRIPT_DIR / "2020-06-29-resultats-t2-communes-de-1000-hab-et-plus.txt"
T2_URL = "https://www.data.gouv.fr/fr/datasets/r/e7cae0aa-5e36-4370-b724-6f233014d0d6"

DEFAULT_DELAY = 3          # Base delay between requests (seconds)
MAX_CONSECUTIVE_ERRORS = 5 # Abort after this many consecutive errors
BATCH_SIZE = 100           # Pages per batch (server bans at ~101)
WIFI_INTERFACE = "en0"     # macOS Wi-Fi interface (see: networksetup -listallhardwareports)

# Map French category names to JSON keys
CATEGORY_MAP = {
    "Environnement": "environnement",
    "Transports": "transports",
    "Sécurité": "securite",
    "Santé": "sante",
    "Sports et loisirs": "sports_et_loisirs",
    "Culture": "culture",
    "Enseignement": "enseignement",
    "Commerces": "commerces",
    "Qualité de vie": "qualite_de_vie",
}


# Map nuance politique codes to famille (political family)
# See https://www.legifrance.gouv.fr/download/pdf/circ?id=44929
NUANCE_TO_FAMILLE = {
    "LCOM": "Gauche",
    "LDIV": "Courants politiques divers",
    "LDLF": "Droite",
    "LDVC": "Centre",
    "LDVD": "Droite",
    "LDVG": "Gauche",
    "LECO": "Courants politiques divers",
    "LEXD": "Extrême droite",
    "LEXG": "Extrême gauche",
    "LFI": "Gauche",
    "LGJ": "Courants politiques divers",
    "LLR": "Droite",
    "LMDM": "Centre",
    "LRDG": "Gauche",
    "LREG": "Courants politiques divers",
    "LREM": "Centre",
    "LRN": "Extrême droite",
    "LSOC": "Gauche",
    "LUC": "Centre",
    "LUD": "Droite",
    "LUDI": "Centre",
    "LUG": "Gauche",
    "LVEC": "Gauche",
}

# Nuances to exclude (no political classification)
UNCLASSIFIED_NUANCES = {"LNC", "NC", ""}


# --- Slug construction -------------------------------------------------------

def commune_name_to_slug(name: str) -> str:
    """Convert a commune name to URL slug.

    Examples:
        Antony -> antony
        Saint-Germain-En-Laye -> saint-germain-en-laye
        L'Haÿ-Les-Roses -> l-hay-les-roses
        Épinay-Sur-Orge -> epinay-sur-orge
    """
    slug = name.lower()
    # Decompose accented characters and strip combining marks
    slug = unicodedata.normalize("NFD", slug)
    slug = "".join(c for c in slug if unicodedata.category(c) != "Mn")
    # Replace apostrophes and spaces with hyphens
    slug = slug.replace("\u2019", "-").replace("'", "-").replace(" ", "-")
    # Remove anything that isn't alphanumeric or hyphen
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    # Collapse multiple hyphens and strip edges
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def insee_to_url_code(code: str) -> str:
    """Convert 5-char INSEE code to the numeric form used in URLs.

    03310 -> 3310, 92002 -> 92002, 2A004 -> 2A004
    """
    if code[:2].upper() in ("2A", "2B"):
        return code[:2].upper() + code[2:]
    return str(int(code))


def build_slug(nom_commune: str, cog_commune: str) -> str:
    """Build the full ville-ideale URL slug from CSV fields."""
    return f"{commune_name_to_slug(nom_commune)}_{insee_to_url_code(cog_commune)}"


# --- Data file download ------------------------------------------------------

def ensure_election_files() -> None:
    """Download election result files from data.gouv.fr if not present."""
    for path, url in [(T1_FILE, T1_URL), (T2_FILE, T2_URL)]:
        if path.exists():
            continue
        print(f"Downloading {path.name}...")
        result = subprocess.run(
            ["curl", "-sL", "-o", str(path), url],
            timeout=120,
        )
        if result.returncode != 0 or not path.exists():
            print(f"  ERROR: failed to download {path.name}", file=sys.stderr)
            sys.exit(1)
        print(f"  Saved ({path.stat().st_size:,} bytes)")


# --- Election results loading ------------------------------------------------

def _parse_wide_row(row: list[str], vote_field: str) -> tuple[str | None, float]:
    """Extract the winning list's nuance from a wide-format election row.

    Repeating candidate blocks of 12 columns start at index 18.
    vote_field is the index offset within each block for the sort key:
      - 11 for % Voix/Exp (T1, to check >50%)
      - 9  for Voix (T2, absolute votes for the winner)
    Returns (nuance, score) of the best-scoring list.
    """
    best_nuance = None
    best_score = 0
    i = 18
    while i + 11 < len(row) and row[i]:
        nuance = row[i + 1]
        raw = row[i + vote_field]
        if not raw:
            i += 12
            continue
        score = float(raw.replace(",", "."))
        if score > best_score:
            best_score = score
            best_nuance = nuance
        i += 12
    return best_nuance, best_score


def _load_sector_winners() -> dict[str, str]:
    """Extract sector-level winners for Paris, Lyon, and Marseille.

    Returns a dict mapping sector key (e.g. "75_056SR07") to the winning
    nuance. T2 results override T1.
    """
    sector_winners: dict[str, str] = {}

    # T1: first-round outright winners (>50%)
    with open(T1_FILE, encoding="latin-1") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader)
        for row in reader:
            if "SR" not in row[2]:
                continue
            nuance, pct = _parse_wide_row(row, vote_field=11)
            if pct > 50 and nuance not in UNCLASSIFIED_NUANCES:
                sector_winners[f"{row[0]}_{row[2]}"] = nuance

    # T2: second-round winners override T1
    with open(T2_FILE, encoding="latin-1") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)
        for row in reader:
            if "SR" not in row[2]:
                continue
            nuance, _ = _parse_wide_row(row, vote_field=9)
            if nuance not in UNCLASSIFIED_NUANCES:
                sector_winners[f"{row[0]}_{row[2]}"] = nuance

    return sector_winners


def _add_arrondissements(
    winners: dict[str, dict],
    sector_winners: dict[str, str],
) -> None:
    """Add arrondissement entries for Paris, Lyon, and Marseille.

    Maps sector-level election winners to individual arrondissements.
    Paris: sectors 1:1 with arrondissements, except sector 1 covers arr 1-4.
    Lyon: sectors 1:1 with arrondissements.
    Marseille: each sector covers 2 consecutive arrondissements.
    """
    def _add(insee: str, name: str, nuance: str) -> None:
        winners[insee] = {
            "nom_commune": name,
            "nuance_politique": nuance,
        }

    def _ordinal(n: int) -> str:
        return "1er" if n == 1 else f"{n}e"

    # Paris: sector 1 = arr 1-4 (merged 2020), sectors 5-20 = arr 5-20
    for arr in range(1, 21):
        sector_num = 1 if arr <= 4 else arr
        sector_key = f"75_056SR{sector_num:02d}"
        nuance = sector_winners.get(sector_key, "LSOC")
        _add(
            f"751{arr:02d}",
            f"Paris {_ordinal(arr)} Arrondissement",
            nuance,
        )

    # Lyon: sector N = arrondissement N
    for arr in range(1, 10):
        sector_key = f"69_123SR{arr:02d}"
        nuance = sector_winners.get(sector_key, "LVEC")
        _add(
            f"6938{arr}",
            f"Lyon {_ordinal(arr)} Arrondissement",
            nuance,
        )

    # Marseille: sector N = arrondissements (2N-1) and (2N)
    for sector in range(1, 9):
        sector_key = f"13_055SR{sector:02d}"
        nuance = sector_winners.get(sector_key, "LUG")
        for arr in (sector * 2 - 1, sector * 2):
            _add(
                f"132{arr:02d}",
                f"Marseille {_ordinal(arr)} Arrondissement",
                nuance,
            )


def load_classified_communes() -> list[dict]:
    """Build the commune list from 2020 municipal election results.

    First round: communes where a list won >50% of expressed votes.
    Second round: the list with the most votes wins.
    Filters out unclassified nuances (LNC, NC).
    Returns list of dicts with slug, nom_commune, cog_commune,
    nuance_politique, famille_politique, sorted by INSEE code.
    """
    ensure_election_files()

    # keyed by INSEE code
    winners: dict[str, dict] = {}

    # T1: first-round outright winners (>50%)
    with open(T1_FILE, encoding="latin-1") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader)  # skip header
        for row in reader:
            dept, comm_code = row[0], row[2]
            if not comm_code.isdigit():  # skip sector codes (Marseille/Lyon)
                continue
            if dept.startswith("Z"):  # skip overseas territories
                continue
            nuance, pct = _parse_wide_row(row, vote_field=11)
            if pct <= 50 or nuance in UNCLASSIFIED_NUANCES:
                continue
            insee = dept.zfill(2) + comm_code.zfill(3)
            winners[insee] = {
                "nom_commune": row[3],
                "nuance_politique": nuance,
            }

    # T2: second-round winners override T1
    with open(T2_FILE, encoding="latin-1") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader)  # skip header
        for row in reader:
            dept, comm_code = row[0], row[2]
            if not comm_code.isdigit():  # skip sector codes (Marseille/Lyon)
                continue
            if dept.startswith("Z"):  # skip overseas territories
                continue
            nuance, _ = _parse_wide_row(row, vote_field=9)
            if nuance in UNCLASSIFIED_NUANCES:
                continue
            insee = dept.zfill(2) + comm_code.zfill(3)
            winners[insee] = {
                "nom_commune": row[3],
                "nuance_politique": nuance,
            }

    # Paris, Lyon, and Marseille use sectoral voting; ville-ideale has
    # per-arrondissement pages. Extract sector-level winners from election
    # data and map them to arrondissements.
    sector_winners = _load_sector_winners()
    _add_arrondissements(winners, sector_winners)

    # Build final list sorted by INSEE code
    communes = []
    for insee in sorted(winners):
        w = winners[insee]
        nuance = w["nuance_politique"]
        communes.append({
            "slug": build_slug(w["nom_commune"], insee),
            "nom_commune": w["nom_commune"],
            "cog_commune": insee,
            "nuance_politique": nuance,
            "famille_politique": NUANCE_TO_FAMILLE.get(nuance, nuance),
        })
    return communes


# --- HTML cache ---------------------------------------------------------------

def load_cached_html(slug: str) -> str | None:
    """Load a previously saved HTML page from the local cache."""
    path = HTML_DIR / f"{slug}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def save_html(slug: str, html: str) -> None:
    """Save an HTML page to the local cache."""
    HTML_DIR.mkdir(exist_ok=True)
    path = HTML_DIR / f"{slug}.html"
    path.write_text(html, encoding="utf-8")


# --- Wi-Fi reset (macOS) ------------------------------------------------------

def reset_wifi() -> bool:
    """Toggle Wi-Fi off/on to get a new IP from the mobile hotspot.

    Returns True if connectivity was restored, False otherwise.
    """
    import urllib.request

    print("  Wi-Fi off...", end="", flush=True)
    subprocess.run(
        ["networksetup", "-setairportpower", WIFI_INTERFACE, "off"],
        capture_output=True,
    )
    time.sleep(3)

    print(" on...", end="", flush=True)
    subprocess.run(
        ["networksetup", "-setairportpower", WIFI_INTERFACE, "on"],
        capture_output=True,
    )

    # Wait for connectivity (up to 30 seconds)
    for attempt in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen("http://www.google.com/generate_204", timeout=5)
            print(f" connected (took {attempt + 1}s).")
            return True
        except Exception:
            pass

    print(" FAILED to reconnect.")
    return False


# --- HTTP fetching via tls_client ---------------------------------------------

import tls_client

SIJS_RE = re.compile(r"sijs\((\d+)\)")

_session: tls_client.Session | None = None


def _new_session() -> tls_client.Session:
    """Create a fresh tls_client session with a Chrome TLS fingerprint."""
    return tls_client.Session(
        client_identifier="chrome_131",
        random_tls_extension_order=True,
    )


def _get_session() -> tls_client.Session:
    """Return the current session, creating one if needed."""
    global _session
    if _session is None:
        _session = _new_session()
    return _session


def _send_sijs_callback(html: str) -> None:
    """Mimic the browser's sijs() JS call: POST click=<idpv> to cherche.php.

    The site embeds `document.onload = sijs(<idpv>)` in every page.
    A real browser executes this on load, POSTing the page-view ID back.
    Without this callback, the server flags the visitor as a bot after ~10 hits.
    """
    m = SIJS_RE.search(html)
    if not m:
        return
    idpv = m.group(1)
    try:
        _get_session().post(
            f"{BASE_URL}/scripts/cherche.php",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/",
            },
            data=f"click={idpv}",
            timeout_seconds=10,
        )
    except Exception:
        pass


def fetch_url(url: str) -> str | None:
    """Fetch a URL with a Chrome TLS fingerprint. Returns HTML or None."""
    try:
        resp = _get_session().get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
                "Referer": f"{BASE_URL}/",
            },
            timeout_seconds=30,
        )
        if resp.status_code == 200 and len(resp.text) > 200:
            _send_sijs_callback(resp.text)
            return resp.text
        return None
    except Exception:
        return None


# --- HTML parsing -------------------------------------------------------------

def parse_town_page(html: str) -> dict | None:
    """Parse a town page and extract ratings.

    Returns a dict with name, postcode, overall score, category scores,
    or None if parsing fails.
    """
    # Extract name and postcode from <h1>ANTONY (92160)</h1>
    h1_match = re.search(r"<h1>\s*(.+?)\s*\((\d+)\)\s*</h1>", html)
    if not h1_match:
        return None
    name = h1_match.group(1).strip().title()
    postcode = int(h1_match.group(2))

    # Extract overall rating from <p id="ng"...>8,25<span...> / 10</span></p>
    overall = None
    ng_match = re.search(r'<p\s+id="ng"[^>]*>([\d,]+)', html)
    if ng_match:
        overall = float(ng_match.group(1).replace(",", "."))

    # Extract category ratings from <table id="tablonotes">
    ratings = {}
    table_match = re.search(
        r'<table\s+id="tablonotes">(.*?)</table>', html, re.DOTALL
    )
    if table_match:
        table_html = table_match.group(1)
        for row_match in re.finditer(
            r"<th[^>]*>\s*(.*?)\s*</th>\s*<td[^>]*>\s*([\d,]+)\s*</td>",
            table_html,
        ):
            category_name = row_match.group(1).strip()
            score_str = row_match.group(2).strip()
            json_key = CATEGORY_MAP.get(category_name)
            if json_key:
                ratings[json_key] = float(score_str.replace(",", "."))

    result = {"name": name, "postcode": postcode, "overall": overall}
    for key in CATEGORY_MAP.values():
        result[key] = ratings.get(key)
    return result


# --- Main scraping logic ------------------------------------------------------

def fetch_missing(
    communes: list[dict],
    base_delay: float = DEFAULT_DELAY,
    wifi: bool = False,
) -> int:
    """Fetch HTML pages for communes not yet cached.

    When wifi=True, works in batches of BATCH_SIZE to stay under the
    server's per-IP rate limit (~101 requests). Between batches, resets
    Wi-Fi to get a fresh IP and starts a fresh TLS session.

    Returns the number of pages newly fetched.
    """
    global _session

    to_fetch = [c for c in communes if not load_cached_html(c["slug"])]

    if not to_fetch:
        print("All pages already cached.")
        return 0

    total = len(to_fetch)
    if wifi:
        n_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"Fetching {total} uncached pages in up to {n_batches} batches "
              f"of {BATCH_SIZE}")
        print(f"  delay: {base_delay}s, Wi-Fi reset between batches\n")
    else:
        print(f"Fetching {total} uncached pages (delay: {base_delay}s)\n")

    consecutive_errors = 0
    fetched = 0
    batch_fetched = 0  # pages fetched in the current batch

    for i, commune in enumerate(to_fetch):
        slug = commune["slug"]
        url = f"{BASE_URL}/{slug}"

        # Reset Wi-Fi between batches to get a fresh IP
        if wifi and batch_fetched > 0 and batch_fetched % BATCH_SIZE == 0:
            batch_num = batch_fetched // BATCH_SIZE
            remaining = total - i
            print(f"\n  Batch {batch_num} done ({batch_fetched} fetched so far). "
                  f"{remaining} pages remaining.")
            if not reset_wifi():
                print("  Cannot continue without network. Stopping.")
                sys.exit(1)
            _session = _new_session()
            consecutive_errors = 0
            print()

        print(f"[{i + 1}/{total}] {slug} ", end="", flush=True)

        time.sleep(base_delay)
        html = fetch_url(url)

        if not html:
            consecutive_errors += 1
            print(f"EMPTY ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"\n{MAX_CONSECUTIVE_ERRORS} consecutive empty responses. "
                      f"Possible IP ban. Stopping.")
                print(f"Re-run to continue with remaining pages.")
                sys.exit(1)
            continue

        consecutive_errors = 0
        save_html(slug, html)
        fetched += 1
        batch_fetched += 1
        print("OK")

    return fetched


def build_json(communes: list[dict]) -> dict:
    """Parse all cached HTML pages and build the output dict."""
    result = {}
    for commune in communes:
        slug = commune["slug"]
        html = load_cached_html(slug)
        if not html:
            continue
        town_data = parse_town_page(html)
        if not town_data:
            continue
        town_data["nuance_politique"] = commune["nuance_politique"]
        town_data["famille_politique"] = commune["famille_politique"]
        result[slug] = town_data
    return result


# --- CLI entry point ----------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape town ratings from ville-ideale.fr"
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help=f"Base delay between requests in seconds (default: {DEFAULT_DELAY})",
    )
    parser.add_argument(
        "--wifi", action="store_true",
        help="Reset Wi-Fi between batches to get a fresh IP from mobile hotspot",
    )
    args = parser.parse_args()

    print("Loading classified communes from election results...")
    communes = load_classified_communes()
    print(f"  {len(communes)} communes")

    cached = sum(1 for c in communes if load_cached_html(c["slug"]))
    print(f"  {cached} already cached in {HTML_DIR.name}/\n")

    fetch_missing(communes, base_delay=args.delay, wifi=args.wifi)

    data = build_json(communes)
    print(f"\nWriting {len(data)} towns to {OUTPUT_FILE.name}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print("Done.")


if __name__ == "__main__":
    main()
