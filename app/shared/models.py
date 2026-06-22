from enum import Enum
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class HealthCheck(BaseModel):
    status: str


class SchoolYearCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_dates(self):
        if not self.name.strip():
            raise ValueError("Name is required.")
        if self.start_date >= self.end_date:
            raise ValueError("Start date must be earlier than end date.")
        return self


class UserRole(str, Enum):
    student = "student"
    teacher = "teacher"


class UserCreate(BaseModel):
    role: UserRole
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: str | None = Field(None, max_length=255)
    pin: str | None = Field(None, pattern=r"^\d{6}$")
    password: str | None = Field(None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_required_fields(self):
        if self.role == UserRole.student and not self.pin:
            raise ValueError("PIN is required for students.")
        if self.role == UserRole.teacher and not self.password:
            raise ValueError("Password is required for teachers.")
        return self

    @model_validator(mode="after")
    def validate_email(self):
        if self.email:
            if "@" not in self.email or "." not in self.email.rsplit("@", 1)[-1]:
                raise ValueError("Invalid email format.")
        return self


class ImportRow(BaseModel):
    row_num: int
    pin: str | None = None
    first_name: str = ""
    last_name: str = ""
    email: str | None = None
    password: str | None = None
    role: Literal["student", "teacher"]
    errors: list[str] = Field(default_factory=list)


class ImportPreview(BaseModel):
    rows: list[ImportRow]
    total_rows: int
    valid_count: int
    error_count: int
    duplicate_count: int = 0
