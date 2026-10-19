"""Small adapter for the queue's existing, parameterized SQLite SQL.

Connections use autocommit for standalone statements; explicit BEGIN / COMMIT
blocks remain real transactions. Closing a failed block rolls it back.
"""
import re
import sqlite3

import psycopg
from psycopg.rows import dict_row


def placeholders(query: str) -> str:
    # Only replace placeholders outside quoted SQL strings/identifiers.
    return re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\?", lambda m: '%s' if m[0] == '?' else m[0], query)


class PgCompatConnection:
    def __init__(self, database_url: str):
        self.raw = psycopg.connect(database_url, autocommit=True, row_factory=dict_row, connect_timeout=10)

    def execute(self, query, parameters=None):
        command = query.strip().rstrip(';').upper()
        if command.startswith('PRAGMA '):
            return None
        if command == 'BEGIN IMMEDIATE':
            query = 'BEGIN'
        try:
            return self.raw.execute(placeholders(query), parameters)
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError('PostgreSQL integrity constraint failed') from exc

    def executescript(self, script):
        with self.raw.transaction():
            for statement in script.split(';'):
                if statement.strip():
                    self.execute(statement)

    def close(self):
        self.raw.close()
