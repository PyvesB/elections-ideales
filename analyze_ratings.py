#!/usr/bin/env python3
"""
Analytics on villes_ratings.json.

Computes average or median ratings grouped by political affiliation
(famille_politique or nuance_politique).

Usage:
    python3 analyze_ratings.py                       # Average by famille_politique
    python3 analyze_ratings.py --by nuance_politique # Average by nuance_politique
    python3 analyze_ratings.py --median              # Median instead of average
    python3 analyze_ratings.py --dept 75             # Filter to Paris (dept 75)
    python3 analyze_ratings.py --dept 13 --median    # Bouches-du-Rhone, median
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_FILE = SCRIPT_DIR / "villes_ratings.json"

RATING_FIELDS = [
    "overall",
    "environnement",
    "transports",
    "securite",
    "sante",
    "sports_et_loisirs",
    "culture",
    "enseignement",
    "commerces",
    "qualite_de_vie",
]

# Map nuance codes to party names
# See https://www.legifrance.gouv.fr/download/pdf/circ?id=44929
NUANCE_TO_PARTY = {
    "LEXG": "Extreme gauche",
    "LCOM": "Parti communiste francais",
    "LFI": "La France insoumise",
    "LSOC": "Parti socialiste",
    "LRDG": "Parti radical de gauche",
    "LDVG": "Divers gauche",
    "LUG": "Union de la gauche",
    "LVEC": "Europe Ecologie-Les Verts",
    "LECO": "Ecologiste",
    "LDIV": "Divers",
    "LREG": "Regionaliste",
    "LGJ": "Gilets jaunes",
    "LREM": "La Republique en marche",
    "LMDM": "Modem",
    "LUDI": "Union des Democrates et Independants",
    "LUC": "Union du centre",
    "LDVC": "Divers centre",
    "LLR": "Les Republicains",
    "LUD": "Union de la droite",
    "LDVD": "Divers droite",
    "LDLF": "Debout la France",
    "LRN": "Rassemblement National",
    "LEXD": "Extreme droite",
    "LNC": "Non Communique",
}

# Short column headers for display
FIELD_HEADERS = {
    "overall": "Overall",
    "environnement": "Envir.",
    "transports": "Transp.",
    "securite": "Secur.",
    "sante": "Sante",
    "sports_et_loisirs": "Sports",
    "culture": "Cult.",
    "enseignement": "Enseig.",
    "commerces": "Comm.",
    "qualite_de_vie": "Qual.vie",
}


def load_data(dept: str | None = None) -> dict:
    with open(INPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    if dept is None:
        return data
    return {
        k: v for k, v in data.items()
        if str(v.get("postcode", 0)).zfill(5)[:2] == dept
    }


def group_ratings(data: dict, group_by: str) -> dict[str, dict[str, list[float]]]:
    """Group non-null rating values by the given key."""
    groups: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {f: [] for f in RATING_FIELDS}
    )
    for town in data.values():
        key = town.get(group_by, "")
        if not key:
            continue
        bucket = groups[key]
        for field in RATING_FIELDS:
            val = town.get(field)
            if val is not None:
                bucket[field].append(val)
    return dict(groups)


def compute_stats(
    groups: dict[str, dict[str, list[float]]],
    use_median: bool,
) -> list[dict]:
    """Compute mean or median per group. Returns list of row dicts sorted by overall descending."""
    agg = median if use_median else mean
    rows = []
    for name, fields in groups.items():
        row = {"name": name}
        row["count"] = max((len(v) for v in fields.values()), default=0)
        for field in RATING_FIELDS:
            values = fields[field]
            row[field] = round(agg(values), 2) if values else None
        rows.append(row)
    rows.sort(key=lambda r: r.get("overall") or 0, reverse=True)
    return rows


def print_table(rows: list[dict], group_by: str, use_median: bool, dept: str | None = None) -> None:
    agg_label = "Median" if use_median else "Average"
    suffix = f" (dept {dept})" if dept else ""
    print(f"\n{agg_label} ratings by {group_by}{suffix}\n")

    show_party = group_by == "nuance_politique"

    # Determine name column width
    name_width = max(len(r["name"]) for r in rows)
    name_width = max(name_width, len(group_by))
    col_width = 8

    # Party column width (only when grouping by nuance)
    if show_party:
        party_width = max(
            len(NUANCE_TO_PARTY.get(r["name"], "")) for r in rows
        )
        party_width = max(party_width, len("Parti"))

    # Header
    header = f"{'':>{name_width}}"
    if show_party:
        header += f"  {'Parti':<{party_width}}"
    header += f"  {'#':>{5}}"
    for field in RATING_FIELDS:
        header += f"  {FIELD_HEADERS[field]:>{col_width}}"
    print(header)
    print("-" * len(header))

    # Rows
    for row in rows:
        line = f"{row['name']:>{name_width}}"
        if show_party:
            party = NUANCE_TO_PARTY.get(row["name"], "")
            line += f"  {party:<{party_width}}"
        line += f"  {row['count']:>{5}}"
        for field in RATING_FIELDS:
            val = row[field]
            cell = f"{val:.2f}" if val is not None else "-"
            line += f"  {cell:>{col_width}}"
        print(line)

    # Total towns
    total = sum(r["count"] for r in rows)
    print(f"\n{total} towns with ratings across {len(rows)} groups.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Analytics on ville-ideale.fr ratings by political affiliation"
    )
    parser.add_argument(
        "--by",
        choices=["famille_politique", "nuance_politique"],
        default="famille_politique",
        help="Grouping key (default: famille_politique)",
    )
    parser.add_argument(
        "--median",
        action="store_true",
        help="Use median instead of mean",
    )
    parser.add_argument(
        "--dept",
        help="Filter by department (first two digits of postcode, e.g. 75, 13, 06)",
    )
    args = parser.parse_args()

    data = load_data(dept=args.dept)
    if not data:
        print(f"No towns found for department {args.dept}.")
        return
    groups = group_ratings(data, args.by)
    rows = compute_stats(groups, use_median=args.median)
    print_table(rows, group_by=args.by, use_median=args.median, dept=args.dept)


if __name__ == "__main__":
    main()
