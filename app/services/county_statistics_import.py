"""Import dated county ACS uncertainty, insurance, income and AHRF workforce."""

import csv
from datetime import datetime, timezone
import hashlib
import io
import math
import os
from pathlib import Path
import zipfile

import requests

from app.services.cms_service import normalize_county
from app.utils.state_utils import get_state_fips

ACS_URL = "https://api.census.gov/data/2024/acs/acs5/profile"
AHRF_URL = "https://data.hrsa.gov/DataDownload/AHRF/AHRF_2024-2025_CSV.zip"
CACHE_PATH = Path(__file__).resolve().parents[2] / "data/imports/AHRF_2024-2025_CSV.zip"
COUNTY_COUNTS = {"CA": 58, "WI": 72, "WY": 23}

# Every percentage uses its published denominator, not total county population.
ACS_METRICS = {
    "total_population": ("DP05_0001E", "people", "Total population"),
    "population_65_plus": ("DP05_0024E", "people", "Total population"),
    "population_65_plus_percent": ("DP05_0024PE", "percent", "Total population"),
    "insurance_population": (
        "DP03_0095E",
        "people",
        "Civilian noninstitutionalized population",
    ),
    "insured_population": (
        "DP03_0096E",
        "people",
        "Civilian noninstitutionalized population",
    ),
    "insured_percent": (
        "DP03_0096PE",
        "percent",
        "Civilian noninstitutionalized population",
    ),
    "uninsured_population": (
        "DP03_0099E",
        "people",
        "Civilian noninstitutionalized population",
    ),
    "uninsured_percent": (
        "DP03_0099PE",
        "percent",
        "Civilian noninstitutionalized population",
    ),
    "public_insurance_percent": (
        "DP03_0098PE",
        "percent",
        "Civilian noninstitutionalized population; coverage types can overlap",
    ),
    "poverty_percent": (
        "DP03_0128PE",
        "percent",
        "People for whom poverty status is determined",
    ),
    "median_household_income": ("DP03_0062E", "2024 USD", "Households"),
}

# County headcounts have different source years and definitions; never sum them.
WORKFORCE_METRICS = {
    "active_physicians_md_do": (
        "tot_md_do_activ_23",
        2023,
        "Active MD and DO physicians",
        "AMA Physician Master File",
    ),
    "primary_care_physicians": (
        "phys_nf_prim_care_pc_exc_rsdt_23",
        2023,
        "Non-federal primary-care patient-care physicians; excludes residents and age 75+",
        "AMA Physician Master File",
    ),
    "nurse_practitioners_npi": (
        "np_npi_24",
        2024,
        "Nurse practitioners with NPI; registration is not verified patient-care capacity",
        "CMS NPI File",
    ),
    "physician_assistants_npi": (
        "pa_npi_24",
        2024,
        "Physician assistants with NPI; registration is not verified patient-care capacity",
        "CMS NPI File",
    ),
    "active_dentists": (
        "dent_nf_fed_proflly_activ_23",
        2023,
        "Professionally active federal and non-federal dentists",
        "ADA",
    ),
}


def numeric_value(value):
    """Preserve special/suppressed source values as missing, never as zero."""
    if value is None or str(value).strip() in (
        "",
        "NA",
        "N/A",
        ".",
        "(X)",
        "**",
        "***",
        "*****",
    ):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if number.is_integer():
        return int(number)
    return number


def acs_measure(raw, variable, unit, universe):
    """Pair estimates with published 90% MOE; distinguish controlled estimates."""
    moe_variable = variable[:-1] + "M"
    estimate = numeric_value(raw.get(variable))
    moe = numeric_value(raw.get(moe_variable))
    status = "available"
    if moe is None:
        status = "unavailable_or_suppressed"
        if str(raw.get(moe_variable)) in ("-555555555", "-555555555.0", "*****"):
            status = "controlled_estimate_moe_not_applicable"
    if unit == "percent" and estimate is not None and estimate > 100:
        raise ValueError("Census percent outside 0–100.")
    estimate_status = "available"
    if estimate is None:
        estimate_status = "unavailable_or_suppressed"
    moe_unit = unit
    if unit == "percent":
        moe_unit = "percentage_points"
    return {
        "estimate": estimate,
        "moe": moe,
        "moe_status": status,
        "estimate_status": estimate_status,
        "confidence_level": 0.90,
        "unit": unit,
        "moe_unit": moe_unit,
        "universe": universe,
        "estimate_variable": variable,
        "moe_variable": moe_variable,
        "raw_estimate": raw.get(variable),
        "raw_moe": raw.get(moe_variable),
    }


