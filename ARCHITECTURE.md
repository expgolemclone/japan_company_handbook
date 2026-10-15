# Architecture

東洋経済「会社四季報オンライン」から誌面PDF・銘柄データを取得・管理する Python プロジェクト。

## 全体構成

```
scrape/              スクレイピング・データ取得
  shikiho_cli.py       統合CLIエントリポイント (shikiho コマンド)
  legacy_cli.py        旧コマンドの互換ラッパ
  auth.py              Chrome Cookie 読み込み・認証管理
  client.py            四季報APIクライアント (PDF・号一覧)
  downloader.py        PDFページダウンロード
  progress.py          JSONベースのダウンロード進捗管理
  pdf_all_cli.py       全号PDF一括取得
  stock.py             銘柄業績予想・大株主のパース
  stock_cli.py         銘柄データ取得CLI
  stock_load_cli.py    ローカルJSON→SQLite読み込みCLI
  stock_db.py          SQLiteへの銘柄データ保存
  watchdog.py          プロセス監視・自動再起動
pdfops/              PDF操作ユーティリティ
  invert.py            PDF白黒反転 (Ghostscript/pdftoppm+ImageMagick)
data/                取得済みデータ保存先
  stock_latest_json/   銘柄API生JSON (code.json)
  stock_performance.db 銘柄業績予想SQLite
  progress.json        PDF全号ダウンロード進捗
tests/               テストスイート
```

## 主要コンポーネント

### CLIレイヤー

`shikiho` コマンドが統合エントリポイント。サブコマンドで機能を切り替える。

| サブコマンド | 機能 | ハンドラ |
|---|---|---|
| `pdf all` | 1936年以降の全号PDF一括保存 | `pdf_all_cli.run` |
| `stock fetch` | 銘柄業績予想・大株主の取得 | `stock_cli.run` |
| `stock load` | ローカルJSONからSQLiteへ読み込み | `stock_load_cli.run` |

### 認証 (auth.py)

Chrome の Cookie DB (SQLite) から toyokeizai.net ドメインの Cookie を抽出して `httpx.Cookies` を構築する。v10形式の暗号化Cookieは PBKDF2+AES-CBC で復号。認証失敗時は Chrome ブラウザを起動して Cookie 更新を試みる。

- JSON形式Cookieファイル (`--cookie-file`) にも対応
- `is_http_auth_error()` で 401/403 を判定
- `refresh_cookie_source()` で Chrome Cookie DB から JSON Cookie を再生成

### PDF全号取得

`client.py` の `build_api_client()` で認証済みhttpxクライアントを構築し、`fetch_pdf_access()` で PDF配信パス (basic/premium) と pdf_hash を取得。`downloader.py` がticker（銘柄コード）単位でダウンロードし、`progress.py` (Progress) が完了状態を `data/progress.json` に記録。直列時は1リクエストごとに1秒のインターバル。`--workers` / `-w` オプションで `ThreadPoolExecutor` による並列DLに対応（Progress はスレッドセーフ）。

### 銘柄データ取得 (stock)

`stock.py` が四季報API (`/stocks/v1/stocks/{code}/latest`) から銘柄情報を取得。レスポンスの `shimen_results` から四季報予想・会社予想を正規表現でパースし、`shimen_shareholders` から大株主を抽出。`shimen_dividends` から配当履歴、`shimen_stats`/`shimen_financials` から指標・財務データをパース。

`stock_db.py` は SQLite に 4テーブルを管理:
- `stock_forecasts`: 銘柄コード・予想種別・期間の複合主キーで UPSERT (営業利益・純利益)
- `major_shareholders`: 銘柄コード・順位の複合主キーで UPSERT (大株主)
- `stock_dividends`: 銘柄コード・期間の複合主キーで UPSERT (配当金)
- `stock_metrics`: 銘柄コード主キーで UPSERT (PER/PBR/ROE/ROA/EPS/財務・会社基本情報)

`stock_cli.py` は API生JSON を `data/stock_latest_json/{code}.json` に保存しつつ SQLite も更新。`--force` なしの場合は全テーブルと raw JSON が揃った銘柄をスキップ。フェッチ完了後、`stock_db` の `sync_shikiho_forecasts` を subprocess で自動実行し、予想データを `stocks.db` へ即時同期する。

`stock_load_cli.py` はAPI通信なしでローカルJSONからSQLiteへ読み込む。認証不要でオフライン再処理が可能。`--force` なしの場合は全テーブル保存済み銘柄をスキップ。

### プロセス監視 (watchdog.py)

長時間実行コマンド (pdf all) を子プロセスとして起動し、heartbeat (ファイル更新時刻) で停滞を検知して自動再起動する。バックオフスケジュール (10s→20s→...→300s) で再起動間隔を制御。プロファイルごとにファイルロックで排他。

### PDF白黒反転 (pdfops/)

Ghostscript があれば `gs` で直接反転。なければ pdftoppm で PNG 化して ImageMagick `-negate` で反転後 PDF に再結合。

## データフロー

```
Chrome Cookie DB
       │
       ▼
   auth.py ──► httpx.Cookies
       │
       ▼
┌─────────────────────────────────────────┐
│            API (api-shikiho.toyokeizai.net)  │
└──┬──────────┬───────────────────────────┘
   │          │
   ▼          ▼
 PDF URL     銘柄情報
   │          │
   ▼          ▼
downloader   stock.py
   │          │
   ▼          ▼
 data/{year}_{series}/  stock_db.py ──► SQLite
                        stock_cli.py ──► raw JSON
```

## 依存関係

- **playwright**: ブラウザ自動化 (Cookie更新用)
- **httpx**: HTTP クライアント
- **cryptography**: Chrome Cookie の AES 復号
- **pytest / pytest-asyncio**: テスト (dev)
- **外部バイナリ** (pdfops): gs (Ghostscript), pdftoppm (Poppler), magick (ImageMagick)

## 実行環境

- Python 3.12+
- パッケージ管理: uv (hatchling ビルド)
- テスト: `uv run pytest`
