# -*- coding: utf-8 -*-
"""MySQL 异步仓库层 — 连接池、建表、CRUD。"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import inspect, text

from conf.config import Settings
from core.exceptions import MySqlError
from logs.decorators import log_step
from logs.logging import get_logger

log = get_logger(__name__)

_DDL_STATEMENTS = [
    # 1. exam_papers
    """
    CREATE TABLE IF NOT EXISTS exam_papers (
        id          VARCHAR(64)  PRIMARY KEY,
        title       VARCHAR(200) NOT NULL,
        grade       VARCHAR(20),
        subject     VARCHAR(20)  DEFAULT '数学',
        total_score INT,
        duration_minutes INT,
        exam_type   VARCHAR(20),
        paper_year  INT,
        content_hash VARCHAR(32) NULL,
        created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
        updated_at  DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_content_hash (content_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 2. questions
    """
    CREATE TABLE IF NOT EXISTS questions (
        id                  VARCHAR(64)  PRIMARY KEY,
        exam_paper_id       VARCHAR(64)  NOT NULL,
        number              VARCHAR(20)  NOT NULL,
        content             TEXT         NOT NULL,
        answer              TEXT,
        score               INT,
        question_type       VARCHAR(20)  NOT NULL,
        difficulty          TINYINT,
        knowledge_point_ids JSON,
        img_url             JSON,
        answer_img          JSON,
        sort_order          INT,
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (exam_paper_id) REFERENCES exam_papers(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 3. knowledge_points
    """
    CREATE TABLE IF NOT EXISTS knowledge_points (
        id          INT          AUTO_INCREMENT PRIMARY KEY,
        name        VARCHAR(100) NOT NULL,
        level       TINYINT      NOT NULL,
        parent_id   INT          NULL,
        subject     VARCHAR(20)  NULL,
        description VARCHAR(1024) NULL,
        sort_order  INT          DEFAULT 0,
        FOREIGN KEY (parent_id) REFERENCES knowledge_points(id),
        UNIQUE KEY uk_name_level (name, level)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 4. formulas_theorems
    """
    CREATE TABLE IF NOT EXISTS formulas_theorems (
        id                  INT          AUTO_INCREMENT PRIMARY KEY,
        name                VARCHAR(200) NOT NULL,
        content             TEXT         NOT NULL,
        description         TEXT,
        knowledge_point_id  INT          NOT NULL,
        created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 5. students
    """
    CREATE TABLE IF NOT EXISTS students (
        id         INT          AUTO_INCREMENT PRIMARY KEY,
        name       VARCHAR(50)  NOT NULL,
        grade      VARCHAR(20),
        class_name VARCHAR(30),
        school_name VARCHAR(100),
        student_no VARCHAR(255),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_school_no (school_name, student_no)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 6. answer_sheets
    """
    CREATE TABLE IF NOT EXISTS answer_sheets (
        id              INT          AUTO_INCREMENT PRIMARY KEY,
        student_id      INT          NOT NULL,
        exam_paper_id   VARCHAR(64)  NOT NULL,
        question_id     VARCHAR(64)  NOT NULL,
        student_answer  TEXT,
        score_obtained  DECIMAL(5,1),
        is_correct      TINYINT,
        answer_img      JSON,
        marked_at       DATETIME,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id)    REFERENCES students(id),
        FOREIGN KEY (exam_paper_id) REFERENCES exam_papers(id),
        FOREIGN KEY (question_id)   REFERENCES questions(id),
        UNIQUE KEY uk_student_q (student_id, question_id, exam_paper_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 7. question_knowledge_point — 题目-知识点 多对多关联表
    """
    CREATE TABLE IF NOT EXISTS question_knowledge_point (
        id                  INT          AUTO_INCREMENT PRIMARY KEY,
        question_id         VARCHAR(64)  NOT NULL,
        knowledge_point_id  INT          NOT NULL,
        created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (question_id)        REFERENCES questions(id),
        FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id),
        UNIQUE KEY uk_question_kp (question_id, knowledge_point_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 8. student_kp_scores — 学生-知识点得分表（三键聚合）
    """
    CREATE TABLE IF NOT EXISTS student_kp_scores (
        id                  INT          AUTO_INCREMENT PRIMARY KEY,
        student_id          INT          NOT NULL,
        knowledge_point_id  INT          NOT NULL,
        exam_paper_id       VARCHAR(64)  NOT NULL,
        total_score         DECIMAL(8,2) NOT NULL DEFAULT 0,
        full_score          DECIMAL(8,2) NOT NULL DEFAULT 0,
        score_rate          DECIMAL(5,4),
        question_count      INT          NOT NULL DEFAULT 0,
        updated_at          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id)          REFERENCES students(id),
        FOREIGN KEY (knowledge_point_id)  REFERENCES knowledge_points(id),
        FOREIGN KEY (exam_paper_id)       REFERENCES exam_papers(id),
        UNIQUE KEY uk_student_kp_paper (student_id, knowledge_point_id, exam_paper_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 9. videos — 视频主表
    """
    CREATE TABLE IF NOT EXISTS videos (
        id               INT          AUTO_INCREMENT PRIMARY KEY,
        title            VARCHAR(200) NOT NULL,
        url              VARCHAR(500),
        duration_seconds INT,
        subject          VARCHAR(20)  DEFAULT '数学',
        grade            VARCHAR(20),
        description      TEXT,
        created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
        updated_at       DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 10. video_knowledge_point — 视频-知识点 多对多关联表
    """
    CREATE TABLE IF NOT EXISTS video_knowledge_point (
        id                  INT          AUTO_INCREMENT PRIMARY KEY,
        video_id            INT          NOT NULL,
        knowledge_point_id  INT          NOT NULL,
        created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (video_id)           REFERENCES videos(id),
        FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id),
        UNIQUE KEY uk_video_kp (video_id, knowledge_point_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


@log_step
class MySqlRepository:
    """Async data-access layer over MySQL (via SQLAlchemy 2.0 async)."""

    def __init__(self, settings: Settings):
        if not settings.mysql_url:
            raise MySqlError("mysql_url 未配置")
        self._engine: AsyncEngine = create_async_engine(
            settings.mysql_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=settings.debug,
        )
        self._url = settings.mysql_url

    async def init_tables(self) -> None:
        """幂等建表 — 应用启动时调用，确保表存在并补齐迁移列。"""
        async with self._engine.begin() as conn:
            for ddl in _DDL_STATEMENTS:
                await conn.execute(text(ddl))
        await self._migrate()
        log.info("MySQL 表结构初始化完成（10 张表）")

    async def _migrate(self) -> None:
        """幂等补齐存量表的列与唯一索引。

        ``CREATE TABLE IF NOT EXISTS`` 只建新表、不改已有表；MySQL 8.0 的
        ``ALTER TABLE`` 又不支持 ``IF NOT EXISTS``，故先用 inspector 探测
        列/索引是否已存在，缺失才执行 ALTER。
        """
        async with self._engine.connect() as conn:
            exam_columns, exam_indexes = await conn.run_sync(self._inspect_exam_papers)
            kp_columns, kp_indexes = await conn.run_sync(self._inspect_knowledge_points)
        async with self._engine.begin() as conn:
            if exam_columns:
                if "content_hash" not in exam_columns:
                    await conn.execute(text(
                        "ALTER TABLE exam_papers ADD COLUMN content_hash VARCHAR(32) NULL"
                    ))
                if "uk_content_hash" not in exam_indexes:
                    await conn.execute(text(
                        "ALTER TABLE exam_papers ADD UNIQUE KEY uk_content_hash (content_hash)"
                    ))
            if kp_columns:
                if "subject" not in kp_columns:
                    await conn.execute(text(
                        "ALTER TABLE knowledge_points ADD COLUMN subject VARCHAR(20) NULL"
                    ))
                if "description" not in kp_columns:
                    await conn.execute(text(
                        "ALTER TABLE knowledge_points ADD COLUMN description VARCHAR(1024) NULL"
                    ))
                if "uk_name_level" not in kp_indexes:
                    await conn.execute(text(
                        "ALTER TABLE knowledge_points ADD UNIQUE KEY uk_name_level (name, level)"
                    ))

    @staticmethod
    def _inspect_exam_papers(sync_conn) -> tuple[set[str], set[str]]:
        """返回 exam_papers 的列名集合与索引名集合（表不存在时返回空集）。"""
        return MySqlRepository._inspect_table(sync_conn, "exam_papers")

    @staticmethod
    def _inspect_knowledge_points(sync_conn) -> tuple[set[str], set[str]]:
        """返回 knowledge_points 的列名集合与索引名集合（表不存在时返回空集）。"""
        return MySqlRepository._inspect_table(sync_conn, "knowledge_points")

    @staticmethod
    def _inspect_table(sync_conn, table: str) -> tuple[set[str], set[str]]:
        """返回指定表的列名集合与索引名集合（表不存在时返回空集）。"""
        inspector = inspect(sync_conn)
        if table not in inspector.get_table_names():
            return set(), set()
        columns = {c["name"] for c in inspector.get_columns(table)}
        indexes = {i["name"] for i in inspector.get_indexes(table)}
        return columns, indexes

    async def close(self) -> None:
        """关闭连接池，应用关闭时调用。"""
        await self._engine.dispose()
        log.info("MySQL 连接池已关闭")

    async def _execute(self, sql: str, params: dict | None = None) -> list[dict]:
        """底层执行：执行 SQL 并返回 dict 列表。"""
        async with self._engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            rows = result.fetchall()
            if not rows:
                return []
            columns = list(result.keys())
            return [dict(zip(columns, row)) for row in rows]

    async def insert_one(self, table: str, data: dict) -> int:
        """插入单行，返回 lastrowid（适用于自增主键表）。"""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data)
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        async with self._engine.begin() as conn:
            result = await conn.execute(text(sql), data)
            return result.lastrowid

    async def upsert(
        self, table: str, data: dict, unique_columns: list[str]
    ) -> int:
        """INSERT ... ON DUPLICATE KEY UPDATE，返回受影响行数。

        当 data 仅含唯一键（无可更新字段）时退化为 ``INSERT IGNORE``，
        避免生成空的 ``ON DUPLICATE KEY UPDATE`` 子句导致 SQL 语法错误。
        """
        columns = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data)
        updates = ", ".join(f"{k}=VALUES({k})" for k in data if k not in unique_columns)
        if updates:
            sql = (
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}"
            )
        else:
            sql = f"INSERT IGNORE INTO {table} ({columns}) VALUES ({placeholders})"
        async with self._engine.begin() as conn:
            result = await conn.execute(text(sql), data)
            return result.rowcount

    async def find_one(self, table: str, where: dict) -> dict | None:
        """按条件查询单行。"""
        clauses = " AND ".join(f"{k}=:{k}" for k in where)
        sql = f"SELECT * FROM {table} WHERE {clauses} LIMIT 1"
        rows = await self._execute(sql, where)
        return rows[0] if rows else None

    async def find_all(
        self, table: str, where: dict | None = None, limit: int = 100
    ) -> list[dict]:
        """按条件查询多行。"""
        if where:
            clauses = " AND ".join(f"{k}=:{k}" for k in where)
            sql = f"SELECT * FROM {table} WHERE {clauses} LIMIT {limit}"
            return await self._execute(sql, where)
        sql = f"SELECT * FROM {table} LIMIT {limit}"
        return await self._execute(sql)
