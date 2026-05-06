from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scrape.stock import StockPerformance

DATA_DIR = Path("data")
DEFAULT_DB_PATH = DATA_DIR / "stock_performance.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS stock_forecasts (
    stock_code      TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    forecast_type   TEXT NOT NULL,
    period          TEXT NOT NULL,
    operating_profit INTEGER,
    net_income      INTEGER,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (stock_code, forecast_type, period)
);
"""

_CREATE_SHAREHOLDERS_TABLE = """
CREATE TABLE IF NOT EXISTS major_shareholders (
    stock_code        TEXT NOT NULL,
    company_name      TEXT NOT NULL,
    rank              INTEGER NOT NULL,
    shareholder_name  TEXT NOT NULL,
    shares            INTEGER,
    ratio_pct         REAL,
    research_date     TEXT,
    fetched_at        TEXT NOT NULL,
    PRIMARY KEY (stock_code, rank)
);
"""

_UPSERT = """
INSERT OR REPLACE INTO stock_forecasts
    (stock_code, company_name, forecast_type, period, operating_profit, net_income, fetched_at)
VALUES (?, ?, ?, ?, ?, ?, ?);
"""

_UPSERT_SHAREHOLDER = """
INSERT OR REPLACE INTO major_shareholders
    (stock_code, company_name, rank, shareholder_name, shares, ratio_pct, research_date, fetched_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?);
"""


def existing_codes(db_path: Path = DEFAULT_DB_PATH) -> set[str]:
    if not db_path.exists():
        return set()
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT DISTINCT stock_code FROM stock_forecasts").fetchall()
    finally:
        con.close()
    return {row[0] for row in rows}


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.execute(_CREATE_TABLE)
        con.execute(_CREATE_SHAREHOLDERS_TABLE)
        con.commit()
    finally:
        con.close()


def save_performance(
    perf: StockPerformance,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db_path)
    try:
        for fc in perf.shikiho_forecasts:
            con.execute(
                _UPSERT,
                (perf.code, perf.company_name, "shikiho", fc.period,
                 fc.operating_profit, fc.net_income, now),
            )
        if perf.company_forecast is not None:
            fc = perf.company_forecast
            con.execute(
                _UPSERT,
                (perf.code, perf.company_name, "company", fc.period,
                 fc.operating_profit, fc.net_income, now),
            )
        con.commit()
    finally:
        con.close()


def existing_shareholder_codes(db_path: Path = DEFAULT_DB_PATH) -> set[str]:
    if not db_path.exists():
        return set()
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT DISTINCT stock_code FROM major_shareholders").fetchall()
    finally:
        con.close()
    return {row[0] for row in rows}


def save_shareholders(
    perf: StockPerformance,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    if not perf.shareholders:
        return
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db_path)
    try:
        for rank, sh in enumerate(perf.shareholders, start=1):
            con.execute(
                _UPSERT_SHAREHOLDER,
                (perf.code, perf.company_name, rank, sh.name,
                 sh.shares, sh.ratio_pct, perf.shareholders_date, now),
            )
        con.commit()
    finally:
        con.close()
