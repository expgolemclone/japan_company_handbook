# Architecture

## Overview

このリポジトリは、会社四季報オンラインの誌面アーカイブを取得し、後続処理しやすい形で保存するためのツール群で構成されている。現状は次の5系統が共存している。

1. `scrape`
   APIから全号のページPDFを直接取得するシンプルな一括ダウンローダー。
2. `scrape.magazine`
   号単位で raw manifest、正規化済み manifest、ページ実体、進捗、検証結果まで保存する取得パイプライン。
3. `scrape.magazine.audit`
   欠号候補のファクトチェックと live API の認証・payload 不整合を診断する監査CLI。
4. `scrape.stock`
   銘柄ごとの業績予想（四季報予想・会社予想）をAPIから取得し、SQLiteに格納する。
5. `pdfops`
   取得済みPDFを反転し、別ディレクトリへミラー出力する後処理ツール。

認証はいずれも東洋経済サイトのログインCookieに依存する。現在の実装は Playwright MCP を前提にしておらず、`httpx` から直接 API と配信URLを叩く構成になっている。

## Design Constraints

- **ログインCookie必須**: 匿名では取得できない。既定では Chrome の `Cookies` DB を直接読み、`scrape.magazine` 系CLIは JSON 形式のCookieファイルも受け付ける。
- **APIと配信URLは別物**: 号一覧や誌面メタデータは `api-shikiho.toyokeizai.net` から取得し、ページ本体は `shikiho.toyokeizai.net/files/...` から取得する。
- **PDF URLは都度解決が必要**: 一部のページはAPIレスポンスに直URLを持たず、`/headers/v1/headers` が返す `pdf_hash` と会員tierからPDF URLを組み立てる。
- **レスポンス形式が一定ではない**: `scrape.magazine.normalize` は複数キー候補から `page_id`、`stock_code`、`source_url` を推定する。
- **長時間バッチを前提にする**: 号単位・ページ単位の進捗ファイルを持ち、中断後の再開と完了検証をできるようにしている。
- **配信系の一時失敗を許容する**: `scrape.magazine.client.request_with_retries()` が `429`、`5xx`、`TransportError` をリトライする。

## Runtime Flows

### 1. `scrape` の全号PDF取得

`scrape.__main__.py` は 1936年以降の全号を走査し、各号のページPDFを `data/{year}_{series}/` に保存する。

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

### 2. `scrape.magazine` の号単位取得

`scrape-magazine` と `scrape-magazine-all` は、ページ実体だけでなく取得時のメタデータと検証可能な状態を丸ごと保存する。

```text
Chrome Cookie / Cookie JSON
  -> scrape.auth.refresh_cookies_via_chrome()  # バッチ前にChromeを自動起動しCookieを更新
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
- `source_url` が manifest に無いページだけ `pdf_hash` を用いてPDF URLを組み立てる。
- PDF URLが期限切れで HTML / JSON を返した場合は、`download_page()` が一度だけ `pdf_hash` を再取得して再試行する。
- `scrape-magazine-all --resume` で成功済み号をスキップできる。
- `scrape-magazine-verify` または `--verify-after-run` で保存完全性を検証できる。

### 3. `scrape.stock` の銘柄業績予想取得

`scrape.stock_cli` は `stock_codes_*.json` に掲載された全銘柄の業績予想を取得し、SQLiteに格納する。起動時に現在の Python に `httpx` が無い場合は、プロジェクト直下の `.venv` を検出できればその Python へ再実行し、見つからなければ依存インストールを促して終了する。

```text
Chrome Cookie DB
  -> scrape.auth.load_toyokeizai_cookies()
  -> scrape.client.build_api_client()
  -> /sso/v1/sso/check
  -> /stocks/v1/stocks/{code}/latest
  -> scrape.stock.fetch_stock_latest()
  -> shimen_results パース
     -> ◇XX.X予 → 四季報予想(2期分)
     -> 会XX.X予 → 会社予想(1期分)
  -> scrape.stock_db.save_performance()
  -> data/stock_performance.db
