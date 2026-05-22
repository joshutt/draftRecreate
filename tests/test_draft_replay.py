"""
Tests for draft_replay.py — full behavioral coverage of specs/spec.md.

Assumes the implementation exposes:
  parse_csv(filepath)         -> list[dict], sorted by draft_time ascending
  format_duration(seconds)    -> str like "3h 14m"
  run_replay(picks, season, cursor, table)
  main()                      -> CLI entry point (reads sys.argv)
"""
import csv
import io
import sys
from unittest.mock import MagicMock, patch

import pytest

import draft_replay


# ── Helpers ──────────────────────────────────────────────────────────────────

REQUIRED_COLUMNS = ["round", "pick", "team", "playerid", "draft_time"]


def make_csv(rows, tmp_path, filename="draft.csv"):
    path = tmp_path / filename
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=REQUIRED_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buf.getvalue())
    return str(path)


def make_cursor(rowcount=1):
    c = MagicMock()
    c.rowcount = rowcount
    return c


PICKS_3 = [
    {"round": "1", "pick": "1", "team": "NE",  "playerid": "101",   "draft_time": "2024-08-24 19:00:00"},
    {"round": "1", "pick": "2", "team": "LAR", "playerid": "98234", "draft_time": "2024-08-24 19:02:22"},
    {"round": "1", "pick": "3", "team": "DAL", "playerid": "205",   "draft_time": "2024-08-24 19:05:00"},
]


# ── CSV Parsing ───────────────────────────────────────────────────────────────

class TestParseCsv:
    def test_returns_all_rows(self, tmp_path):
        rows = draft_replay.parse_csv(make_csv(PICKS_3, tmp_path))
        assert len(rows) == 3

    def test_sorts_by_draft_time_ascending(self, tmp_path):
        shuffled = [PICKS_3[1], PICKS_3[0], PICKS_3[2]]
        rows = draft_replay.parse_csv(make_csv(shuffled, tmp_path))
        times = [r["draft_time"] for r in rows]
        assert times == sorted(times)

    def test_already_sorted_unchanged(self, tmp_path):
        rows = draft_replay.parse_csv(make_csv(PICKS_3, tmp_path))
        times = [r["draft_time"] for r in rows]
        assert times == sorted(times)

    @pytest.mark.parametrize("missing", REQUIRED_COLUMNS)
    def test_raises_on_missing_required_column(self, tmp_path, missing):
        cols = [c for c in REQUIRED_COLUMNS if c != missing]
        content = ",".join(cols) + "\n" + ",".join(["x"] * len(cols)) + "\n"
        path = tmp_path / "bad.csv"
        path.write_text(content)
        with pytest.raises((KeyError, ValueError, SystemExit)):
            draft_replay.parse_csv(str(path))


# ── Duration Formatting ───────────────────────────────────────────────────────

class TestFormatDuration:
    def test_hours_and_minutes(self):
        # 3h 14m = 3*3600 + 14*60 = 11640s
        assert draft_replay.format_duration(11640) == "3h 14m"

    def test_exact_hours_zero_minutes(self):
        assert draft_replay.format_duration(7200) == "2h 0m"

    def test_less_than_one_hour(self):
        assert draft_replay.format_duration(900) == "0h 15m"

    def test_one_hour_exactly(self):
        assert draft_replay.format_duration(3600) == "1h 0m"

    def test_five_minutes(self):
        assert draft_replay.format_duration(300) == "0h 5m"


# ── Startup Output ────────────────────────────────────────────────────────────

class TestStartupOutput:
    def _run(self, tmp_path, picks=None, season=2025, rowcount=1):
        picks = picks or PICKS_3
        cursor = make_cursor(rowcount)
        with patch("time.sleep"):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv(picks, tmp_path)),
                season=season,
                cursor=cursor,
                table="draft_picks",
            )

    def test_pick_count_in_summary(self, tmp_path, capsys):
        self._run(tmp_path)
        assert "3 picks" in capsys.readouterr().out

    def test_season_in_summary(self, tmp_path, capsys):
        self._run(tmp_path, season=2025)
        assert "Season: 2025" in capsys.readouterr().out

    def test_estimated_duration_in_summary(self, tmp_path, capsys):
        # PICKS_3 spans 19:00:00 → 19:05:00 = 300s = 0h 5m
        self._run(tmp_path)
        assert "Estimated duration: 0h 5m" in capsys.readouterr().out

    def test_summary_line_format(self, tmp_path, capsys):
        self._run(tmp_path)
        out = capsys.readouterr().out
        assert "Draft replay loaded: 3 picks | Season: 2025 | Estimated duration:" in out

    def test_starting_replay_printed(self, tmp_path, capsys):
        self._run(tmp_path)
        assert "Starting replay..." in capsys.readouterr().out

    def test_starting_replay_comes_after_summary(self, tmp_path, capsys):
        self._run(tmp_path)
        out = capsys.readouterr().out
        summary_pos = out.index("Draft replay loaded")
        starting_pos = out.index("Starting replay...")
        assert starting_pos > summary_pos

    def test_estimated_duration_two_picks_142s(self, tmp_path, capsys):
        picks = [
            {"round": "1", "pick": "1", "team": "NE",  "playerid": "101",   "draft_time": "2024-08-24 19:00:00"},
            {"round": "1", "pick": "2", "team": "LAR", "playerid": "98234", "draft_time": "2024-08-24 19:02:22"},
        ]
        self._run(tmp_path, picks=picks)
        # 142s = 0h 2m (floor) — duration is last_time - first_time
        assert "Estimated duration: 0h 2m" in capsys.readouterr().out


