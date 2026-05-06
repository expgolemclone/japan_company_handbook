# Architecture

## Overview

このリポジトリは、会社四季報オンラインからデータを取得し、後続処理しやすい形で保存するためのツール群で構成されている。利用者向けの scraping 導線は `shikiho` に統一してあり、主な取得系は次の3系統に整理している。

1. `shikiho pdf all`
   1936年以降の全号ページPDFを `data/{year}_{series}/` に一括保存する。
2. `shikiho magazine ...`
   号単位の manifest、ページ実体、進捗、検証結果、監査結果を `data/magazines/` 配下に保存する。
3. `shikiho stock fetch`
   銘柄ごとの業績予想（四季報予想・会社予想）をAPIから取得し、SQLiteへ保存する。

補助系として、取得済みPDFを反転する `invert-pdfs` と、長時間バッチを監視する watchdog ラッパーを持つ。認証はいずれも東洋経済サイトのログインCookieに依存し、HTTPアクセスは Playwright ではなく `httpx` から直接 API と配信URLを叩く構成になっている。

## Design Constraints

- **ログインCookie必須**: 匿名では取得できない。既定では Chrome の `Cookies` DB を直接読み、`shikiho magazine ...` は JSON 形式のCookieファイルも受け付ける。
- **Cookie失効は認証失敗で検知する**: `401` / `403` / payload `3202` / auth-like payload shape を検知した時だけ `https://shikiho.toyokeizai.net/stocks/` へアクセスし、Cookie 更新後に1回だけ再試行する。
- **APIと配信URLは別物**: 号一覧や誌面メタデータは `api-shikiho.toyokeizai.net`、ページ本体は `shikiho.toyokeizai.net/files/...` から取得する。
- **PDF URLは都度解決が必要**: 一部のページはAPIレスポンスに直URLを持たず、`/headers/v1/headers` が返す `pdf_hash` と会員tierからPDF URLを組み立てる。
- **レスポンス形式が一定ではない**: `scrape.magazine.normalize` は複数キー候補から `page_id`、`stock_code`、`source_url` を推定する。
- **長時間バッチを前提にする**: 号単位・ページ単位の進捗ファイルを持ち、中断後の再開と完了検証をできるようにしている。
- **配信系の一時失敗を許容する**: `scrape.magazine.client.request_with_retries()` が `429`、`5xx`、`TransportError` をリトライする。
- **JSON Cookie も自動回復する**: `--cookie-file *.json` 指定時に認証失敗した場合は、Chrome Cookie DB から Cookie を再読込して指定 JSON を上書き更新する。
- **旧CLIは互換実行しない**: `scrape*` と `python -m scrape.stock_cli` は移行メッセージを出して終了コード `2` を返す。

## Runtime Flows

### 1. `shikiho pdf all`

`scrape.pdf_all_cli` が 1936年以降の全号を走査し、各号のページPDFを `data/{year}_{series}/` に保存する。

```text
Chrome Cookie DB
  -> scrape.auth.load_toyokeizai_cookies()
  -> scrape.client.build_api_client()
  -> /sso/v1/sso/check
  -> /headers/v1/headers
  -> /files/v1/files/magazines/list
  -> /files/v1/files/magazines/{year}/{series}
  -> scrape.client.extract_page_ids()
  -> scrape.downloader.download_all_pages()
  -> data/{year}_{series}/{page_id}.pdf
  -> data/progress.json
```

特徴:

- 出力はページPDFのみで、manifestは保持しない。
- `data/progress.json` で `page_id + year + series` 単位の完了状態を管理する。
- 連続アクセス間隔は `scrape/downloader.py` の `REQUEST_INTERVAL = 1.0` 秒。

### 2. `shikiho magazine issue` / `all`

`scrape.magazine.issue_cli` と `scrape.magazine.all_cli` が、ページ実体だけでなく取得時のメタデータと検証可能な状態を丸ごと保存する。

