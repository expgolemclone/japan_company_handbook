# japan_company_handbook

四季報のデータを抽出することが目的のプロジェクトです.

## plan

1. 'https://shikiho.toyokeizai.net/stocks/{code}/shikiho' をスクレイピングして, 直近4号分の画像を保存する.
   a. まずはplaywright mcpでサイト構造を把握.
   b. 必要であればuserにplaywright操作を記録してもらう.

2. 全上場企業で1を完了させる.

## audit

- `uv run scrape-magazine-audit --cookie-file data/cookies.json`
  - `data/magazines/fact_check_report.json`
    - `issues.raw.json` / `issues.expected.json` / 既存 manifest を突き合わせて、欠号候補を `external_confirmed` / `mixed` / `internal_inferred` で分類する.
  - `data/magazines/auth_diagnostics.json`
    - ライブAPIに対して `issue_list` と代表2号を probe し、`401` / payload `3202` / `1000 + empty magazine` を分類する.
- `scrape-magazine-all` はバッチ開始前に同じ preflight を行い、失敗時は `auth_diagnostics.json` を書いて停止する.

## watchdog

- `scripts/watch-scrape`
  - `uv run scrape` を監視し、異常終了または heartbeat 停止時に再起動する.
- `scripts/watch-scrape-magazine-all`
  - `uv run scrape-magazine-all --resume --verify-after-run` を同様に監視する.
- runtime state と child log は `data/watchdogs/` に保存される.
- 例:
  - `scripts/watch-scrape --idle-seconds 900`
  - `scripts/watch-scrape-magazine-all --idle-seconds 1800`

## monitoring

- プロセス確認:

```bash
ps -ef | rg 'scrape|watch-scrape|uv run'
```

- watchdog heartbeat / restart 状態:

```bash
python - <<'PY'
from pathlib import Path
import json

for name in ["scrape.json", "scrape-magazine-all.json"]:
    path = Path("data/watchdogs") / name
    print(f"== {name} ==")
    if not path.exists():
        print("missing")
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in [
        "pid",
        "command",
        "last_heartbeat_at",
        "last_exit_code",
        "last_restart_reason",
        "restart_count",
    ]:
        print(f"{key}: {data.get(key)}")
    print()
PY
```

- `scrape` の進捗件数:

```bash
python - <<'PY'
from pathlib import Path
import json

path = Path("data/progress.json")
data = json.loads(path.read_text(encoding="utf-8"))
print("completed:", len(data.get("completed", [])))
PY
```

- `scrape-magazine-all` の号単位進捗:

```bash
python - <<'PY'
from pathlib import Path
import json
from collections import Counter

expected = json.loads(Path("data/magazines/issues.expected.json").read_text(encoding="utf-8"))["issues"]
batch = json.loads(Path("data/magazines/batch_progress.json").read_text(encoding="utf-8"))["issues"]

counts = Counter()
for item in expected:
    key = f"{item['calendar']}_{item['series']}"
    record = batch.get(key)
    status = record.get("status", "pending") if isinstance(record, dict) else "pending"
    counts[status] += 1

print(dict(counts))
PY
```

- 欠号監査・認証診断:

```bash
python - <<'PY'
from pathlib import Path
import json

for name in ["fact_check_report.json", "auth_diagnostics.json"]:
    path = Path("data/magazines") / name
    print(f"== {name} ==")
    if not path.exists():
        print("missing")
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    print("generated_at:", data.get("generated_at"))
    print("ok:", data.get("ok"))
    if name == "fact_check_report.json":
        print("leading_missing_groups:", len(data.get("leading_missing_groups", [])))
        print("interior_missing_groups:", len(data.get("interior_missing_groups", [])))
    else:
        print("category_counts:", data.get("category_counts"))
    print()
PY
```

- 直近で更新された出力ファイルを見る:

```bash
find data -path 'data/magazines' -prune -o -type f -name '*.pdf' -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' | sort | tail -n 20
find data/magazines -type f -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' | sort | tail -n 20
```