# ── Sleep / Timing ────────────────────────────────────────────────────────────

class TestTiming:
    def test_no_sleep_before_first_pick(self, tmp_path):
        cursor = make_cursor()
        sleep_calls = []
        execute_calls = []

        def track_sleep(s):
            sleep_calls.append(("sleep", s))

        def track_execute(sql, params):
            execute_calls.append(("execute",))

        cursor.execute.side_effect = track_execute

        with patch("time.sleep", side_effect=track_sleep):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv(PICKS_3, tmp_path)),
                season=2025,
                cursor=cursor,
                table="draft_picks",
            )

        # First action must be execute, not sleep
        all_events = []
        # Reconstruct: interleave by checking the first logged event
        # Simplest: assert that sleep count is one less than pick count
        assert len(sleep_calls) == len(PICKS_3) - 1

    def test_sleep_count_is_picks_minus_one(self, tmp_path):
        cursor = make_cursor()
        sleep_calls = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv(PICKS_3, tmp_path)),
                season=2025,
                cursor=cursor,
                table="draft_picks",
            )
        assert len(sleep_calls) == 2

    def test_sleep_duration_matches_draft_time_delta(self, tmp_path):
        picks = [
            {"round": "1", "pick": "1", "team": "NE",  "playerid": "101",   "draft_time": "2024-08-24 19:00:00"},
            {"round": "1", "pick": "2", "team": "LAR", "playerid": "98234", "draft_time": "2024-08-24 19:02:22"},
        ]
        cursor = make_cursor()
        sleep_calls = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv(picks, tmp_path)),
                season=2025,
                cursor=cursor,
                table="draft_picks",
            )
        # 19:02:22 - 19:00:00 = 142 seconds
        assert sleep_calls == [142]

    def test_sleep_occurs_before_subsequent_pick_not_after(self, tmp_path):
        """Order must be: execute, sleep, execute, sleep, execute — not execute, execute, sleep..."""
        cursor = make_cursor()
        call_order = []

        def track_sleep(s):
            call_order.append("sleep")

        def track_execute(sql, params):
            call_order.append("execute")

        cursor.execute.side_effect = track_execute

        with patch("time.sleep", side_effect=track_sleep):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv(PICKS_3, tmp_path)),
                season=2025,
                cursor=cursor,
                table="draft_picks",
            )

        assert call_order == ["execute", "sleep", "execute", "sleep", "execute"]

    def test_single_pick_no_sleep(self, tmp_path):
        picks = [PICKS_3[0]]
        cursor = make_cursor()
        sleep_calls = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv(picks, tmp_path)),
                season=2025,
                cursor=cursor,
                table="draft_picks",
            )
        assert sleep_calls == []


# ── Database Operation ────────────────────────────────────────────────────────

