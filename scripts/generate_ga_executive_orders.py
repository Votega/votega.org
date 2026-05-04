#!/usr/bin/env python3
"""
Parse scraped executive order CSV data and generate JSON files.
Usage: python scripts/generate_ga_executive_orders.py
"""

import json
import re
import os
from datetime import datetime

BASE_URL = "https://gov.georgia.gov"
OUTPUT_DIR = "assets/data"


def categorize(title):
    t = title.lower()
    if any(x in t for x in ['state of emergency', 'state emergency', 'renewing the state', 'extending the state',
                              'renewal of state', 'declaring a state']):
        return 'State of Emergency'
    if 'writ of election' in t:
        return 'Writ of Election'
    if t.startswith('suspend') or 'suspending' in t:
        return 'Suspension'
    if 'lower' in t and 'flag' in t:
        return 'Flag at Half-Staff'
    if t.startswith('authoriz') or 'authorizing' in t:
        return 'Authorization'
    if 'appoint' in t:
        return 'Appointment'
    return 'Other'


def parse_2024_line(line):
    """Format: MM.DD.YY.NN,Title,/document/path"""
    parts = line.strip().split(',', 2)
    if len(parts) != 3:
        return None
    num, title, path = parts
    m = re.match(r'^(\d{2})\.(\d{2})\.(\d{2})\.(\d{2,})$', num)
    if not m:
        return None
    month, day, year, seq = m.groups()
    full_date = f"20{year}-{month}-{day}"
    return {
        "date": full_date,
        "number": num,
        "title": title.strip(),
        "category": categorize(title),
        "url": f"{BASE_URL}{path.strip()}"
    }


def parse_2025_line(line):
    """Format: MM.DD.YY.NN,MM.DD.YY.NN,Title,/document/path"""
    parts = line.strip().split(',', 3)
    if len(parts) != 4:
        return None
    num, _dup, title, path = parts
    m = re.match(r'^(\d{2})\.(\d{2})\.(\d{2})\.(\d{2,})$', num)
    if not m:
        return None
    month, day, year, seq = m.groups()
    full_date = f"20{year}-{month}-{day}"
    return {
        "date": full_date,
        "number": num,
        "title": title.strip(),
        "category": categorize(title),
        "url": f"{BASE_URL}{path.strip()}"
    }


def parse_2023_line(line):
    """Format: MM.DD.YY,NN,Title,/document/path"""
    parts = line.strip().split(',', 3)
    if len(parts) != 4:
        return None
    date_str, seq, title, path = parts
    m = re.match(r'^(\d{2})\.(\d{2})\.(\d{2})$', date_str)
    if not m:
        return None
    month, day, year = m.groups()
    full_date = f"20{year}-{month}-{day}"
    num = f"{date_str}.{seq.strip().zfill(2)}"
    return {
        "date": full_date,
        "number": num,
        "title": title.strip(),
        "category": categorize(title),
        "url": f"{BASE_URL}{path.strip()}"
    }


def process_file(filepath, year, parser_fn, skip_header=False):
    orders = []
    seen = set()
    with open(filepath, encoding='utf-8') as f:
        lines = f.readlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        entry = parser_fn(line)
        if entry and entry['number'] not in seen:
            seen.add(entry['number'])
            orders.append(entry)
    return orders


def write_json(year, orders, governor="Brian P. Kemp"):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    source_url = f"https://gov.georgia.gov/executive-action/executive-orders/{year}"
    data = {
        "_note": f"Generated from {source_url}. Update manually or via a fetch script when new orders are issued.",
        "metadata": {
            "year": year,
            "governor": governor,
            "updatedAt": datetime.now().strftime("%Y-%m-%d"),
            "source": source_url,
            "count": len(orders)
        },
        "orders": orders
    }
    out_path = os.path.join(OUTPUT_DIR, f"ga-executive-orders-{year}.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(orders)} orders to {out_path}")


if __name__ == '__main__':
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tool_results_dir = r"C:\Users\justi\.claude\projects\c--Users-justi-Documents-GitHub-votega-org\ebb5ce38-acc4-4178-a11d-b682a50c56ce\tool-results"

    os.chdir(base)

    file_2024 = os.path.join(tool_results_dir, "toolu_01A73vQAGhiM7bqV59ujFCzw.txt")
    file_2025 = os.path.join(tool_results_dir, "toolu_01UFeJb95pAHGxiR1hQaj6ZD.txt")
    file_2023 = os.path.join(tool_results_dir, "toolu_01UKHdXgkS9ATERnA2jbJD6W.txt")

    orders_2024 = process_file(file_2024, 2024, parse_2024_line)
    write_json(2024, orders_2024)

    orders_2025 = process_file(file_2025, 2025, parse_2025_line)
    write_json(2025, orders_2025)

    orders_2023 = process_file(file_2023, 2023, parse_2023_line)
    write_json(2023, orders_2023)