```text
Chrome Cookie / Cookie JSON
  -> scrape.magazine.client.build_magazine_http_client()
  -> /files/v1/files/magazines/list
  -> data/magazines/issues.raw.json
  -> extract_issue_refs()
  -> data/magazines/issues.expected.json
  -> 号ごとに /files/v1/files/magazines/{calendar}/{series}
  -> manifest.raw.json
  -> normalize_magazine()
  -> 必要時だけ /headers/v1/headers で pdf_hash 解決
  -> manifest.normalized.json
  -> pages/{page_id}.{ext}
  -> issue progress.json
  -> batch_progress.json
  -> verify_report.json / batch_summary.json
```

特徴:

- ページ実体は PDF とは限らず、`png`、`jpg`、`webp` も許容する。
- 起動時に毎回 Cookie 更新はせず、認証失敗時だけ `stocks/` を開いて回復を試みる。
- `--cookie-file *.json` 指定時も、認証失敗したら Chrome Cookie DB を元に JSON を上書き更新してから再試行する。
- `source_url` が manifest に無いページだけ `pdf_hash` を用いてPDF URLを組み立てる。
- PDF URLが期限切れで HTML / JSON を返した場合は、`download_page()` が一度だけ `pdf_hash` を再取得して再試行する。
- `shikiho magazine all --resume` で成功済み号をスキップできる。
- `shikiho magazine verify` または `--verify-after-run` で保存完全性を検証できる。

### 3. `shikiho stock fetch`

`scrape.stock_cli` が `stock_codes_*.json` に掲載された全銘柄の業績予想を取得し、SQLiteに格納する。起動時に現在の Python に `httpx` が無い場合は、プロジェクト直下の `.venv` を検出できれば `python -m scrape.shikiho_cli stock fetch` へ再実行し、見つからなければ依存インストールを促して終了する。

```text
Chrome Cookie DB
  -> scrape.auth.load_toyokeizai_cookies()
  -> scrape.client.build_api_client()
  -> /sso/v1/sso/check
  -> /stocks/v1/stocks/{code}/latest
  -> scrape.stock.fetch_stock_latest()
  -> shimen_results パース
     -> ◇XX.X予 -> 四季報予想(2期分)
     -> 会XX.X予 -> 会社予想(1期分)
  -> scrape.stock_db.save_performance()
  -> data/stock_performance.db
```

特徴:

- 営業利益・純利益を百万円単位で取得する。
- 四季報予想はプレミアム会員限定の値が `ー` になる場合、`NULL` として格納する。
- `INSERT OR REPLACE` で同一キーを更新する。
- 起動時 `sso/check` と銘柄取得中の `401` / `403` を検知した時だけ Cookie 更新を試み、同じ銘柄を1回だけ再試行する。
- 連続アクセス間隔は `REQUEST_INTERVAL = 1.0` 秒。

### 4. `shikiho magazine audit`

`scrape.magazine.audit_cli` は保存済み号一覧と live API を分離して検査し、欠号候補と認証異常を別ファイルで出力する。

```text
data/magazines/issues.raw.json
  -> build_fact_check_report()
  -> data/magazines/fact_check_report.json

Cookie JSON / Chrome Cookie
  -> build_magazine_http_client()
  -> /files/v1/files/magazines/list
  -> /files/v1/files/magazines/{first,last}
  -> build_auth_diagnostics()
  -> data/magazines/auth_diagnostics.json
```

特徴:

- 欠号候補は `external_confirmed` / `mixed` / `internal_inferred` の証拠レベルで分類する。
- `401`、payload `3202`、`status=1000` なのに `magazine` が空、を別カテゴリで記録する。
- 認証診断が auth-like failure の時だけ Cookie 更新後に1回だけ再試行する。
- `shikiho magazine all` も同じ preflight を使い、回復できない場合だけバッチ開始前に停止する。

### 5. `invert-pdfs`

