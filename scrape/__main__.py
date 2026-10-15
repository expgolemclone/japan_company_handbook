from __future__ import annotations

from scrape.legacy_cli import main_scrape_module


def main() -> int:
    return main_scrape_module()


if __name__ == "__main__":
    raise SystemExit(main())
