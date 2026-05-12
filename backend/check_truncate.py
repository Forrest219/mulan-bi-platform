#!/usr/bin/env python3
from sqlglot import exp
import sqlglot

# Test: what type is the statement for TRUNCATE TABLE?
result = sqlglot.parse('TRUNCATE TABLE users', dialect='postgres')
stmt = result[0]
print('Top-level type name:', type(stmt).__name__)

# walk all nodes
for n in stmt.walk():
    tn = type(n).__name__.upper()
    print(' node:', tn, '| isinstance TruncateTable:', isinstance(n, exp.TruncateTable))

print()
# Confirm Drop works
result2 = sqlglot.parse('DROP TABLE users', dialect='postgres')
stmt2 = result2[0]
print('DROP top-level:', type(stmt2).__name__)
for n in stmt2.walk():
    print(' node:', type(n).__name__.upper(), '| isinstance exp.Drop:', isinstance(n, exp.Drop))