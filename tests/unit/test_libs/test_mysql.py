# -*- coding: utf-8 -*-
"""MySqlRepository 单元测试 — 建表 DDL 与 CRUD。

依赖真实 MySQL（tests/fixtures/mysql_fixtures.py 提供 mysql_repo fixture），
MySQL 不可达时自动 pytest.skip。
"""
import pytest

from conf.config import Settings
from core.exceptions import MySqlError
from libs.mysql import MySqlRepository

# fixture 通过导入注册到本模块（pytest 按模块内名字解析 fixture）
from tests.fixtures.mysql_fixtures import mysql_repo  # noqa: F401


class TestMySqlRepositoryInit:
    def test_empty_mysql_url_raises(self):
        """mysql_url 未配置时构造函数抛出 MySqlError。"""
        with pytest.raises(MySqlError):
            MySqlRepository(Settings(mysql_url=""))


@pytest.mark.asyncio
class TestMySqlRepositoryDDL:
    async def test_init_tables_idempotent(self, mysql_repo: MySqlRepository):
        """建表操作应该是幂等的——重复调用不抛异常。"""
        await mysql_repo.init_tables()  # 第二次调用（fixture 中已建过一次）
        # 不抛异常即通过

    async def test_all_tables_exist(self, mysql_repo: MySqlRepository):
        """6 张表全部存在。"""
        expected = {
            "exam_papers", "questions", "knowledge_points",
            "formulas_theorems", "students", "answer_sheets",
            "question_knowledge_point", "student_kp_scores",
            "videos", "video_knowledge_point",
        }
        rows = await mysql_repo._execute("SHOW TABLES")
        actual = {list(r.values())[0] for r in rows}
        assert expected.issubset(actual)


@pytest.mark.asyncio
class TestMySqlRepositoryCRUD:
    async def test_insert_and_find_one(self, mysql_repo: MySqlRepository):
        """插入一行后能查询到。"""
        await mysql_repo.insert_one("students", {
            "name": "测试学生",
            "grade": "高一",
            "school_name": "测试学校",
            "student_no": "20240001",
        })
        row = await mysql_repo.find_one(
            "students",
            {"school_name": "测试学校", "student_no": "20240001"},
        )
        assert row is not None
        assert row["name"] == "测试学生"
        assert row["grade"] == "高一"

    async def test_upsert_inserts_then_updates(self, mysql_repo: MySqlRepository):
        """UPSERT 首次插入，第二次更新。"""
        data = {
            "id": "paper_test001",
            "title": "测试试卷",
            "subject": "数学",
            "grade": "高一",
        }
        rc1 = await mysql_repo.upsert("exam_papers", data, ["id"])
        assert rc1 == 1  # 插入 1 行

        data["title"] = "更新后的标题"
        rc2 = await mysql_repo.upsert("exam_papers", data, ["id"])
        assert rc2 == 2  # ON DUPLICATE KEY UPDATE 返回 2

        row = await mysql_repo.find_one("exam_papers", {"id": "paper_test001"})
        assert row["title"] == "更新后的标题"

    async def test_find_all_with_limit(self, mysql_repo: MySqlRepository):
        """批量查询和 limit 过滤。"""
        for i in range(3):
            await mysql_repo.insert_one("students", {
                "name": f"学生{i}", "school_name": "批量学校", "student_no": f"N{i}"
            })
        rows = await mysql_repo.find_all(
            "students", {"school_name": "批量学校"}, limit=2
        )
        assert len(rows) == 2

    async def test_find_one_not_found(self, mysql_repo: MySqlRepository):
        """查询不存在的记录返回 None。"""
        row = await mysql_repo.find_one("students", {"id": 99999})
        assert row is None
