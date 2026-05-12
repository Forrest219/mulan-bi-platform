#!/usr/bin/env python3
import sqlglot

# Check valid LOAD DATA syntax for various dialects
for dialect in ['mysql', 'starrocks', 'postgres']:
    try:
        result = sqlglot.parse("LOAD DATA INFILE '/tmp/users.csv' INTO TABLE users", dialect=dialect)
        print(f'{dialect}: {type(result[0]).__name__ if result else None}')
        if result:
            for n in result[0].walk():
                print(f'  {type(n).__name__.upper()}')
    except Exception as e:
        print(f'{dialect}: ERROR - {e}')
    print()

# Also check the COPY TO syntax
print("COPY TO:")
for dialect in ['mysql', 'starrocks', 'postgres']:
    try:
        result = sqlglot.parse("COPY users TO '/tmp/out.csv'", dialect=dialect)
        print(f'{dialect}: {type(result[0]).__name__ if result else None}')
        if result:
            for n in result[0].walk():
                print(f'  {type(n).__name__.upper()}')
    except Exception as e:
        print(f'{dialect}: ERROR - {e}')
    print()