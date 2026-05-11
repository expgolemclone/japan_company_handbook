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
_RE_DIVIDEND_PERIOD = re.compile(r"^(\d+\.\d+)(予)?$")


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


@dataclass(frozen=True, slots=True)
class StockLatestJson:
    code: str
    payload: dict[str, object]
    content: bytes


@dataclass(frozen=True, slots=True)
class DividendRow:
    period: str
    dividend: float | None
    is_forecast: bool


@dataclass(frozen=True, slots=True)
class StockMetrics:
    code: str
    company_name: str
    fyp1_per: float | None
    fyp2_per: float | None
    pbr: float | None
    shimen_per_high: float | None
    shimen_per_low: float | None
    fyp1_dividend_yield: float | None
    fyp2_dividend_yield: float | None
    market_capitalization: float | None
    shimen_ratio_of_net_worth: float | None
    year_high: float | None
    year_low: float | None
    roe: float | None
    roa: float | None
    eps: float | None
    net_worth: int | None
    total_assets: int | None
    capital_stock: int | None
    interest_bearing_debt: int | None
    employees: int | None
    established_date: str | None
    listed_date: str | None
    year_end_month: str | None


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


def _parse_ratio(raw: str | float | None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
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


def _parse_dividend_value(raw: str | None) -> float | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped in ("ー", "-", "―", "", "‥"):
        return None
    try:
        return float(stripped.replace(",", ""))
    except ValueError:
        logger.debug("failed to parse dividend value: %r", stripped)
        return None


def parse_dividends(
    shimen_dividends: list[list[str]] | None,
) -> list[DividendRow]:
    if not shimen_dividends:
        return []
    rows: list[DividendRow] = []
    for entry in shimen_dividends[1:]:
        if not entry or len(entry) < 2:
            continue
        label = entry[0]
        m = _RE_DIVIDEND_PERIOD.match(label)
        if not m:
            continue
        rows.append(
            DividendRow(
                period=m.group(1),
                dividend=_parse_dividend_value(entry[1]),
                is_forecast=m.group(2) is not None,
            )
        )
    return rows


def _parse_stat_value(raw: str | None) -> float | None:
    if raw is None:
        return None
    stripped = raw.strip().rstrip("%").rstrip("円").replace(",", "")
    if stripped in ("ー", "-", "―", "", "‥"):
        return None
    try:
        return float(stripped)
    except ValueError:
        logger.debug("failed to parse stat value: %r", stripped)
        return None


def _parse_stat_field(stats: dict, key: str) -> float | None:
    entry = stats.get(key)
    if not isinstance(entry, list) or len(entry) < 2:
        return None
    return _parse_stat_value(entry[1])


def _parse_financial_field(financials: dict, key: str) -> int | None:
    entry = financials.get(key)
    if not isinstance(entry, list) or len(entry) < 2:
        return None
    return _parse_value(entry[1])


def parse_metrics(
    code: str,
    payload: dict[str, object],
) -> StockMetrics | None:
    if payload.get("is_exist") != "1":
        return None

    company_name = payload.get("company_name_j") or ""

    stats = payload.get("shimen_stats") or {}
    financials = payload.get("shimen_financials") or {}

    employees_raw = payload.get("shimen_employees") or ""
    employees = None
    if isinstance(employees_raw, str):
        import re as _re
        m_employees = _re.search(r"(\d+)名", employees_raw)
        if m_employees:
            employees = int(m_employees.group(1))

    established_raw = payload.get("shimen_established_date")
    established_date = str(established_raw) if established_raw else None

    listed_raw = payload.get("shimen_listed_date")
    listed_date = str(listed_raw) if listed_raw else None

    year_end_raw = payload.get("shimen_year_end_month")
    year_end_month = None
    if isinstance(year_end_raw, str):
        import re as _re
        m_month = _re.search(r"(\d+)月", year_end_raw)
        if m_month:
            year_end_month = m_month.group(1)

    return StockMetrics(
        code=code,
        company_name=company_name,
        fyp1_per=_parse_ratio(payload.get("fyp1_per")),
        fyp2_per=_parse_ratio(payload.get("fyp2_per")),
        pbr=_parse_ratio(payload.get("pbr")),
        shimen_per_high=_parse_ratio(payload.get("shimen_per_high")),
        shimen_per_low=_parse_ratio(payload.get("shimen_per_low")),
        fyp1_dividend_yield=_parse_ratio(payload.get("fyp1_dividend_yield")),
        fyp2_dividend_yield=_parse_ratio(payload.get("fyp2_dividend_yield")),
        market_capitalization=_parse_ratio(payload.get("market_capitalization")),
        shimen_ratio_of_net_worth=_parse_ratio(payload.get("shimen_ratio_of_net_worth")),
        year_high=_parse_ratio(payload.get("year_high")),
        year_low=_parse_ratio(payload.get("year_low")),
        roe=_parse_stat_field(stats, "roe"),
        roa=_parse_stat_field(stats, "roa"),
        eps=_parse_stat_field(stats, "eps"),
        net_worth=_parse_financial_field(financials, "net_worth"),
        total_assets=_parse_financial_field(financials, "total_assets"),
        capital_stock=_parse_financial_field(financials, "capital_stock"),
        interest_bearing_debt=_parse_financial_field(financials, "interest_bearing_liabilities"),
        employees=employees,
        established_date=established_date,
        listed_date=listed_date,
        year_end_month=year_end_month,
    )


def fetch_stock_latest(
    client: httpx.Client,
    code: str,
) -> StockPerformance | None:
    latest = fetch_stock_latest_json(client, code)
    return parse_stock_latest_payload(code, latest.payload)


def fetch_stock_latest_json(
    client: httpx.Client,
    code: str,
) -> StockLatestJson:
    resp = client.get(f"/stocks/v1/stocks/{code}/latest")  # noqa: scrape-interval
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError(f"{code}: JSONオブジェクトではないレスポンスです")
    return StockLatestJson(code=code, payload=payload, content=resp.content)


def parse_stock_latest_payload(
    code: str,
    payload: dict[str, object],
) -> StockPerformance | None:
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
