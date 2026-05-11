from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scrape.stock import StockPerformance
from scrape.stock import DividendRow
from scrape.stock import StockMetrics

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

_CREATE_DIVIDENDS_TABLE = """
CREATE TABLE IF NOT EXISTS stock_dividends (
    stock_code  TEXT NOT NULL,
    period      TEXT NOT NULL,
    dividend    REAL,
    is_forecast INTEGER NOT NULL DEFAULT 0,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (stock_code, period)
);
"""

_CREATE_METRICS_TABLE = """
CREATE TABLE IF NOT EXISTS stock_metrics (
    stock_code                TEXT PRIMARY KEY,
    company_name              TEXT NOT NULL,
    fyp1_per                  REAL,
    fyp2_per                  REAL,
    pbr                       REAL,
    shimen_per_high           REAL,
    shimen_per_low            REAL,
    fyp1_dividend_yield       REAL,
    fyp2_dividend_yield       REAL,
    market_capitalization     REAL,
    shimen_ratio_of_net_worth REAL,
    year_high                 REAL,
    year_low                  REAL,
    roe                       REAL,
    roa                       REAL,
    eps                       REAL,
    net_worth                 INTEGER,
    total_assets              INTEGER,
    capital_stock             INTEGER,
    interest_bearing_debt     INTEGER,
    employees                 INTEGER,
    established_date          TEXT,
    listed_date               TEXT,
    year_end_month            TEXT,
    fetched_at                TEXT NOT NULL
);
"""

_UPSERT_DIVIDEND = """
INSERT OR REPLACE INTO stock_dividends
    (stock_code, period, dividend, is_forecast, fetched_at)
VALUES (?, ?, ?, ?, ?);
"""

_UPSERT_METRICS = """
INSERT OR REPLACE INTO stock_metrics
    (stock_code, company_name,
     fyp1_per, fyp2_per, pbr,
     shimen_per_high, shimen_per_low,
     fyp1_dividend_yield, fyp2_dividend_yield,
     market_capitalization, shimen_ratio_of_net_worth,
     year_high, year_low,
     roe, roa, eps,
     net_worth, total_assets, capital_stock, interest_bearing_debt,
     employees, established_date, listed_date, year_end_month,
     fetched_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
        con.execute(_CREATE_DIVIDENDS_TABLE)
        con.execute(_CREATE_METRICS_TABLE)
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


def existing_dividend_codes(db_path: Path = DEFAULT_DB_PATH) -> set[str]:
    if not db_path.exists():
        return set()
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT DISTINCT stock_code FROM stock_dividends").fetchall()
    finally:
        con.close()
    return {row[0] for row in rows}


def save_dividends(
    code: str,
    dividends: list[DividendRow],
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    if not dividends:
        return
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db_path)
    try:
        for div in dividends:
            con.execute(
                _UPSERT_DIVIDEND,
                (code, div.period, div.dividend, int(div.is_forecast), now),
            )
        con.commit()
    finally:
        con.close()


def existing_metrics_codes(db_path: Path = DEFAULT_DB_PATH) -> set[str]:
    if not db_path.exists():
        return set()
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT DISTINCT stock_code FROM stock_metrics").fetchall()
    finally:
        con.close()
    return {row[0] for row in rows}


def save_metrics(
    metrics: StockMetrics,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            _UPSERT_METRICS,
            (metrics.code, metrics.company_name,
             metrics.fyp1_per, metrics.fyp2_per, metrics.pbr,
             metrics.shimen_per_high, metrics.shimen_per_low,
             metrics.fyp1_dividend_yield, metrics.fyp2_dividend_yield,
             metrics.market_capitalization, metrics.shimen_ratio_of_net_worth,
             metrics.year_high, metrics.year_low,
             metrics.roe, metrics.roa, metrics.eps,
             metrics.net_worth, metrics.total_assets,
             metrics.capital_stock, metrics.interest_bearing_debt,
             metrics.employees, metrics.established_date,
             metrics.listed_date, metrics.year_end_month,
             now),
        )
        con.commit()
    finally:
        con.close()
