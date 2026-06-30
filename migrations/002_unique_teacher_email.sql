-- Add unique index on teachers.email to prevent duplicate teacher accounts
-- (If existing duplicates exist, this will fail with a clear error;
--  manually resolve by updating or removing duplicates first.)

CREATE UNIQUE INDEX IF NOT EXISTS idx_teachers_email ON teachers(email);
