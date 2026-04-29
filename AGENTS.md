# japan_company_handbook AGENTS

- 返答は日本語で行う。
- 新しいブランチは作らず、現在のブランチで作業する。
- スクレイピング実装を触ったら、少なくとも `uv run pytest -q` を実行してから結果を共有する。
- 四季報監査は `uv run scrape-magazine-audit --cookie-file data/cookies.json --out-dir data/magazines` を使う。
- `scrape-magazine-audit` は `data/magazines/fact_check_report.json` と `data/magazines/auth_diagnostics.json` を更新する。認証診断で exit code 1 でも、JSON が更新されていれば内容確認を優先する。
- `data/cookies.json` は stale になりうる。再ログイン直後の再開確認は Chrome の実 Cookie を優先し、`auth_diagnostics.json` が `ok: true` か確認する。
- 保存済み成果物の整合確認は `uv run scrape-magazine-verify --out-dir data/magazines` を使う。
- verify 後に必要なドキュメントを更新し、現在のブランチへ push する。
