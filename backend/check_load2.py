#!/usr/bin/env python3
import sqlglot
from sqlglot import exp

# Check LOAD DATA when it fails to parse
sql = "LOAD DATA INFILE '/tmp/users.csv' INTO TABLE users"
result = sqlglot.parse(sql, dialect='mysql')
print("Result:", result)
print("First:", type(result[0]).__name__ if result else None)
if result:
    for n in result[0].walk():
        print(f"  {type(n).__name__.upper()}, isinstance Command: {isinstance(n, exp.Command)}")
        if isinstance(n, exp.Command):
            print(f"    args: {n.args}")