-- db/create_tables.sql
-- SQL Server DDL for TF File Generator job tracking tables
-- Run once against the FAST_DTW database.

USE FAST_DTW;
GO

-- ---------------------------------------------------------------------------
-- 1. tf_job_log  — one row per request
-- ---------------------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_NAME = 'tf_job_log'
)
BEGIN
    CREATE TABLE tf_job_log (
        job_id              INT IDENTITY(1,1)   NOT NULL,
        job_no              BIGINT              NOT NULL,
        request_id          VARCHAR(100)        NOT NULL,
        integration_profile VARCHAR(100)        NOT NULL,
        requested_by        VARCHAR(100)        NOT NULL,
        requested_at        DATETIME            NOT NULL,
        source_system       VARCHAR(100)        NOT NULL,
        status              VARCHAR(20)         NOT NULL
            CONSTRAINT chk_job_log_status CHECK (
                status IN ('RECEIVED', 'PROCESSING', 'COMPLETED', 'FAILED')
        ),
        error_message       NVARCHAR(MAX)       NULL,
        head_backup_path    NVARCHAR(500)       NULL,
        detail_backup_path  NVARCHAR(500)       NULL,
        created_at          DATETIME            NOT NULL CONSTRAINT df_job_log_created_at  DEFAULT GETDATE(),
        updated_at          DATETIME            NOT NULL CONSTRAINT df_job_log_updated_at  DEFAULT GETDATE(),
        CONSTRAINT pk_tf_job_log PRIMARY KEY (job_id),
        CONSTRAINT uq_tf_job_log_job_no UNIQUE (job_no)
    );
END
GO

-- ---------------------------------------------------------------------------
-- 2. tf_job_step  — step details per job
-- ---------------------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_NAME = 'tf_job_step'
)
BEGIN
    CREATE TABLE tf_job_step (
        step_id     INT IDENTITY(1,1)   NOT NULL,
        job_id      INT                 NOT NULL,
        step_name   VARCHAR(50)         NOT NULL,
        success     BIT                 NOT NULL,
        message     NVARCHAR(500)       NOT NULL,
        detail      NVARCHAR(MAX)       NULL,
        step_at     DATETIME            NOT NULL CONSTRAINT df_job_step_step_at DEFAULT GETDATE(),
        CONSTRAINT pk_tf_job_step  PRIMARY KEY (step_id),
        CONSTRAINT fk_job_step_job FOREIGN KEY (job_id)
            REFERENCES tf_job_log (job_id)
    );
END
GO

-- ---------------------------------------------------------------------------
-- 3. tf_job_document  — one row per document in request
-- ---------------------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_NAME = 'tf_job_document'
)
BEGIN
    CREATE TABLE tf_job_document (
        doc_id          INT IDENTITY(1,1)   NOT NULL,
        job_id          INT                 NOT NULL,
        record_key      VARCHAR(50)         NOT NULL,
        transfer_no     VARCHAR(100)        NOT NULL,
        doc_date        VARCHAR(20)         NOT NULL,
        from_warehouse  VARCHAR(50)         NOT NULL,
        series          VARCHAR(50)         NOT NULL,
        comments        NVARCHAR(500)       NOT NULL,
        created_at      DATETIME            NOT NULL CONSTRAINT df_job_document_created_at DEFAULT GETDATE(),
        CONSTRAINT pk_tf_job_document  PRIMARY KEY (doc_id),
        CONSTRAINT fk_job_document_job FOREIGN KEY (job_id)
            REFERENCES tf_job_log (job_id)
    );
END
GO

-- ---------------------------------------------------------------------------
-- 4. tf_job_item  — one row per detail line / ItemCode
-- ---------------------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_NAME = 'tf_job_item'
)
BEGIN
    CREATE TABLE tf_job_item (
        item_id         INT IDENTITY(1,1)   NOT NULL,
        doc_id          INT                 NOT NULL,
        job_id          INT                 NOT NULL,
        line_num        INT                 NOT NULL,
        item_code       VARCHAR(100)        NOT NULL,
        quantity        VARCHAR(50)         NOT NULL,
        warehouse_code  VARCHAR(50)         NOT NULL,
        status          VARCHAR(20)         NOT NULL CONSTRAINT df_job_item_status DEFAULT 'PROCESSING',
        created_at      DATETIME            NOT NULL CONSTRAINT df_job_item_created_at DEFAULT GETDATE(),
        CONSTRAINT pk_tf_job_item   PRIMARY KEY (item_id),
        CONSTRAINT fk_job_item_doc  FOREIGN KEY (doc_id)
            REFERENCES tf_job_document (doc_id),
        CONSTRAINT fk_job_item_job  FOREIGN KEY (job_id)
            REFERENCES tf_job_log (job_id)
    );
END
GO
