from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_COL_OPERATING_PROFIT = 2
_COL_NET_INCOME = 4

_RE_SHIKIHO_FORECAST = re.compile(r"^(?:◇|◎|連|単)(\d+\.\d+)\*?予(?:変)?$")
_RE_COMPANY_FORECAST = re.compile(r"^会(\d+\.\d+)予$")


@dataclass(frozen=True, slots=True)
class ForecastRow:
    period: str
    operating_profit: int | None
    net_income: int | None


@dataclass(frozen=True, slots=True)
class MajorShareholder:
    name: str
    shares: int | None
    ratio_pct: float | None


@dataclass(frozen=True, slots=True)
class StockPerformance:
    code: str
    company_name: str
    shikiho_forecasts: list[ForecastRow]
    company_forecast: ForecastRow | None
    shareholders: list[MajorShareholder]
    shareholders_date: str | None


def _parse_value(raw: str | None) -> int | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped in ("ー", "-", "―", ""):
        return None
    try:
        return int(stripped.replace(",", ""))
    except ValueError:
        logger.debug("failed to parse numeric value: %r", stripped)
        return None


def _parse_ratio(raw: str | None) -> float | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped in ("ー", "-", "―", "", "‥"):
        return None
    try:
        return float(stripped)
    except ValueError:
        logger.debug("failed to parse ratio value: %r", stripped)
        return None


def parse_shimen_results(
    shimen_results: list[list[str]],
    *,
    max_shikiho: int = 2,
) -> tuple[list[ForecastRow], ForecastRow | None]:
    shikiho_forecasts: list[ForecastRow] = []
    company_forecast: ForecastRow | None = None

    for row in shimen_results[1:]:
        if not row:
            continue
        label = row[0]

        m = _RE_SHIKIHO_FORECAST.match(label)
        if m and len(shikiho_forecasts) < max_shikiho:
            shikiho_forecasts.append(
                ForecastRow(
                    period=m.group(1),
                    operating_profit=_parse_value(row[_COL_OPERATING_PROFIT] if len(row) > _COL_OPERATING_PROFIT else None),
                    net_income=_parse_value(row[_COL_NET_INCOME] if len(row) > _COL_NET_INCOME else None),
                )
            )
            continue

        m = _RE_COMPANY_FORECAST.match(label)
        if m and company_forecast is None:
            company_forecast = ForecastRow(
                period=m.group(1),
                operating_profit=_parse_value(row[_COL_OPERATING_PROFIT] if len(row) > _COL_OPERATING_PROFIT else None),
                net_income=_parse_value(row[_COL_NET_INCOME] if len(row) > _COL_NET_INCOME else None),
            )

    return shikiho_forecasts, company_forecast


def fetch_stock_latest(
    client: httpx.Client,
    code: str,
) -> StockPerformance | None:
    resp = client.get(f"/stocks/v1/stocks/{code}/latest")  # noqa: scrape-interval
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("is_exist") != "1":
        logger.warning("%s: 銘柄が存在しません", code)
        return None

    shimen_results = payload.get("shimen_results")
    if not shimen_results:
        logger.warning("%s: 業績データがありません", code)
        return None

    shikiho_forecasts, company_forecast = parse_shimen_results(shimen_results)
    if not shikiho_forecasts and company_forecast is None:
        logger.warning("%s: 保存対象の予想行がありません", code)
        return None

    raw_shareholders = payload.get("shimen_shareholders") or []
    shareholders = [
        MajorShareholder(
            name=s.get("name", ""),
            shares=_parse_value(s.get("number")),
            ratio_pct=_parse_ratio(s.get("ratio")),
        )
        for s in raw_shareholders
    ]

    return StockPerformance(
        code=code,
        company_name=payload.get("company_name_j") or "",
        shikiho_forecasts=shikiho_forecasts,
        company_forecast=company_forecast,
        shareholders=shareholders,
        shareholders_date=payload.get("shareholders_research_date"),
    )