```

特徴:

- 営業利益・純利益を百万円単位で取得する。
- 四季報予想はプレミアム会員限定の値が `ー` になる場合、`NULL` として格納する。
- `INSERT OR REPLACE` で同一キーを更新する。
- 連続アクセス間隔は `REQUEST_INTERVAL = 1.0` 秒。

### 4. `pdfops` のPDF反転

`invert-pdfs` は任意の入力ディレクトリ配下の PDF を列挙し、相対パスを保ったまま出力先へ反転版を書き出す。

```text
source_root/**/*.pdf
  -> pdfops.plan_inversion_jobs()
  -> invert_pdf()
     -> gs があれば Ghostscript
     -> 無ければ pdftoppm + ImageMagick
  -> output_root/**/*.pdf
```

特徴:

- 出力先ディレクトリ構造は入力をミラーする。
- `gs` があればベクタPDFのまま反転し、無ければラスタライズ経由で生成する。

### 5. `scrape.magazine.audit` の監査

`scrape-magazine-audit` は保存済み号一覧と live API を分離して検査し、欠号候補と認証異常を別ファイルで出力する。

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
- `scrape-magazine-all` も同じ preflight を使い、失敗時はバッチ開始前に停止する。

## Module Responsibilities

### `scrape/auth.py`

- Chrome の Cookie SQLite DB を一時コピーして読み込む。
- v10 形式の暗号化Cookieを復号し、`httpx.Cookies` に積み替える。
- JSON Cookie経由ではなくブラウザ実Cookieを使う経路の基盤。
- `refresh_cookies_via_chrome()` でバッチ取得前にChromeを自動起動しCookieを更新する。

### `scrape/client.py`

- `scrape` 系の低レベルAPIアクセスを担当。
- 会員権限から `basic` / `premium` のPDFパスを決める。
- 号一覧取得、号メタデータ取得、ページID抽出、PDF URL構築を行う。

### `scrape/downloader.py`

- `scrape` 系のページPDF保存を担当。
- 保存先は `data/{year}_{series}/{page_id}.pdf`。
- `content-type` を検査し、PDF以外を弾く。

### `scrape/progress.py`

- `scrape` 系の簡易進捗管理。
- `data/progress.json` に completed キー集合を保存する。
- autosave と flush を持つ。

### `scrape/stock.py`

- 銘柄業績予想のAPI呼び出しとパースを担当。
- `/stocks/v1/stocks/{code}/latest` から `shimen_results` を取得する。
- `◇XX.X予` 行から四季報予想（営業利益・純利益）を2期分抽出する。
- `会XX.X予` 行から会社予想（営業利益・純利益）を1期分抽出する。
- 値が `ー` の場合は `None` とする。
- 数値パース失敗時は `logger.debug` で不正値を記録する。

### `scrape/stock_db.py`

- 銘柄業績予想のSQLite格納を担当。
- `data/stock_performance.db` に `stock_forecasts` テーブルを作成する。
- `INSERT OR REPLACE` でUPSERTを行う。
- 主キーは `(stock_code, forecast_type, period)`。

### `scrape/stock_cli.py`

- `scrape.stock` 系のバッチCLIエントリポイント。
- `data/stock_codes_*.json` の全銘柄を処理する。
- `httpx` 未導入の Python で起動された場合、`.venv/bin/python3` などのプロジェクト仮想環境を検出して自動で再実行する。
- 認証失敗時はChrome Cookieの自動更新を試行する。

### `scrape/magazine/client.py`

- `scrape.magazine` 系のHTTPクライアント構築を担当。
- Chrome Cookie DB と JSON Cookie の両方に対応する。
- 号一覧取得、単号取得、ページ一覧取得、`pdf_hash` 解決、リトライ制御、issue一覧キャッシュ保存を行う。
- payload status とレスポンス形状の検証も担当し、空 `magazine` / 空 `pages` を正常扱いしない。

### `scrape/magazine/normalize.py`

- APIレスポンスを安定した内部manifestへ正規化する。
- 重複ページの統合、`stock_code` の集約、`source_url` 推定、拡張子推定を行う。
- 正規化結果は `manifest.normalized.json` に保存される。

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
- manifest 上の expected pages と `pages/` 実ファイル、progress 状態、`physical_page_count` の整合を確認する。
- 結果は `verify_report.json` に保存できる。

### `scrape/magazine/summary.py`

- `BatchProgress` と `verify_report` から集計サマリを生成する。
- 結果は `batch_summary.json` に保存する。

### `scrape/magazine/audit.py`

- 欠号候補の抽出、前後号 manifest による連続性確認、公開書誌ソースの付与を担当する。
- live API の probe 結果を `http_status_error` / `payload_permission_error` / `payload_shape_error` などに分類する。
- `fact_check_report.json` と `auth_diagnostics.json` を保存する。

### `scrape/magazine/*.py` CLI

- `issue_cli.py`: 単号取得。
- `all_cli.py`: 全号取得、再開、実行後検証。
- `verify_cli.py`: 既存成果物の検証のみ実行。
- `audit_cli.py`: 欠号監査と認証診断を実行。

### `pdfops/invert.py`

- PDF列挙、出力パス計画、PDF反転処理を担当。
- Ghostscript 優先、無ければ `pdftoppm` と `magick` を使う。

## Data Layout

### Git 管理方針

`.gitignore` はホワイトリスト方式を採用している。ソースコード・設定ファイル・メタデータJSONのみを管理し、PDF・進捗ファイル・認証情報はスクレイパーの実行によってローカルにのみ存在する。PDFはスクレイパーで再取得可能なためリポジトリには含めない。

### 主要な入力・中間・出力

```text
data/                               # ホワイトリストで個別に管理
├── progress.json                    # [未管理] scrape 系の全体進捗
├── cookies.json                     # [未管理] 認証Cookie（秘匿）
├── signed_params.json               # [未管理] 認証パラメータ（秘匿）
├── stock_codes_*.json              # [管理] 銘柄コード一覧
├── stock_performance.db            # [未管理] 銘柄業績予想SQLite
├── {year}_{series}/                 # [未管理] scrape 系のページPDF保存先
│   └── {page_id}.pdf
├── watchdogs/                       # [未管理] watchdog の実行時ログ・ロック
└── magazines/
    ├── issues.raw.json              # [管理] APIから取得した号一覧の生データ
    ├── issues.expected.json         # [管理] バッチ対象の号一覧
    ├── batch_progress.json          # [未管理] 全号進捗
    ├── batch_summary.json           # [管理] 全号サマリ
    ├── verify_report.json           # [管理] 全号検証結果
    ├── fact_check_report.json       # [管理] 欠号候補と証拠レベルの監査結果
    ├── auth_diagnostics.json        # [管理] live API の認証・payload診断
    └── {calendar}_{series}/
        ├── manifest.raw.json        # [管理] APIレスポンスの生データ
        ├── manifest.normalized.json # [管理] 正規化済みmanifest
        ├── progress.json            # [未管理] 号単位の進捗
        └── pages/                   # [未管理] ページ実体
            └── {page_id}.{pdf|png|jpg|webp}

derived/
└── inverted_pdfs/
    └── ...                          # invert-pdfs の出力先の一例
```

## CLI Surface

`pyproject.toml` で公開しているCLIは次の通り。

- `scrape`: `scrape.__main__:main`
- `scrape-magazine`: `scrape.magazine.issue_cli:main`
- `scrape-magazine-all`: `scrape.magazine.all_cli:main`
- `scrape-magazine-verify`: `scrape.magazine.verify_cli:main`
- `scrape-magazine-audit`: `scrape.magazine.audit_cli:main`
- `invert-pdfs`: `pdfops.__main__:main`

追加のCLI:

- `uv run python -m scrape.stock_cli`: 銘柄業績予想のバッチ取得（推奨）
- `python -m scrape.stock_cli`: `.venv` を検出できる場合は同じ処理を自動再実行

## Error Handling

- HTTPステータス異常は `raise_for_status()` でそのまま失敗させる。
- `scrape.magazine` では payload 内 `status.code` も検査し、権限エラーを `MagazinePermissionError` に切り分ける。
- `scrape.magazine` では payload status が成功でも、空 `magazine` や空 `pages` は `MagazinePayloadShapeError` として失敗扱いにする。
- `request_with_retries()` は `429`、`5xx`、`TransportError` を再試行するが、永続エラーは握りつぶさない。
- 単号バッチでは失敗したページや号の状態を progress に記録し、全件停止ではなく続行できる箇所を分けている。
- 検証フェーズは「進捗が成功になっているか」だけでなく、「manifest と物理ファイルが一致するか」まで確認する。
- `scrape.stock_cli` では起動時の依存不足を検出し、`.venv` への再実行または `uv sync` の案内に切り分ける。
- `scrape.stock_cli` ではHTTPエラー、転送エラー、データなしの銘柄をスキップし、ログに出力して後続の処理を続行する。
- `scrape.stock._parse_value()` は数値変換失敗を握りつぶさず `logger.debug` で記録する。
