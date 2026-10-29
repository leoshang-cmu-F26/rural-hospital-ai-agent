# Rural hospital lists

`GET /hospitals/rural?state=WI&limit=5` returns a compact list without
demographics, HPSA evidence, geocoding or distance calculations.

Parameters:

- `state`: required state name or abbreviation.
- `county`: optional county name; normalized using existing county rules.
- `zip_code`: optional five-digit string; matches the ZIP5 portion of directory ZIP+4.
- `limit`: defaults to 5, range 1–50.
- `year`: optional CMS dataset year, defaults to the latest available/imported year.

County and ZIP filters intersect and select hospital directory locations. State
is required even when supplying a county or ZIP. Examples:

```text
/hospitals/rural?state=WI&county=Juneau&limit=5
/hospitals/rural?state=WI&zip_code=53948&limit=10
```

The Agent uses the `list_rural_hospitals` tool for simple rural names, lists or
counts. Access questions continue to use `analyze_area_healthcare_access`.
Results are alphabetical, not a priority or quality ranking.

In database mode, one query retrieves the active complete financial snapshot
for the state/year. Duplicate reports use the existing primary-row selection
rule. The directory uses its existing snapshot cache. No migration or new
import is required. Database-only mode never falls back to CMS for missing
coverage; unavailable coverage is an error rather than an empty list.

Classification retains the application's existing CMS cost-report R/U rule.
The returned year and source describe that rule, not a new independent rural
classification. Missing or unrecognized values count as unknown and are excluded.
The response reports the full confirmed-rural count, unknown count and limited
hospital list. Live/hybrid fallback may still query individual cost reports.

Offline checks: `python -m pytest app/tests/rural_hospital_list_test.py -q`.