`invert-pdfs` は任意の入力ディレクトリ配下の PDF を列挙し、相対パスを保ったまま出力先へ反転版を書き出す。

```text
source_root/**/*.pdf
  -> pdfops.plan_inversion_jobs()
  -> invert_pdf()
     -> gs があれば Ghostscript
     -> 無ければ pdftoppm + ImageMagick
  -> output_root/**/*.pdf
```

## Module Responsibilities

### `scrape/shikiho_cli.py`

- 利用者向けの親CLI。
- `pdf` / `magazine` / `stock` を第一階層に束ねる。
- `magazine` 配下は既存の leaf CLI parser を親parserとして再利用する。

### `scrape/legacy_cli.py`

- 廃止済みコマンドの移行メッセージをまとめる。
- 旧 console script と `python -m ...` 導線を終了コード `2` で止める。

### `scrape/pdf_all_cli.py`

- `shikiho pdf all` の実行本体。
- 旧 `scrape` の実処理を引き継ぎ、全号PDF保存を担当する。

### `scrape/auth.py`

- Chrome の Cookie SQLite DB を一時コピーして読み込む。
- v10 形式の暗号化Cookieを復号し、`httpx.Cookies` に積み替える。
- JSON Cookie経由ではなくブラウザ実Cookieを使う経路の基盤。
- `refresh_cookies_via_chrome()` で `stocks/` を開き、Cookie が再利用可能になるまで待機する。
- `refresh_cookie_source()` は認証失敗時の回復ヘルパで、JSON指定なら Chrome Cookie DB から指定 JSON も上書き更新する。

### `scrape/client.py`

- PDF一括取得系の低レベルAPIアクセスを担当。
- 会員権限から `basic` / `premium` のPDFパスを決める。
- 号一覧取得、号メタデータ取得、ページID抽出、PDF URL構築を行う。

### `scrape/downloader.py`

- PDF一括取得系のページPDF保存を担当。
- 保存先は `data/{year}_{series}/{page_id}.pdf`。
- `content-type` を検査し、PDF以外を弾く。

### `scrape/progress.py`

- PDF一括取得系の簡易進捗管理。
- `data/progress.json` に completed キー集合を保存する。
- autosave と flush を持つ。

### `scrape/stock.py`

- 銘柄業績予想のAPI呼び出しとパースを担当。
- `/stocks/v1/stocks/{code}/latest` から `shimen_results` を取得する。
- `◇XX.X予` 行から四季報予想を2期分、`会XX.X予` 行から会社予想を1期分抽出する。

### `scrape/stock_db.py`

- 銘柄業績予想のSQLite格納を担当。
- `data/stock_performance.db` に `stock_forecasts` テーブルを作成する。
- `INSERT OR REPLACE` でUPSERTを行う。

### `scrape/stock_cli.py`

- `shikiho stock fetch` の実行本体。
- `data/stock_codes_*.json` の全銘柄を処理する。
- `httpx` 未導入時は `.venv` を検出して `scrape.shikiho_cli stock fetch` に再実行する。
- `401` / `403` を検知した場合は Cookie 更新後に同じ銘柄を1回だけ再試行する。
- 直接 `python -m scrape.stock_cli` された場合は移行メッセージを返す。

### `scrape/magazine/client.py`

- `shikiho magazine ...` 系のHTTPクライアント構築を担当。
- Chrome Cookie DB と JSON Cookie の両方に対応する。
- 号一覧取得、単号取得、ページ一覧取得、`pdf_hash` 解決、リトライ制御、issue一覧キャッシュ保存を行う。
- 認証失敗らしい例外を `is_probable_auth_error()` で切り分ける。

### `scrape/magazine/normalize.py`

- APIレスポンスを安定した内部manifestへ正規化する。
- 重複ページの統合、`stock_code` の集約、`source_url` 推定、拡張子推定を行う。

### `scrape/magazine/downloader.py`

- 単号取得の実行本体。
- `manifest.raw.json` と `manifest.normalized.json` を保存してからページ実体を取得する。
- 取得中の失敗は issue progress に記録する。