def fetch_acs_counties(state):
    """Fetch all requested county estimates and MOEs in one bounded ACS call."""
    fields = ["NAME"]
    for variable, unit, universe in ACS_METRICS.values():
        fields.append(variable)
        fields.append(variable[:-1] + "M")
    params = {
        "get": ",".join(fields),
        "for": "county:*",
        "in": "state:" + get_state_fips(state),
    }
    if os.getenv("CENSUS_API_KEY"):
        params["key"] = os.getenv("CENSUS_API_KEY")
    response = requests.get(ACS_URL, params=params, timeout=60)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("Census county statistics unavailable.")
    headers = rows[0]
    if not set(fields + ["state", "county"]).issubset(headers):
        raise ValueError("Census variables missing from response.")
    records = {}
    for values in rows[1:]:
        if len(values) != len(headers):
            raise ValueError("Truncated Census row.")
        raw = {}
        for header, value in zip(headers, values):
            raw[header] = value
        if raw["state"] != get_state_fips(state):
            raise ValueError("Census state mismatch.")
        county = normalize_county(raw["NAME"].split(",")[0])
        if county in records:
            raise ValueError("Duplicate Census county.")
        measures = {}
        for name, (variable, unit, universe) in ACS_METRICS.items():
            measures[name] = acs_measure(raw, variable, unit, universe)
        record = {
            "county": county.upper(),
            "state_fips": raw["state"],
            "county_fips": raw["county"],
            "geography": "county",
            "source": "U.S. Census Bureau ACS 2024 5-Year",
            "dataset": "ACS Demographic and Housing Estimates; ACS Economic Characteristics",
            "survey_period": "2020–2024",
            "statistics_year": 2024,
            "acs_measures": measures,
            "_raw_record": raw,
            "moe_note": "Published ACS 90% margins of error; controlled or suppressed MOEs remain null with a reason.",
        }
        for name in (
            "total_population",
            "population_65_plus",
            "population_65_plus_percent",
        ):
            record[name] = measures[name]["estimate"]
        records[county] = record
    if state in COUNTY_COUNTS and len(records) != COUNTY_COUNTS[state]:
        raise ValueError("Incomplete Census county coverage.")
    return records


def workforce_measure(raw, variable, year, definition, original_source):
    """Compute a per-100,000 rate using same-year Census population in AHRF."""
    count = numeric_value(raw.get(variable))
    population_variable = "popn_est_" + str(year)[2:]
    population = numeric_value(raw.get(population_variable))
    rate = None
    residents_per_provider = None
    if count is not None and population is not None and population > 0:
        rate = round(count / population * 100000, 4)
        if count > 0:
            residents_per_provider = round(population / count, 4)
    status = "available"
    if rate is None:
        status = "unavailable_or_suppressed"
    return {
        "count": count,
        "count_year": year,
        "definition": definition,
        "source_variable": variable,
        "original_source": original_source,
        "population": population,
        "population_year": year,
        "population_variable": population_variable,
        "population_source": "Census County Population Estimates in AHRF",
        "per_100000_residents": rate,
        "residents_per_provider": residents_per_provider,
        "raw_count": raw.get(variable),
        "raw_population": raw.get(population_variable),
        "status": status,
    }


def fetch_workforce_counties(state):
    """Read only selected state counties and fields from the official AHRF ZIP."""
    if not CACHE_PATH.exists():
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(AHRF_URL, timeout=120)
        response.raise_for_status()
        if len(response.content) > 150 * 1024 * 1024:
            raise ValueError("AHRF archive exceeds import size limit.")
        temporary = CACHE_PATH.with_suffix(".part")
        temporary.write_bytes(response.content)
        temporary.replace(CACHE_PATH)
    digest = hashlib.sha256(CACHE_PATH.read_bytes()).hexdigest()
    records = {}
    with zipfile.ZipFile(CACHE_PATH) as archive:
        with archive.open("NCHWA-2024-2025+AHRF+COUNTY+CSV/AHRF2025.csv") as stream:
            reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig"))
            required = ["fips_st_cnty", "st_name_abbrev", "popn_est_23", "popn_est_24"]
            for variable, year, definition, source in WORKFORCE_METRICS.values():
                required.append(variable)
            if not set(required).issubset(reader.fieldnames or []):
                raise ValueError("AHRF required variables missing.")
            for raw in reader:
                if raw["st_name_abbrev"] != state:
                    continue
                fips = raw["fips_st_cnty"]
                if not fips.startswith(get_state_fips(state)) or fips in records:
                    raise ValueError("AHRF invalid or duplicate county FIPS.")
                measures = {}
                for name, (
                    variable,
                    year,
                    definition,
                    source,
                ) in WORKFORCE_METRICS.items():
                    measures[name] = workforce_measure(
                        raw, variable, year, definition, source
                    )
                records[fips] = {
                    "source": "HRSA Area Health Resources Files",
                    "release": "2024–2025",
                    "source_url": AHRF_URL,
                    "technical_documentation_url": "https://data.hrsa.gov/DataDownload/AHRF/AHRF_USER_TECH_2024-2025.zip",
                    "source_sha256": digest,
                    "county_fips": fips,
                    "source_retrieved_at": datetime.fromtimestamp(
                        CACHE_PATH.stat().st_mtime, timezone.utc
                    ).isoformat(),
                    "measures": measures,
                    "limitations": "County provider counts are not hospital staffing, FTEs, availability, capacity or a rural classification. Categories overlap; do not sum them.",
                }
    if state in COUNTY_COUNTS and len(records) != COUNTY_COUNTS[state]:
        raise ValueError("Incomplete AHRF county coverage.")
    return records


def fetch_county_statistics(state):
    """Join ACS and AHRF by FIPS before publishing a complete state snapshot."""
    records = fetch_acs_counties(state)
    workforce = fetch_workforce_counties(state)
    for record in records.values():
        fips = record["state_fips"] + record["county_fips"]
        if fips not in workforce:
            raise ValueError("AHRF county missing for ACS FIPS.")
        record["health_workforce"] = workforce[fips]
    return records
