# japan_company_handbook

四季報データを取得するためのプロジェクトです。scraping 系コマンドは `shikiho` に統一しています。

## セットアップ

```bash
uv sync
```

## scraping コマンド

| 用途 | コマンド | 主な出力 |
| --- | --- | --- |
| 全号ページPDFを一括取得 | `uv run shikiho pdf all` | `data/{year}_{series}/{page_id}.pdf` |
| 誌面アーカイブを単号取得 | `uv run shikiho magazine issue --calendar 2026 --series 2` | `data/magazines/{calendar}_{series}/` |
| 誌面アーカイブを全号取得 | `uv run shikiho magazine all --resume --verify-after-run` | `data/magazines/` 配下一式 |
| 誌面アーカイブを検証 | `uv run shikiho magazine verify` | `data/magazines/verify_report.json` |
| 欠号監査と認証診断 | `uv run shikiho magazine audit --cookie-file data/cookies.json` | `fact_check_report.json` / `auth_diagnostics.json` |
| 銘柄業績予想を取得 | `uv run shikiho stock fetch` | `data/stock_performance.db` |

## 補足

- `shikiho stock fetch` は `httpx` が見つからない場合、プロジェクト直下の `.venv` を検出できれば `python -m scrape.shikiho_cli stock fetch` へ自動再実行します。
- `.venv` が無い、または依存が未インストールの場合は起動できないため、先に `uv sync` を実行してください。
- `shikiho magazine all` は開始前に認証 preflight を行い、失敗時は `data/magazines/auth_diagnostics.json` を書いて停止します。
- `shikiho magazine audit` は `issues.raw.json` / `issues.expected.json` / 既存 manifest を突き合わせて、欠号候補を `external_confirmed` / `mixed` / `internal_inferred` で分類します。

## 移行表

| 旧コマンド | 新コマンド |
| --- | --- |
| `scrape` | `uv run shikiho pdf all` |
| `scrape-magazine` | `uv run shikiho magazine issue` |
| `scrape-magazine-all` | `uv run shikiho magazine all` |
| `scrape-magazine-verify` | `uv run shikiho magazine verify` |
| `scrape-magazine-audit` | `uv run shikiho magazine audit` |
| `python -m scrape.stock_cli` | `uv run shikiho stock fetch` |

旧コマンドは互換実行せず、対応する `shikiho` コマンドを案内して終了します。
