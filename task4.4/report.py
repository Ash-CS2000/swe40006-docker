#!/usr/bin/env python3
"""
StayEasy Report - a command-line booking analytics tool (non-web app)
SWE40006 Task 4.4 - Aung Si Hein

Reads a CSV of hotel bookings, prints a revenue report in the terminal,
and can export the summary to a CSV or JSON file.

Examples:
  python report.py sample/bookings.csv
  python report.py /data/bookings.csv --city Penang --from 2026-08-01 --to 2026-08-31
  python report.py /data/bookings.csv --output /data/summary.json

Exit codes:
  0  report produced
  1  input problem (file missing, wrong columns, no matching bookings)
  2  bad command-line arguments (argparse)
"""
import argparse
import csv
import json
import socket
import platform
import sys
from collections import defaultdict
from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
err = Console(stderr=True)

REQUIRED_COLUMNS = {"reference", "hotel", "city", "room_type", "check_in",
                    "check_out", "guests", "total", "status"}


# --------------------------------------------------------------- arguments ---

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="stayeasy-report",
        description="Generate a revenue report from a StayEasy bookings CSV.")
    p.add_argument("csv_file", nargs="?", default="sample/bookings.csv",
                   help="path to the bookings CSV file (default: built-in sample data)")
    p.add_argument("--city", help="only include bookings in this city (e.g. Penang)")
    p.add_argument("--from", dest="date_from", type=date.fromisoformat,
                   help="only include stays checking in on/after this date (YYYY-MM-DD)")
    p.add_argument("--to", dest="date_to", type=date.fromisoformat,
                   help="only include stays checking in on/before this date (YYYY-MM-DD)")
    p.add_argument("--output", "-o",
                   help="export the per-hotel summary to this file (.csv or .json)")
    p.add_argument("--top", type=int, default=0,
                   help="show only the top N hotels by revenue")
    return p.parse_args(argv)


# ------------------------------------------------------------------ input ---

def load_bookings(path):
    """Read and validate the CSV. Bad rows are skipped and counted, not fatal."""
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
            rows, skipped = [], 0
            for row in reader:
                try:
                    row["check_in"] = date.fromisoformat(row["check_in"])
                    row["check_out"] = date.fromisoformat(row["check_out"])
                    row["total"] = float(row["total"])
                    row["guests"] = int(row["guests"])
                    row["nights"] = (row["check_out"] - row["check_in"]).days
                    if row["nights"] <= 0:
                        raise ValueError("check-out not after check-in")
                    rows.append(row)
                except (ValueError, TypeError):
                    skipped += 1
            return rows, skipped
    except FileNotFoundError:
        raise ValueError(f"File not found: {path}\n"
                         "Hint: inside Docker, mount the folder first, e.g. "
                         "-v \"$PWD/data:/data\" and use /data/<file>.csv")


def apply_filters(rows, args):
    if args.city:
        rows = [r for r in rows if r["city"].lower() == args.city.lower()]
    if args.date_from:
        rows = [r for r in rows if r["check_in"] >= args.date_from]
    if args.date_to:
        rows = [r for r in rows if r["check_in"] <= args.date_to]
    return rows


# --------------------------------------------------------------- analysis ---

def summarise(rows):
    """Group by hotel. Cancelled bookings count toward the cancellation rate only."""
    hotels = defaultdict(lambda: {"city": "", "bookings": 0, "cancelled": 0,
                                  "room_nights": 0, "guests": 0, "revenue": 0.0})
    for r in rows:
        h = hotels[r["hotel"]]
        h["city"] = r["city"]
        if r["status"] == "cancelled":
            h["cancelled"] += 1
            continue
        h["bookings"] += 1
        h["room_nights"] += r["nights"]
        h["guests"] += r["guests"]
        h["revenue"] += r["total"]

    summary = []
    for name, h in hotels.items():
        all_bookings = h["bookings"] + h["cancelled"]
        summary.append({
            "hotel": name,
            "city": h["city"],
            "bookings": h["bookings"],
            "cancelled": h["cancelled"],
            "cancellation_rate": round(h["cancelled"] / all_bookings * 100, 1) if all_bookings else 0.0,
            "room_nights": h["room_nights"],
            "guests": h["guests"],
            "revenue": round(h["revenue"], 2),
            # ADR = Average Daily Rate, the hotel industry's "average price per room per night"
            "adr": round(h["revenue"] / h["room_nights"], 2) if h["room_nights"] else 0.0,
        })
    summary.sort(key=lambda s: s["revenue"], reverse=True)
    return summary


