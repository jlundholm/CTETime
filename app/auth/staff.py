from dataclasses import dataclass

import aiosqlite
import bcrypt


@dataclass
class StaffAuthResult:
    admin_id: int
    email: str
    first_name: str
    last_name: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


_DUMMY_HASH = hash_password("dummy-timing-guard")


async def authenticate_admin(database_path: str, email: str, password: str) -> StaffAuthResult | None:
    query = (
        "SELECT id, email, first_name, last_name, password_hash "
        "FROM admins WHERE lower(email) = lower(?)"
    )

    async with aiosqlite.connect(database_path) as connection:
        connection.row_factory = aiosqlite.Row
        async with connection.execute(query, (email.strip(),)) as cursor:
            row = await cursor.fetchone()

    if not row:
        verify_password(password, _DUMMY_HASH)
        return None

    if not verify_password(password, row["password_hash"]):
        return None

    return StaffAuthResult(
        admin_id=row["id"],
        email=row["email"],
        first_name=row["first_name"],
        last_name=row["last_name"],
    )


def create_session(session: dict, auth_result: StaffAuthResult) -> None:
    session["admin_id"] = auth_result.admin_id
    session["admin_email"] = auth_result.email
    session["admin_name"] = f"{auth_result.first_name} {auth_result.last_name}".strip()


def destroy_session(session: dict) -> None:
    session.pop("admin_id", None)
    session.pop("admin_email", None)
    session.pop("admin_name", None)
