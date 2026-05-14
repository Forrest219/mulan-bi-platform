#!/usr/bin/env python3
import sqlglot

cases = [
    ("LOAD DATA INFILE '/tmp/users.csv' INTO TABLE users", "mysql"),
    ("SELECT * FROM users INTO OUTFILE '/tmp/out.csv'", "mysql"),
    ("COPY users TO '/tmp/out.csv'", "postgres"),
]

for sql, dialect in cases:
    print(f"SQL: {sql[:50]} | dialect: {dialect}")
    try:
        result = sqlglot.parse(sql, dialect=dialect)
        print(f"  -> type: {type(result[0]).__name__}")
        for n in result[0].walk():
            print(f"    node: {type(n).__name__.upper()}")
    except Exception as e:
        print(f"  -> PARSE ERROR: {e}")
    print()