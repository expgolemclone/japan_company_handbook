from __future__ import annotations

import sys


def _print_migration(old_invocation: str, new_invocation: str) -> int:
    print(
        f"`{old_invocation}` は廃止されました。`{new_invocation}` を使ってください。",
        file=sys.stderr,
    )
    return 2


def main_scrape() -> int:
    return _print_migration("scrape", "uv run shikiho pdf all")


def main_scrape_module() -> int:
    return _print_migration("python -m scrape", "uv run shikiho pdf all")


def main_scrape_magazine_issue() -> int:
    return _print_migration("scrape-magazine", "uv run shikiho magazine issue")


def main_scrape_magazine_all() -> int:
    return _print_migration("scrape-magazine-all", "uv run shikiho magazine all")


def main_scrape_magazine_verify() -> int:
    return _print_migration(
        "scrape-magazine-verify",
        "uv run shikiho magazine verify",
    )


def main_scrape_magazine_audit() -> int:
    return _print_migration(
        "scrape-magazine-audit",
        "uv run shikiho magazine audit",
    )


def main_stock_module() -> int:
    return _print_migration(
        "python -m scrape.stock_cli",
        "uv run shikiho stock fetch",
    )


def main_stock_load_module() -> int:
    return _print_migration(
        "python -m scrape.stock_load_cli",
        "uv run shikiho stock load",
    )