### `scrape/magazine/progress.py`

- 号単位の `IssueProgress` と、全体バッチ単位の `BatchProgress` を持つ。
- `IssueProgress` は expected pages、各ページの completed / failed、完了フラグを保持する。
- `BatchProgress` は `pending` / `running` / `succeeded` / `failed` を保持する。

### `scrape/magazine/verify.py`

- 単号・全号の保存完全性を検証する。
- manifest、物理ファイル、progress 状態、`physical_page_count` の整合を確認する。

### `scrape/magazine/summary.py`

- `BatchProgress` と `verify_report` から集計サマリを生成する。
- 結果は `batch_summary.json` に保存する。

### `scrape/magazine/audit.py`

- 欠号候補の抽出、前後号 manifest による連続性確認、公開書誌ソースの付与を担当する。
- live API の probe 結果を `http_status_error` / `payload_permission_error` / `payload_shape_error` などに分類する。

### `scrape/magazine/*.py` CLI

- `issue_cli.py`: `shikiho magazine issue`
- `all_cli.py`: `shikiho magazine all`
- `verify_cli.py`: `shikiho magazine verify`
- `audit_cli.py`: `shikiho magazine audit`
- `issue_cli.py` / `all_cli.py` / `audit_cli.py` は auth-like failure のとき Cookie 回復後に1回だけ再試行する。

### `scrape/watchdog.py`

- 長時間バッチを監視して再起動する。
- 現在の profile 名は `shikiho-pdf-all` と `shikiho-magazine-all`。
- child command は `uv run shikiho ...` を直接起動する。

### `pdfops/invert.py`

- PDF列挙、出力パス計画、PDF反転処理を担当する。
- Ghostscript 優先、無ければ `pdftoppm` と `magick` を使う。

## Verification Strategy

CLI再編後の scraping 導線は、実APIの長時間バッチを毎回走らせる代わりに、入口疎通と実行本体の主要経路をスモークテストで固定化して確認する。

- `tests/test_pdf_all_cli.py`
  `shikiho pdf all` が `401` / `403` 再認証、号一覧取得、ページ一覧抽出、同一号の再試行まで到達することを確認する。
- `tests/test_magazine_all_cli.py`
  `shikiho magazine all` が issue list 取得、artifact 保存、`verify_report.json` 生成、`--resume`、認証エラー時の Cookie 回復と診断出力まで完了することを確認する。
- `tests/test_magazine_issue_cli.py`
  `shikiho magazine issue` が認証エラー後に同じ号を再試行し、2回目も失敗したら終了コード `1` を返すことを確認する。
- `tests/test_magazine_audit_cli.py`
  `shikiho magazine audit` が auth diagnostics の `3202` を検知したら Cookie 回復後に再実行することを確認する。
- `tests/test_stock_cli.py`
  `shikiho stock fetch` が銘柄一覧読込、`/sso/v1/sso/check`、`fetch_stock_latest()`、認証エラー時の同一銘柄再試行、SQLite保存、`httpx` 未導入時の `.venv` 再実行判定まで確認する。
- `tests/test_auth.py`
  JSON Cookie の上書き再生成と、非JSON Cookie ソースの refresh 委譲を確認する。
- `tests/test_shikiho_cli.py`
  利用者向け `shikiho` 親CLIが `pdf` / `magazine` / `stock` の各 subcommand へ正しく dispatch することを確認する。

## Data Layout

### Git 管理方針

`.gitignore` はホワイトリスト方式を採用している。ソースコード・設定ファイル・メタデータJSONのみを管理し、PDF・進捗ファイル・認証情報はスクレイパーの実行によってローカルにのみ存在する。PDFはスクレイパーで再取得可能なためリポジトリには含めない。

### 主要な入力・中間・出力

