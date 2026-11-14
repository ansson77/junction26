"""Step 1 inputs: Business ID check, PRH registry lookup, TOL code -> sector family, demo data files."""

import json
import re
import urllib.parse
import urllib.request
from datetime import date
from functools import cache
from pathlib import Path

from .models import Profile

DATA_DIR = Path(__file__).resolve().parent / "data"
PLAYBOOK_PATH = DATA_DIR / "playbook.json"
PLAYBOOK_ESCO_PATH = DATA_DIR / "playbook_esco.json"
SAMPLES_PATH = DATA_DIR / "sample_companies.json"

PRH_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?businessId={}"
PRH_TIMEOUT = 4  # seconds; the lookup is best effort

# TOL 2008 two-digit division -> sector family. Anything else is "general".
TOL_FAMILIES = {
    "software": [58, 62, 63],
    "professional_services": [69, 70, 71, 72, 73, 74, 78],
    "manufacturing": range(10, 34),
    "construction": [41, 42, 43],
    "retail": [45, 46, 47],
    "hospitality": [55, 56],
    "health_care": [86, 87, 88],
}
_TOL_TO_FAMILY = {div: family for family, divs in TOL_FAMILIES.items() for div in divs}

_CHECK_WEIGHTS = (7, 9, 10, 5, 8, 4, 2)


# ---------- Data files ----------

@cache
def load_playbook():
    return json.loads(PLAYBOOK_PATH.read_text(encoding="utf-8"))


def load_playbook_esco():
    """{"phrases": {phrase: [skill, ...]}} written by prepare.py, or None if it hasn't been run."""
    if not PLAYBOOK_ESCO_PATH.exists():
        return None
    return json.loads(PLAYBOOK_ESCO_PATH.read_text(encoding="utf-8"))


def sample_companies():
    return json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))


def root_cause(rc_id):
    try:
        return load_playbook()["root_causes"][rc_id]
    except KeyError:
        raise ValueError(f"unknown root cause: {rc_id}") from None


def check_sector(sector):
    if sector not in load_playbook()["sectors"]:
        raise ValueError(f"unknown sector: {sector} (choose from {', '.join(load_playbook()['sectors'])})")
    return sector


# ---------- Business ID ----------

def normalize_business_id(value):
    """'1234560-4', '12345604' or ' 1234560 - 4 ' -> '1234560-4'. Raises ValueError if the
    format or the check digit is wrong."""
    digits = re.sub(r"[\s-]", "", value or "")
    if not re.fullmatch(r"\d{7,8}", digits):
        raise ValueError(f"not a Finnish Business ID (format 1234567-8): {value!r}")
    digits = digits.zfill(8)  # old IDs may have only 6 digits before the dash
    body, check = digits[:7], int(digits[7])
    remainder = sum(int(d) * w for d, w in zip(body, _CHECK_WEIGHTS)) % 11
    if remainder == 1 or check != (0 if remainder == 0 else 11 - remainder):
        raise ValueError(f"Business ID check digit is wrong: {value!r}")
    return f"{body}-{check}"


# ---------- Sector and age ----------

def sector_family(tol_code):
    """TOL 2008 code ('62010', '62', ...) -> sector family."""
    if not tol_code or not str(tol_code)[:2].isdigit():
        return "general"
    return _TOL_TO_FAMILY.get(int(str(tol_code)[:2]), "general")


def age_band(registered, today=None):
    if not registered:
        return None
    try:
        start = date.fromisoformat(registered[:10])
    except ValueError:
        return None
    years = ((today or date.today()) - start).days / 365.25
    if years < 2:
        return "under 2 years"
    if years < 5:
        return "2-5 years"
    if years < 10:
        return "5-10 years"
    return "over 10 years"


# ---------- PRH registry ----------

def fetch_prh(business_id):
    """Look a company up in the PRH open data API (no key needed). Returns
    {name, tol_code, registered}, or None if the lookup fails for any reason."""
    url = PRH_URL.format(urllib.parse.quote(business_id))
    try:
        with urllib.request.urlopen(url, timeout=PRH_TIMEOUT) as response:
            data = json.load(response)
        company = data["companies"][0]
    except Exception:
        return None
    names = [n for n in company.get("names", []) if n.get("type") == "1" and not n.get("endDate")]
    return {
        "name": names[0]["name"] if names else None,
        "tol_code": (company.get("mainBusinessLine") or {}).get("type"),
        "registered": (company.get("businessId") or {}).get("registrationDate") or company.get("registrationDate"),
    }


# ---------- Profiles ----------

def profile_from_registry(business_id):
    """Business ID -> Profile from PRH. Raises ValueError for a malformed ID, LookupError if PRH
    can't be reached or doesn't know the company (the caller can fall back to a sector)."""
    business_id = normalize_business_id(business_id)
    found = fetch_prh(business_id)
    if found is None:
        raise LookupError(f"could not look up {business_id} in the PRH registry (offline or unknown company)")
    return Profile(business_id=business_id, name=found["name"], sector_family=sector_family(found["tol_code"]),
                   tol_code=found["tol_code"], registered=found["registered"],
                   age_band=age_band(found["registered"]), source="prh")


def load_sample(key=None):
    """A demo company by key ('consulting', ...) or business ID. None -> the first one."""
    samples = sample_companies()
    if key is None:
        s = samples[0]
    else:
        matches = [s for s in samples if key in (s["key"], s["business_id"])]
        if not matches:
            raise ValueError(f"no sample company {key!r} (choose from {', '.join(s['key'] for s in samples)})")
        s = matches[0]
    return Profile(business_id=s["business_id"], name=s["name"], sector_family=s["sector_family"],
                   tol_code=s["tol_code"], registered=s["registered"], age_band=age_band(s["registered"]),
                   source="sample")


def manual_profile(sector, name=None, business_id=None):
    if business_id:
        business_id = normalize_business_id(business_id)
    return Profile(business_id=business_id, name=name, sector_family=check_sector(sector), source="manual")
