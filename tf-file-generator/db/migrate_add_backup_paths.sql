-- migrate_add_backup_paths.sql
-- Add backup file path columns to tf_job_log so resend can locate archived files.
-- Run once against FAST_DTW database.

USE FAST_DTW;
GO

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'tf_job_log' AND COLUMN_NAME = 'head_backup_path'
)
BEGIN
    ALTER TABLE tf_job_log
        ADD head_backup_path   NVARCHAR(500) NULL,
            detail_backup_path NVARCHAR(500) NULL;
    PRINT 'Columns head_backup_path and detail_backup_path added to tf_job_log.';
END
ELSE
BEGIN
    PRINT 'Columns already exist — skipped.';
END
GO
