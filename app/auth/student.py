from dataclasses import dataclass

import aiosqlite
from fastapi import Request


@dataclass
class StudentAuthResult:
    student_id: int
    first_name: str
    last_name: str


_DUMMY_PIN_QUERY = "SELECT id FROM students WHERE pin = ?"

async def verify_student_pin(connection: aiosqlite.Connection, pin: str) -> StudentAuthResult | None:
    connection.row_factory = aiosqlite.Row
    query = (
        "SELECT s.id, s.first_name, s.last_name "
        "FROM students s "
        "JOIN school_years sy ON s.school_year_id = sy.id "
        "WHERE s.pin = ? AND sy.status = 'active'"
    )
    async with connection.execute(query, (pin,)) as cursor:
        row = await cursor.fetchone()

    if not row:
        async with connection.execute(_DUMMY_PIN_QUERY, (pin,)):
            pass
        return None

    return StudentAuthResult(
        student_id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
    )


def create_student_session(request: Request, auth_result: StudentAuthResult) -> None:
    request.session.clear()
    request.session["student_id"] = auth_result.student_id
    request.session["student_name"] = f"{auth_result.first_name} {auth_result.last_name}".strip()
    request.session["student_pin_failures"] = 0


def destroy_student_session(session: dict) -> None:
    session.pop("student_id", None)
    session.pop("student_name", None)
    session.pop("student_pin_failures", None)
