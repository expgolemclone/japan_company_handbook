# Architecture

## Overview

会社四季報オンライン（shikiho.toyokeizai.net）の誌面アーカイブPDFを一括保存するツール。
有料会員のログインセッションを使い、CloudFront署名付きURL経由でPDFをダウンロードする。

## Design Constraints

- **API認証**: サイトのAPI（`api-shikiho.toyokeizai.net`）はブラウザのCORSクレデンシャルでのみ認可される。httpx等の外部HTTPクライアントでは権限エラーになるため、銘柄一覧・号情報の取得はPlaywright MCP経由で事前に行い、JSONファイルに保存する。
- **署名付きURL**: PDF配信はCloudFront署名付きCookieを使用。署名パラメータ（Policy/Signature/Key-Pair-Id）はワイルドカードポリシー（`files/shimen/basic/*`）のため、1回の取得で全銘柄のダウンロードに使い回せる。有効期限あり（数時間）。
- **NixOS**: Playwright PythonはNixOSで動作しないため、ブラウザ操作はPlaywright MCP（既存ブラウザセッション）を利用する。

## Data Flow

```
1. Playwright MCP（手動）
   ├── ログイン → Cookie抽出 → data/cookies.json
   ├── 銘柄一覧取得 → data/stock_codes_{year}_{series}.json
   └── 署名パラメータ抽出 → data/signed_params.json

2. scrapeモジュール（自動）
   ├── 署名パラメータ読込
   ├── 銘柄コード読込
   └── PDF一括ダウンロード（1秒間隔）
       └── data/{year}_{series}/{code}.pdf
```

## File Structure

```
scrape/
├── __init__.py          # パッケージ初期化
├── __main__.py          # エントリーポイント（main）
├── client.py            # データ読込・URL構築
├── downloader.py        # PDF一括ダウンロード
└── progress.py          # 進捗管理（JSON、中断・再開対応）

data/
├── signed_params.json              # CloudFront署名パラメータ
├── stock_codes_2025_3.json         # 2025年夏号 銘柄コード一覧
├── stock_codes_2025_4.json         # 2025年秋号
├── stock_codes_2026_1.json         # 2026年新春号
├── stock_codes_2026_2.json         # 2026年春号
├── cookies.json                    # 認証Cookie（gitignore）
├── progress.json                   # ダウンロード進捗（自動生成）
├── 2025_3/{code}.pdf               # 各号のPDF保存先
├── 2025_4/{code}.pdf
├── 2026_1/{code}.pdf
└── 2026_2/{code}.pdf

tests/
├── test_client.py                  # client.py のテスト
├── test_downloader.py              # downloader.py のテスト
└── test_progress.py                # progress.py のテスト
```

## Module Responsibilities

### `scrape/client.py`

データ読込とPDF URL構築を担当。

- `ISSUES`: 直近4号のメタデータ（ハードコード）
- `load_stock_codes(year, series)`: 保存済み銘柄コード一覧を読み込む
- `load_signed_params()`: 保存済みCloudFront署名パラメータを読み込む
- `build_pdf_url(year, series, code, params)`: 署名付きPDF URLを構築する
- `build_http_client()`: PDFダウンロード用のhttpx.Clientを構築する

### `scrape/downloader.py`

PDFダウンロードの実行を担当。1秒間隔で順次ダウンロード。

- `download_pdf()`: 1銘柄のPDFをダウンロード・保存。content-type検証あり
- `download_all_stocks()`: 進捗管理付き一括ダウンロード。未ダウンロード分のみ処理

### `scrape/progress.py`

JSONファイルベースの進捗管理。中断・再開に対応。

- `DownloadKey`: `{code}_{year}_{series}` 形式のキー（frozen dataclass）
- `Progress`: ダウンロード済みの記録・参照。`pending_codes()` で未処理分を抽出

### `scrape/__main__.py`

エントリーポイント。全号のPDFダウンロードを実行する。

## Error Handling

- 具体的な例外型のみキャッチ（`httpx.HTTPStatusError`, `httpx.TimeoutException`）
- except + pass 禁止（ログ出力か再送出）
- fail fast: エラーは呼び出し元に伝搬
