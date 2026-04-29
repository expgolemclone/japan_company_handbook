# japan_company_handbook

四季報のデータを抽出することが目的のプロジェクトです.

## plan

1. 'https://shikiho.toyokeizai.net/stocks/{code}/shikiho' をスクレイピングして, 直近4号分の画像を保存する.
   a. まずはplaywright mcpでサイト構造を把握.
   b. 必要であればuserにplaywright操作を記録してもらう.

2. 全上場企業で1を完了させる.

## watchdog

- `scripts/watch-scrape`
  - `uv run scrape` を監視し、異常終了または heartbeat 停止時に再起動する.
- `scripts/watch-scrape-magazine-all`
  - `uv run scrape-magazine-all --resume --verify-after-run` を同様に監視する.
- runtime state と child log は `data/watchdogs/` に保存される.
- 例:
  - `scripts/watch-scrape --idle-seconds 900`
  - `scripts/watch-scrape-magazine-all --idle-seconds 1800`
