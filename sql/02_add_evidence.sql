-- Step 3: store the exact phrase from the article that proves each signal.
-- Run once in the Supabase SQL editor, after 01_schema.sql.

alter table signals add column if not exists evidence text;