def by_month(rows):
    months = defaultdict(float)
    for r in rows:
        if r["status"] != "cancelled":
            months[r["check_in"].strftime("%Y-%m")] += r["total"]
    return dict(sorted(months.items()))


# ----------------------------------------------------------------- output ---

def print_report(summary, months, args, total_rows, skipped):
    scope = [args.city.title() if args.city else "All cities"]
    if args.date_from or args.date_to:
        scope.append(f"{args.date_from or '...'} to {args.date_to or '...'}")
    console.print(Panel.fit(
        f"[bold]StayEasy Revenue Report[/bold]\n"
        f"Scope: {' | '.join(scope)}\n"
        f"[dim]Rows analysed: {total_rows}   Skipped (invalid): {skipped}\n"
        f"Running in container {socket.gethostname()} on {platform.machine()}[/dim]",
        border_style="blue"))

    table = Table(title="Performance by hotel", header_style="bold white on blue")
    table.add_column("#", justify="right")
    table.add_column("Hotel")
    table.add_column("City")
    table.add_column("Bookings", justify="right")
    table.add_column("Cancel %", justify="right")
    table.add_column("Room-nights", justify="right")
    table.add_column("ADR (MYR)", justify="right")
    table.add_column("Revenue (MYR)", justify="right", style="bold green")

    shown = summary[:args.top] if args.top else summary
    for i, s in enumerate(shown, 1):
        cancel_colour = "red" if s["cancellation_rate"] >= 20 else "yellow" if s["cancellation_rate"] >= 10 else "green"
        table.add_row(str(i), s["hotel"], s["city"], str(s["bookings"]),
                      f"[{cancel_colour}]{s['cancellation_rate']:.1f}%[/]",
                      str(s["room_nights"]), f"{s['adr']:,.0f}", f"{s['revenue']:,.0f}")

    totals = {k: sum(s[k] for s in summary) for k in ("bookings", "cancelled", "room_nights", "revenue")}
    all_b = totals["bookings"] + totals["cancelled"]
    table.add_section()
    table.add_row("", "[bold]TOTAL[/]", "", f"[bold]{totals['bookings']}[/]",
                  f"[bold]{(totals['cancelled'] / all_b * 100) if all_b else 0:.1f}%[/]",
                  f"[bold]{totals['room_nights']}[/]",
                  f"[bold]{(totals['revenue'] / totals['room_nights']) if totals['room_nights'] else 0:,.0f}[/]",
                  f"[bold]{totals['revenue']:,.0f}[/]")
    console.print(table)

    # simple text bar chart of revenue per month
    if months:
        console.print("\n[bold]Revenue by check-in month[/bold]")
        peak = max(months.values())
        for m, v in months.items():
            bar = "█" * max(1, int(v / peak * 40))
            console.print(f"  {m}  [cyan]{bar}[/cyan] MYR {v:,.0f}")


def export(summary, path):
    if path.endswith(".json"):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"generated": date.today().isoformat(), "hotels": summary}, fh, indent=2)
    elif path.endswith(".csv"):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
            w.writeheader()
            w.writerows(summary)
    else:
        raise ValueError("--output must end in .csv or .json")


# ------------------------------------------------------------------- main ---

def main(argv=None):
    args = parse_args(argv)
    try:
        rows, skipped = load_bookings(args.csv_file)
        rows = apply_filters(rows, args)
        if not rows:
            raise ValueError("No bookings match those filters.")
        summary = summarise(rows)
        print_report(summary, by_month(rows), args, len(rows), skipped)
        if args.output:
            export(summary, args.output)
            console.print(f"\n[green]✓ Summary exported to {args.output}[/green]")
    except ValueError as e:
        err.print(f"[bold red]Error:[/bold red] {e}")
        return 1
    except PermissionError as e:
        err.print(f"[bold red]Error:[/bold red] cannot write file ({e.filename}). "
                  "Check the mounted folder's permissions.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
