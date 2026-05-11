from __future__ import annotations

import argparse

from scrape.magazine import all_cli, audit_cli, issue_cli, verify_cli

DESCRIPTION = "四季報 scraping を用途別に実行する"
PDF_DESCRIPTION = "全号ページPDFを保存する"
MAGAZINE_DESCRIPTION = "誌面アーカイブを取得・検証する"
STOCK_DESCRIPTION = "銘柄業績予想を取得する"
PDF_ALL_DESCRIPTION = "1936年以降の全号ページPDFを保存する"
STOCK_FETCH_DESCRIPTION = "銘柄業績予想を取得してSQLiteへ保存する"


def _run_pdf_all(args: argparse.Namespace) -> int:
    from scrape import pdf_all_cli

    return pdf_all_cli.run(args)


def _run_stock_fetch(args: argparse.Namespace) -> int:
    from scrape import stock_cli

    return stock_cli.run(args)


def build_parser() -> argparse.ArgumentParser:
    from scrape import pdf_all_cli

    parser = argparse.ArgumentParser(prog="shikiho", description=DESCRIPTION)
    top_level = parser.add_subparsers(dest="domain", required=True)

    pdf_parser = top_level.add_parser("pdf", description=PDF_DESCRIPTION, help=PDF_DESCRIPTION)
    pdf_commands = pdf_parser.add_subparsers(dest="pdf_command", required=True)
    pdf_all_parser = pdf_commands.add_parser(
        "all",
        parents=[
            pdf_all_cli.build_parser(
                prog="shikiho pdf all",
                add_help=False,
            )
        ],
        add_help=True,
        description=PDF_ALL_DESCRIPTION,
        help=PDF_ALL_DESCRIPTION,
    )
    pdf_all_parser.set_defaults(handler=_run_pdf_all)

    magazine_parser = top_level.add_parser(
        "magazine",
        description=MAGAZINE_DESCRIPTION,
        help=MAGAZINE_DESCRIPTION,
    )
    magazine_commands = magazine_parser.add_subparsers(
        dest="magazine_command",
        required=True,
    )

    magazine_issue_parser = magazine_commands.add_parser(
        "issue",
        parents=[
            issue_cli.build_parser(
                prog="shikiho magazine issue",
                add_help=False,
            )
        ],
        add_help=True,
        description=issue_cli.DESCRIPTION,
        help=issue_cli.DESCRIPTION,
    )
    magazine_issue_parser.set_defaults(handler=issue_cli.run)

    magazine_all_parser = magazine_commands.add_parser(
        "all",
        parents=[
            all_cli.build_parser(
                prog="shikiho magazine all",
                add_help=False,
            )
        ],
        add_help=True,
        description=all_cli.DESCRIPTION,
        help=all_cli.DESCRIPTION,
    )
    magazine_all_parser.set_defaults(handler=all_cli.run)

    magazine_verify_parser = magazine_commands.add_parser(
        "verify",
        parents=[
            verify_cli.build_parser(
                prog="shikiho magazine verify",
                add_help=False,
            )
        ],
        add_help=True,
        description=verify_cli.DESCRIPTION,
        help=verify_cli.DESCRIPTION,
    )
    magazine_verify_parser.set_defaults(handler=verify_cli.run)

    magazine_audit_parser = magazine_commands.add_parser(
        "audit",
        parents=[
            audit_cli.build_parser(
                prog="shikiho magazine audit",
                add_help=False,
            )
        ],
        add_help=True,
        description=audit_cli.DESCRIPTION,
        help=audit_cli.DESCRIPTION,
    )
    magazine_audit_parser.set_defaults(handler=audit_cli.run)

    stock_parser = top_level.add_parser(
        "stock",
        description=STOCK_DESCRIPTION,
        help=STOCK_DESCRIPTION,
    )
    stock_commands = stock_parser.add_subparsers(dest="stock_command", required=True)
    from scrape import stock_cli as _stock_cli

    stock_fetch_parser = stock_commands.add_parser(
        "fetch",
        parents=[
            _stock_cli.build_parser(
                prog="shikiho stock fetch",
                add_help=False,
            )
        ],
        add_help=True,
        description=STOCK_FETCH_DESCRIPTION,
        help=STOCK_FETCH_DESCRIPTION,
    )
    stock_fetch_parser.set_defaults(handler=_run_stock_fetch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
