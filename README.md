# japan_company_handbook

四季報のデータを抽出することが目的のプロジェクトです.

## plan

1. 'https://shikiho.toyokeizai.net/stocks/{code}/shikiho' をスクレイピングして, 直近4号分の画像を保存する.
   a. まずはplaywright mcpでサイト構造を把握.
   b. 必要であればuserにplaywright操作を記録してもらう.

2. 全上場企業で1を完了させる.

## 銘柄業績予想スクレイプ

全上場企業の業績予想（営業利益・純利益）をAPIから取得し、SQLiteに格納する。

初回セットアップ:

```
uv sync
```

推奨実行コマンド:

```
uv run python -m scrape.stock_cli
```

補足:

- プロジェクト直下に `.venv` があれば、`python -m scrape.stock_cli` でも自動的に `.venv` の Python へ再実行する。
- `.venv` が無い、または依存が未インストールの場合は `httpx` が見つからず起動できないため、先に `uv sync` を実行する。

従来コマンド:

```
python -m scrape.stock_cli
```

結果確認:

```
sqlite3 data/stock_performance.db "SELECT * FROM stock_forecasts LIMIT 10"
```

## audit

- `uv run scrape-magazine-audit --cookie-file data/cookies.json`
  - `data/magazines/fact_check_report.json`
    - `issues.raw.json` / `issues.expected.json` / 既存 manifest を突き合わせて、欠号候補を `external_confirmed` / `mixed` / `internal_inferred` で分類する.
  - `data/magazines/auth_diagnostics.json`
    - ライブAPIに対して `issue_list` と代表2号を probe し、`401` / payload `3202` / `1000 + empty magazine` を分類する.
- `scrape-magazine-all` はバッチ開始前に同じ preflight を行い、失敗時は `auth_diagnostics.json` を書いて停止する.
