from pathlib import Path

import aiosqlite


ROOT_DIR = Path(__file__).resolve().parent.parent
INITIAL_MIGRATION = ROOT_DIR / "migrations" / "001_initial_schema.sql"


async def run_migrations(database_path: str) -> None:
    db_file = Path(database_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    migration_sql = INITIAL_MIGRATION.read_text(encoding="utf-8")

    async with aiosqlite.connect(database_path) as connection:
        await connection.executescript("PRAGMA foreign_keys = ON;\n" + migration_sql)
        await connection.commit()
