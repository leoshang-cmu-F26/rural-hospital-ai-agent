"""Persistent hospital coordinates, shared across application processes."""

from contextlib import closing
from pathlib import Path
import sqlite3


COORDINATE_DB_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "hospital_coordinates.db"
)
FIELDS = (
    "facility_id", "facility_name", "address", "city", "state", "zip_code",
    "latitude", "longitude", "matched_address", "source",
)


def initialize_coordinate_cache() -> None:
    """Create the runtime directory and schema on first use."""
    COORDINATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(COORDINATE_DB_PATH)) as connection:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS hospital_coordinates (
                    facility_id TEXT PRIMARY KEY,
                    facility_name TEXT,
                    address TEXT,
                    city TEXT,
                    state TEXT,
                    zip_code TEXT,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    matched_address TEXT,
                    source TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)


def read_coordinate_cache(facility_id: str) -> dict | None:
    """Read a successful geocode without exposing database metadata."""
    initialize_coordinate_cache()
    with closing(sqlite3.connect(COORDINATE_DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            f"SELECT {', '.join(FIELDS)} FROM hospital_coordinates "
            "WHERE facility_id = ?", (facility_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def write_coordinate_cache(result: dict) -> None:
    """Insert or refresh a successful geocode, preserving leading-zero CCNs."""
    initialize_coordinate_cache()
    updates = ", ".join(f"{field} = excluded.{field}" for field in FIELDS[1:])
    with closing(sqlite3.connect(COORDINATE_DB_PATH)) as connection:
        with connection:
            connection.execute(
                f"INSERT INTO hospital_coordinates ({', '.join(FIELDS)}) "
                f"VALUES ({', '.join('?' for _ in FIELDS)}) "
                f"ON CONFLICT(facility_id) DO UPDATE SET {updates}, "
                "updated_at = CURRENT_TIMESTAMP",
                tuple(result[field] for field in FIELDS),
            )