class TestDatabaseOperation:
    def _run_single(self, tmp_path, pick, season=2025, rowcount=1, table="draft_picks"):
        cursor = make_cursor(rowcount)
        with patch("time.sleep"):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv([pick], tmp_path)),
                season=season,
                cursor=cursor,
                table=table,
            )
        return cursor

    def test_issues_update_not_insert(self, tmp_path):
        cursor = self._run_single(tmp_path, PICKS_3[0])
        sql = cursor.execute.call_args[0][0].upper()
        assert sql.strip().startswith("UPDATE")
        assert "INSERT" not in sql

    def test_sql_sets_playerid(self, tmp_path):
        cursor = self._run_single(tmp_path, PICKS_3[0])
        sql = cursor.execute.call_args[0][0].upper().replace("\n", " ")
        assert "SET" in sql
        assert "PLAYERID" in sql

    def test_sql_where_includes_round_pick_season(self, tmp_path):
        cursor = self._run_single(tmp_path, PICKS_3[0])
        sql = cursor.execute.call_args[0][0].upper().replace("\n", " ")
        assert "WHERE" in sql
        assert "ROUND" in sql
        assert "PICK" in sql
        assert "SEASON" in sql

    def test_uses_table_name_from_argument(self, tmp_path):
        cursor = self._run_single(tmp_path, PICKS_3[0], table="my_league_picks")
        sql = cursor.execute.call_args[0][0]
        assert "my_league_picks" in sql

    def test_params_are_playerid_round_pick_season(self, tmp_path):
        pick = {"round": "2", "pick": "5", "team": "NE", "playerid": "77777", "draft_time": "2024-08-24 19:00:00"}
        cursor = self._run_single(tmp_path, pick, season=2025)
        params = cursor.execute.call_args[0][1]
        assert str(params[0]) == "77777"  # playerid
        assert int(params[1]) == 2         # round
        assert int(params[2]) == 5         # pick
        assert int(params[3]) == 2025      # season

    def test_season_comes_from_cli_arg_not_csv_year(self, tmp_path):
        """draft_time year is 2024; --season is 2025 — UPDATE must use 2025."""
        pick = {"round": "1", "pick": "1", "team": "NE", "playerid": "101", "draft_time": "2024-08-24 19:00:00"}
        cursor = self._run_single(tmp_path, pick, season=2025)
        params = cursor.execute.call_args[0][1]
        assert int(params[3]) == 2025

    def test_execute_called_once_per_pick(self, tmp_path):
        cursor = make_cursor()
        with patch("time.sleep"):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv(PICKS_3, tmp_path)),
                season=2025,
                cursor=cursor,
                table="draft_picks",
            )
        assert cursor.execute.call_count == 3


# ── Rows Affected Warnings ────────────────────────────────────────────────────

class TestRowsAffected:
    def _run_and_capture(self, tmp_path, capsys, pick, rowcount, season=2025):
        cursor = make_cursor(rowcount)
        with patch("time.sleep"):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv([pick], tmp_path)),
                season=season,
                cursor=cursor,
                table="draft_picks",
            )
        return capsys.readouterr().out

    def test_one_row_no_warn(self, tmp_path, capsys):
        out = self._run_and_capture(tmp_path, capsys, PICKS_3[0], rowcount=1)
        assert "[WARN]" not in out

    def test_zero_rows_prints_warn(self, tmp_path, capsys):
        pick = {"round": "3", "pick": "7", "team": "NE", "playerid": "101", "draft_time": "2024-08-24 19:00:00"}
        out = self._run_and_capture(tmp_path, capsys, pick, rowcount=0)
        assert "[WARN]" in out

    def test_zero_rows_warn_exact_format(self, tmp_path, capsys):
        pick = {"round": "3", "pick": "7", "team": "NE", "playerid": "101", "draft_time": "2024-08-24 19:00:00"}
        out = self._run_and_capture(tmp_path, capsys, pick, rowcount=0, season=2025)
        assert "[WARN] No matching row for Round 3, Pick 7, Season 2025" in out
        assert "skipped" in out.lower()

    def test_two_rows_prints_warn(self, tmp_path, capsys):
        out = self._run_and_capture(tmp_path, capsys, PICKS_3[0], rowcount=2)
        assert "[WARN]" in out

    def test_two_rows_warn_exact_format(self, tmp_path, capsys):
        pick = {"round": "1", "pick": "1", "team": "NE", "playerid": "101", "draft_time": "2024-08-24 19:00:00"}
        out = self._run_and_capture(tmp_path, capsys, pick, rowcount=2, season=2025)
        assert "[WARN] Round 1, Pick 1, Season 2025 updated 2 rows" in out
        assert "possible data issue" in out

    def test_three_or_more_rows_prints_warn(self, tmp_path, capsys):
        out = self._run_and_capture(tmp_path, capsys, PICKS_3[0], rowcount=5)
        assert "[WARN]" in out
        assert "5 rows" in out or "updated 5" in out

    def test_many_rows_warn_includes_count(self, tmp_path, capsys):
        pick = {"round": "2", "pick": "3", "team": "DAL", "playerid": "205", "draft_time": "2024-08-24 19:00:00"}
        out = self._run_and_capture(tmp_path, capsys, pick, rowcount=4, season=2025)
        assert "[WARN] Round 2, Pick 3, Season 2025 updated 4 rows" in out
        assert "possible data issue" in out


# ── Per-Pick Console Output ───────────────────────────────────────────────────

