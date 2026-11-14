import sqlite3


def extract(path):
    with open(path, encoding="utf-8") as handle:
        return [line.rstrip().split(",") for line in handle]


def clean(rows):
    return [row for row in rows if len(row) == 2 and row[1].isdigit()]


def aggregate(rows):
    totals = {}
    for name, amount in rows:
        totals[name] = totals.get(name, 0) + int(amount)
    return sorted(totals.items())


def load(totals, database):
    connection = sqlite3.connect(database)
    connection.executemany("INSERT INTO totals(name, amount) VALUES (?, ?)", totals)
    connection.commit()


def run(path, database):
    raw = extract(path)
    valid = clean(raw)
    totals = aggregate(valid)
    load(totals, database)
