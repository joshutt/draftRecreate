#!/usr/bin/env python3
import argparse
import csv
import os
import time
from datetime import datetime

from dotenv import load_dotenv
import mysql.connector

REQUIRED_COLUMNS = ["round", "pick", "team", "playerid", "draft_time"]


def parse_csv(filepath):
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = set(reader.fieldnames or [])

    for col in REQUIRED_COLUMNS:
        if col not in fieldnames:
            raise ValueError(f"Missing required column: {col}")

    rows.sort(key=lambda r: r["draft_time"])
    return rows


def format_duration(seconds):
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    return f"{hours}h {minutes}m"


def run_replay(picks, season, cursor, table):
    if not picks:
        return

    first_time = datetime.strptime(picks[0]["draft_time"], "%Y-%m-%d %H:%M:%S")
    last_time = datetime.strptime(picks[-1]["draft_time"], "%Y-%m-%d %H:%M:%S")
    total_seconds = (last_time - first_time).total_seconds()

    print(f"Draft replay loaded: {len(picks)} picks | Season: {season} | Estimated duration: {format_duration(total_seconds)}")
    print("Starting replay...")

    for i, pick in enumerate(picks):
        if i > 0:
            prev_time = datetime.strptime(picks[i - 1]["draft_time"], "%Y-%m-%d %H:%M:%S")
            curr_time = datetime.strptime(pick["draft_time"], "%Y-%m-%d %H:%M:%S")
            delta = int((curr_time - prev_time).total_seconds())
            time.sleep(delta)

        sql = f"UPDATE {table} SET playerid = %s WHERE round = %s AND pick = %s AND season = %s"
        params = (pick["playerid"], int(pick["round"]), int(pick["pick"]), int(season))
        cursor.execute(sql, params)

        r = pick["round"]
        p = pick["pick"]
        rowcount = cursor.rowcount

        if rowcount == 0:
            print(f"[WARN] No matching row for Round {r}, Pick {p}, Season {season} — skipped.")
        elif rowcount >= 2:
            print(f"[WARN] Round {r}, Pick {p}, Season {season} updated {rowcount} rows — possible data issue.")
        else:
            if i < len(picks) - 1:
                curr_time = datetime.strptime(pick["draft_time"], "%Y-%m-%d %H:%M:%S")
                next_time = datetime.strptime(picks[i + 1]["draft_time"], "%Y-%m-%d %H:%M:%S")
                next_delta = int((next_time - curr_time).total_seconds())
                print(f"[Round {r}, Pick {p}] Team: {pick['team']} | Player: {pick['playerid']} | Season: {season} | Next pick in: {next_delta}s")
            else:
                print(f"[Round {r}, Pick {p}] Team: {pick['team']} | Player: {pick['playerid']} | Season: {season}")


def main():
    parser = argparse.ArgumentParser(description="Replay a fantasy draft into the database.")
    parser.add_argument("--csv", required=True, help="Path to the draft CSV file")
    parser.add_argument("--season", required=True, type=int, help="Target season integer")
    args = parser.parse_args()

    load_dotenv()

    host = os.environ["DB_HOST"]
    port = int(os.environ.get("DB_PORT", 3306))
    db_name = os.environ["DB_NAME"]
    user = os.environ["DB_USER"]
    password = os.environ["DB_PASSWORD"]
    table = os.environ["DB_TABLE"]

    picks = parse_csv(args.csv)

    conn = mysql.connector.connect(
        host=host,
        port=port,
        database=db_name,
        user=user,
        password=password,
    )
    cursor = conn.cursor()

    try:
        run_replay(picks, season=args.season, cursor=cursor, table=table)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