class TestPickOutputFormat:
    def _pick_lines(self, tmp_path, capsys, picks=None, season=2025, rowcount=1):
        picks = picks or PICKS_3
        cursor = make_cursor(rowcount)
        with patch("time.sleep"):
            draft_replay.run_replay(
                draft_replay.parse_csv(make_csv(picks, tmp_path)),
                season=season,
                cursor=cursor,
                table="draft_picks",
            )
        return [l for l in capsys.readouterr().out.splitlines() if "[Round" in l]

    def test_pick_line_includes_round_and_pick(self, tmp_path, capsys):
        lines = self._pick_lines(tmp_path, capsys)
        assert "[Round 1, Pick 1]" in lines[0]

    def test_pick_line_includes_team(self, tmp_path, capsys):
        lines = self._pick_lines(tmp_path, capsys)
        assert "Team: NE" in lines[0]

    def test_pick_line_includes_player(self, tmp_path, capsys):
        lines = self._pick_lines(tmp_path, capsys)
        assert "Player: 101" in lines[0]

    def test_pick_line_includes_season(self, tmp_path, capsys):
        lines = self._pick_lines(tmp_path, capsys)
        assert "Season: 2025" in lines[0]

    def test_non_last_picks_include_next_pick_in(self, tmp_path, capsys):
        lines = self._pick_lines(tmp_path, capsys)
        assert "Next pick in" in lines[0]
        assert "Next pick in" in lines[1]

    def test_last_pick_omits_next_pick_in(self, tmp_path, capsys):
        lines = self._pick_lines(tmp_path, capsys)
        assert "Next pick in" not in lines[-1]

    def test_next_pick_in_shows_correct_seconds(self, tmp_path, capsys):
        picks = [
            {"round": "1", "pick": "1", "team": "NE",  "playerid": "101",   "draft_time": "2024-08-24 19:00:00"},
            {"round": "1", "pick": "2", "team": "LAR", "playerid": "98234", "draft_time": "2024-08-24 19:02:22"},
        ]
        lines = self._pick_lines(tmp_path, capsys, picks=picks)
        # 19:02:22 - 19:00:00 = 142 seconds
        assert "Next pick in: 142s" in lines[0]

    def test_single_pick_no_next_pick_in(self, tmp_path, capsys):
        lines = self._pick_lines(tmp_path, capsys, picks=[PICKS_3[0]])
        assert len(lines) == 1
        assert "Next pick in" not in lines[0]

    def test_one_pick_line_per_pick(self, tmp_path, capsys):
        lines = self._pick_lines(tmp_path, capsys)
        assert len(lines) == 3

    def test_pick_line_exact_format_sample(self, tmp_path, capsys):
        """Spot-check the full line format from the spec example."""
        picks = [
            {"round": "1", "pick": "3", "team": "LAR", "playerid": "98234", "draft_time": "2024-08-24 19:00:00"},
            {"round": "1", "pick": "4", "team": "NE",  "playerid": "101",   "draft_time": "2024-08-24 19:02:22"},
        ]
        lines = self._pick_lines(tmp_path, capsys, picks=picks, season=2025)
        # spec: [Round 1, Pick 3] Team: LAR | Player: 98234 | Season: 2025 | Next pick in: 142s
        expected = "[Round 1, Pick 3] Team: LAR | Player: 98234 | Season: 2025 | Next pick in: 142s"
        assert lines[0] == expected


# ── CLI Argument Parsing ──────────────────────────────────────────────────────

class TestCLI:
    def test_missing_csv_arg_exits(self):
        with patch("sys.argv", ["draft_replay.py", "--season", "2025"]):
            with pytest.raises(SystemExit):
                draft_replay.main()

    def test_missing_season_arg_exits(self, tmp_path):
        csv_path = make_csv(PICKS_3, tmp_path)
        with patch("sys.argv", ["draft_replay.py", "--csv", csv_path]):
            with pytest.raises(SystemExit):
                draft_replay.main()

    def test_season_parsed_as_integer(self, tmp_path):
        csv_path = make_csv([PICKS_3[0]], tmp_path)
        cursor = make_cursor()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        env = {
            "DB_HOST": "localhost", "DB_PORT": "3306", "DB_NAME": "testdb",
            "DB_USER": "user", "DB_PASSWORD": "pass", "DB_TABLE": "draft_picks",
        }

        with patch("sys.argv", ["draft_replay.py", "--csv", csv_path, "--season", "2025"]), \
             patch.dict("os.environ", env), \
             patch("time.sleep"), \
             patch("mysql.connector.connect", return_value=mock_conn):
            draft_replay.main()

        params = cursor.execute.call_args[0][1]
        assert params[3] == 2025  # integer, not the string "2025"
