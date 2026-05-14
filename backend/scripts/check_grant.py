#!/usr/bin/env python3
from sqlglot import exp
import sqlglot

tests = [
    "GRANT ALL ON users TO 'root'@'localhost'",
    "REVOKE ALL ON users FROM 'root'@'localhost'",
    "ALTER TABLE users ADD COLUMN age INT",
    "CREATE TABLE t (id INT)",
    "DROP TABLE users",
]
for sql in tests:
    result = sqlglot.parse(sql, dialect='postgres')
    stmt = result[0]
    print(f'SQL: {sql[:40]}')
    print(f'  Top type: {type(stmt).__name__}')
    for n in stmt.walk():
        print(f'  node: {type(n).__name__.upper()}')
    print()