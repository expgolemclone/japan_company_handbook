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
| 銘柄業績予想を取得 | `uv run shikiho stock fetch` | `data/stock_performance.db` / `data/stock_latest_json/{code}.json` |
| 指定銘柄だけ再取得 | `uv run shikiho stock fetch --code 4231 --force` | `data/stock_performance.db` / `data/stock_latest_json/4231.json` |

## 補足

- `shikiho stock fetch` は `httpx` が見つからない場合、プロジェクト直下の `.venv` を検出できれば `python -m scrape.shikiho_cli stock fetch` へ自動再実行します。
- `shikiho stock fetch --code CODE` は、銘柄一覧JSONを読まずに指定銘柄だけを取得します。保存済み銘柄を更新する場合は `--force` も指定してください。
- `shikiho stock fetch` は各銘柄の API レスポンス JSON を `data/stock_latest_json/{code}.json` に丸ごと保存し、同じレスポンスから従来どおり SQLite も更新します。保存先は `--raw-json-dir` で変更できます。
- `--force` なしの場合、SQLite と raw JSON の両方が揃っている銘柄だけを取得済みとしてスキップします。
- `.venv` が無い、または依存が未インストールの場合は起動できないため、先に `uv sync` を実行してください。
- `shikiho pdf all` / `shikiho stock fetch` は、`401` / `403` / `3202` などの認証失敗を検知すると `https://shikiho.toyokeizai.net/stocks/` を開いて Cookie 更新を試み、成功時は同じ処理を1回だけ再試行します。
- `--cookie-file data/cookies.json` のような JSON Cookie を指定した場合も、認証失敗時は Chrome Cookie DB を元にその JSON を自動で上書き更新します。

## 移行表

| 旧コマンド | 新コマンド |
| --- | --- |
| `scrape` | `uv run shikiho pdf all` |
| `python -m scrape.stock_cli` | `uv run shikiho stock fetch` |

旧コマンドは互換実行せず、対応する `shikiho` コマンドを案内して終了します。
