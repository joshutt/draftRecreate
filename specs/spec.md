# Draft Replay Simulator — Script Specification

## Overview

A Python script that reads a CSV of last year's draft results and replays the picks into a MySQL/MariaDB database in real-time, preserving the original time gaps between selections. Each pick is applied as an UPDATE targeting a row matched by round, pick, and season.

---

## Input

### CSV File

Path provided as a CLI argument. Required columns:

| Column | Description |
|--------|-------------|
| `round` | Draft round number |
| `pick` | Pick number within the round |
| `team` | Team name or ID making the pick |
| `playerid` | The player being drafted |
| `draft_time` | Timestamp of when the pick was made (e.g. `2024-08-24 19:03:45`) |

### Season Argument

The `--season` flag is a required CLI argument (integer). It specifies the target season for the UPDATE and may differ from the year reflected in the CSV's `draft_time` column.

---

## Configuration

A `.env` file in the script's working directory, loaded via `python-dotenv`:

```
DB_HOST=localhost
DB_PORT=3306
DB_NAME=your_database
DB_USER=your_user
DB_PASSWORD=your_password
DB_TABLE=draft_picks
```

---

## CLI Usage

```bash
python draft_replay.py --csv draft_2024.csv --season 2025
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--csv` | Yes | Path to the input CSV file |
| `--season` | Yes | Target season integer to match in the DB |

---

## Behavior

### Startup

1. Parse the CSV and sort rows by `draft_time` ascending.
2. Validate that all required columns are present.
3. Print a startup summary:

```
Draft replay loaded: 210 picks | Season: 2025 | Estimated duration: 3h 14m
Starting replay...
```

### Replay Loop

For each pick in chronological order:

1. Calculate the time delta to the next pick using the `draft_time` column.
2. Call `time.sleep()` for that duration.
3. Issue an UPDATE to the target DB table (see Database Operation).
4. Print a confirmation line to stdout.

No sleep occurs before the first pick — it fires immediately. The last pick omits the "Next pick in" segment from its output line.

---

## Database Operation

Each pick issues an **UPDATE** — not an INSERT. The `playerid` column is set where `round`, `pick`, and `season` match:

```sql
UPDATE {table}
SET playerid = %s
WHERE round = %s AND pick = %s AND season = %s
```

Values: `(playerid, round, pick, season)` — `season` comes from the `--season` CLI argument, not the CSV.

### Rows Affected Check

After each UPDATE, inspect the affected row count:

| Rows Affected | Action |
|---------------|--------|
| 1 | Success — print confirmation line as normal. |
| 0 | `[WARN] No matching row for Round {r}, Pick {p}, Season {season} — skipped.` |
| 2+ | `[WARN] Round {r}, Pick {p}, Season {season} updated {n} rows — possible data issue.` |

---

## Console Output

### Per Pick

```
[Round 1, Pick 3] Team: LAR | Player: 98234 | Season: 2025 | Next pick in: 142s
```

### Startup

```
Draft replay loaded: 210 picks | Season: 2025 | Estimated duration: 3h 14m
Starting replay...
```

---

## Dependencies

- `python-dotenv` — `.env` config loading
- `mysql-connector-python` or `PyMySQL` — database connectivity
- Standard library: `csv`, `time`, `argparse`, `datetime`

---

## Out of Scope

- No dry-run mode
- No rollback or resume if interrupted mid-replay
- No scaling or compression of timing gaps
- No unique constraint handling on `playerid` (column has no uniqueness requirement)
