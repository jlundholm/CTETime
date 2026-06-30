from pathlib import Path

import aiosqlite


ROOT_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT_DIR / "migrations"


async def run_migrations(database_path: str) -> None:
    db_file = Path(database_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    async with aiosqlite.connect(database_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON;")

        for sql_file in sql_files:
            migration_sql = sql_file.read_text(encoding="utf-8")
            await connection.executescript(migration_sql)

        await connection.commit()
