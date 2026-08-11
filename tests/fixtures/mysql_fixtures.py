# -*- coding: utf-8 -*-
"""MySQL 测试 fixtures — 依赖本地/CI MySQL。

被测对象是 MySqlRepository（libs/mysql.py）。fixture 连接真实 MySQL 并执行
幂等建表；若 MySQL 不可达，则通过 pytest.skip 跳过依赖它的用例。
"""
import pytest
import pytest_asyncio
from sqlalchemy import text

from conf.config import Settings
from libs.mysql import MySqlRepository

# 共享基础设施 MySQL（docker-compose 启动，root/root，容器内 3306 映射到宿主机）
TEST_MYSQL_URL = "mysql+aiomysql://root:root@127.0.0.1:3306/llm_construct"

# 清理顺序需满足外键依赖：
# answer_sheets → formulas_theorems → knowledge_points → questions → exam_papers → students
_CLEANUP_TABLES = [
    "answer_sheets",
    "formulas_theorems",
    "knowledge_points",
    "questions",
    "exam_papers",
    "students",
]


async def _mysql_available(repo: MySqlRepository) -> bool:
    """探测 MySQL 是否可达（执行一次 SELECT 1）。"""
    try:
        async with repo._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def mysql_repo() -> MySqlRepository:
    """创建使用测试数据库的 MySqlRepository，测试后清理全部 6 张表。"""
    settings = Settings(mysql_url=TEST_MYSQL_URL)
    repo = MySqlRepository(settings)
    if not await _mysql_available(repo):
        await repo.close()
        pytest.skip("MySQL 不可达，跳过依赖真实数据库的用例")
    await repo.init_tables()
    yield repo
    # 清理测试数据（按外键依赖逆序删除）
    async with repo._engine.begin() as conn:
        for table in _CLEANUP_TABLES:
            await conn.execute(text(f"DELETE FROM {table}"))
    await repo.close()
