CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS school_years (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'ended'))
);

CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    school_year_id INTEGER REFERENCES school_years(id)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT,
    pin TEXT NOT NULL,
    school_year_id INTEGER NOT NULL REFERENCES school_years(id)
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id),
    school_year_id INTEGER NOT NULL REFERENCES school_years(id)
);

CREATE TABLE IF NOT EXISTS enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL REFERENCES classes(id),
    student_id INTEGER NOT NULL REFERENCES students(id)
);

CREATE TABLE IF NOT EXISTS punches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    clock_in_time TEXT NOT NULL,
    clock_out_time TEXT,
    manual INTEGER NOT NULL DEFAULT 0,
    school_year_id INTEGER NOT NULL REFERENCES school_years(id)
);

CREATE INDEX IF NOT EXISTS idx_punches_student ON punches(student_id, school_year_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_punches_active ON punches(student_id, school_year_id) WHERE clock_out_time IS NULL;
CREATE INDEX IF NOT EXISTS idx_enrollments_class ON enrollments(class_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_students_pin ON students(pin, school_year_id);
