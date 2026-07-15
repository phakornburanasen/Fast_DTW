-- db/migrate_job_id_to_date_bigint.sql
-- Extend the existing schema with a public date-based job number.
--
-- The original relational key stays unchanged:
--   tf_job_log.job_id INT IDENTITY(1,1)
--   tf_job_step/job_document/job_item.job_id INT foreign keys
--
-- This migration adds:
--   tf_job_log.job_no BIGINT NOT NULL UNIQUE
--
-- job_no is exposed by the API as the user-facing job_id:
--   20260714001, 20260714002, ...
--
-- Important:
-- - Back up FAST_DTW before running this migration.
-- - Run during a quiet period so no new jobs are inserted while backfilling.
-- - Existing rows are backfilled from created_at, ordered by original job_id.

USE FAST_DTW;
GO

SET XACT_ABORT ON;
GO

BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.tf_job_log', N'U') IS NULL
BEGIN
    THROW 51010, 'Table dbo.tf_job_log was not found.', 1;
END;

IF COL_LENGTH(N'dbo.tf_job_log', N'head_backup_path') IS NULL
BEGIN
    ALTER TABLE dbo.tf_job_log
        ADD head_backup_path NVARCHAR(500) NULL;
END;

IF COL_LENGTH(N'dbo.tf_job_log', N'detail_backup_path') IS NULL
BEGIN
    ALTER TABLE dbo.tf_job_log
        ADD detail_backup_path NVARCHAR(500) NULL;
END;

IF COL_LENGTH(N'dbo.tf_job_log', N'job_no') IS NULL
BEGIN
    ALTER TABLE dbo.tf_job_log
        ADD job_no BIGINT NULL;
END;

EXEC(N'
IF EXISTS (
    SELECT 1
    FROM (
        SELECT
            CONVERT(CHAR(8), created_at, 112) AS job_date,
            ROW_NUMBER() OVER (
                PARTITION BY CONVERT(CHAR(8), created_at, 112)
                ORDER BY job_id
            ) AS daily_seq
        FROM dbo.tf_job_log
        WHERE job_no IS NULL
    ) AS numbered
    WHERE numbered.daily_seq > 999
)
BEGIN
    THROW 51011, ''Cannot backfill job_no: more than 999 jobs exist on at least one day.'', 1;
END;

;WITH numbered AS (
    SELECT
        job_id,
        CONVERT(CHAR(8), created_at, 112) AS job_date,
        ROW_NUMBER() OVER (
            PARTITION BY CONVERT(CHAR(8), created_at, 112)
            ORDER BY job_id
        ) AS daily_seq
    FROM dbo.tf_job_log
    WHERE job_no IS NULL
)
UPDATE l
SET job_no = CAST(n.job_date AS BIGINT) * 1000 + n.daily_seq
FROM dbo.tf_job_log AS l
JOIN numbered AS n ON n.job_id = l.job_id;

IF EXISTS (
    SELECT job_no
    FROM dbo.tf_job_log
    GROUP BY job_no
    HAVING COUNT(*) > 1
)
BEGIN
    THROW 51012, ''Cannot enforce unique job_no: duplicate values were found.'', 1;
END;

IF EXISTS (
    SELECT 1
    FROM dbo.tf_job_log
    WHERE job_no IS NULL
)
BEGIN
    THROW 51013, ''Cannot make job_no NOT NULL: null values remain.'', 1;
END;
');

EXEC(N'
ALTER TABLE dbo.tf_job_log
    ALTER COLUMN job_no BIGINT NOT NULL;
');

IF NOT EXISTS (
    SELECT 1
    FROM sys.key_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.tf_job_log')
      AND name = N'uq_tf_job_log_job_no'
)
BEGIN
    EXEC(N'
    ALTER TABLE dbo.tf_job_log
        ADD CONSTRAINT uq_tf_job_log_job_no UNIQUE (job_no);
    ');
END;

COMMIT TRANSACTION;

PRINT 'Migration completed. tf_job_log.job_no is now the public YYYYMMDD### job id.';
GO