```text
data/                               # ホワイトリストで個別に管理
├── progress.json                   # [未管理] pdf all の全体進捗
├── cookies.json                    # [未管理] 認証Cookie（秘匿）
├── signed_params.json              # [未管理] 認証パラメータ（秘匿）
├── stock_codes_*.json              # [管理] 銘柄コード一覧
├── stock_performance.db            # [未管理] 銘柄業績予想SQLite
├── {year}_{series}/                # [未管理] pdf all のページPDF保存先
│   └── {page_id}.pdf
├── watchdogs/                      # [未管理] watchdog の実行時ログ・ロック
│   ├── shikiho-pdf-all-hourly.json # [未管理] 1時間ごとの監視スナップショット
│   ├── shikiho-pdf-all-hourly.log  # [未管理] 1時間ごとの監視履歴
│   └── shikiho-pdf-all-hourly.pid  # [未管理] 1時間ごとの監視プロセスPID
└── magazines/
    ├── issues.raw.json             # [管理] APIから取得した号一覧の生データ
    ├── issues.expected.json        # [管理] バッチ対象の号一覧
    ├── batch_progress.json         # [未管理] 全号進捗
    ├── batch_summary.json          # [管理] 全号サマリ
    ├── verify_report.json          # [管理] 全号検証結果
    ├── fact_check_report.json      # [管理] 欠号候補と証拠レベルの監査結果
    ├── auth_diagnostics.json       # [管理] live API の認証・payload診断
    └── {calendar}_{series}/
        ├── manifest.raw.json       # [管理] APIレスポンスの生データ
        ├── manifest.normalized.json # [管理] 正規化済みmanifest
        ├── progress.json           # [未管理] 号単位の進捗
        └── pages/                  # [未管理] ページ実体
            └── {page_id}.{pdf|png|jpg|webp}

derived/
└── inverted_pdfs/
    └── ...                         # invert-pdfs の出力先の一例
```

## CLI Surface

`pyproject.toml` で公開している利用者向けCLIは次の通り。

- `shikiho`
- `invert-pdfs`

`shikiho` のサブコマンドは次の通り。

- `shikiho pdf all`
- `shikiho magazine issue`
- `shikiho magazine all`
- `shikiho magazine verify`
- `shikiho magazine audit`
- `shikiho stock fetch`

移行用に旧 console script も名前だけ残しているが、いずれも実処理はせず新コマンドを案内して終了する。

- `scrape`
- `scrape-magazine`
- `scrape-magazine-all`
- `scrape-magazine-verify`
- `scrape-magazine-audit`
- `python -m scrape`
- `python -m scrape.stock_cli`

watchdog ラッパー:

- `scripts/watch-shikiho-pdf-all`
- `scripts/watch-shikiho-magazine-all`
- `scripts/monitor-shikiho-pdf-all-hourly`

旧ラッパー `scripts/watch-scrape` と `scripts/watch-scrape-magazine-all` も移行メッセージのみ返す。

## Error Handling

- HTTPステータス異常は `raise_for_status()` でそのまま失敗させる。
- `shikiho magazine ...` では payload 内 `status.code` も検査し、権限エラーを `MagazinePermissionError` に切り分ける。
- `shikiho magazine ...` では payload status が成功でも、空 `magazine` や空 `pages` は `MagazinePayloadShapeError` として失敗扱いにする。
- `request_with_retries()` は `429`、`5xx`、`TransportError` を再試行するが、永続エラーは握りつぶさない。
- 単号バッチでは失敗したページや号の状態を progress に記録し、全件停止ではなく続行できる箇所を分けている。
- 検証フェーズは進捗だけでなく、manifest と物理ファイルの一致まで確認する。
- `scrape.stock_cli` は起動時の依存不足を検出し、`.venv` への再実行または `uv sync` の案内に切り分ける。
- `scrape.stock_cli` はHTTPエラー、転送エラー、データなしの銘柄をスキップし、ログに出力して後続処理を続行する。
- 旧CLIはすべて移行エラーとして終了コード `2` を返す。
