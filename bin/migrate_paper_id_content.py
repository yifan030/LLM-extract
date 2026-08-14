# -*- coding: utf-8 -*-
"""一次性迁移：paper_id / content_hash 从「路径派生」切到「原始文件字节派生」。

前置条件
--------
- 迁移期间暂停 8085 mysql-import 消费者（避免新上传在迁移中入库导致新旧 id 并存）。
- 原始文件（PDF/图片）仍在 MinIO（content_hash 需下载原始文件算 md5）。

流程
----
1. 反推旧 paper_id（= md5(试卷 .md key)，.md key 由 file_storage_path 按 _parsed_dir 规则推导），
   与 exam_papers.id 精确匹配定位试卷（不依赖 category 列，老数据 category 多为 NULL）。
2. 下载原始文件算 content_hash（md5）。
3. 内容冲突（同一原始文件被多次上传 → 多个旧 id 落同一新 id）：
   --merge-duplicates 时每组保留题数最多的一卷，删除其余重复卷。
4. --apply 时：补齐 content_hash 列 → 回填 → 关外键检查级联更新
   exam_papers / questions / answer_sheets / student_kp_scores → 删除重复卷 → 补唯一键。

用法（默认 dry-run 只读不落库）
--------------------------------
    set -a && source .env.prod && set +a
    python -m bin.migrate_paper_id_content                 # dry-run
    python -m bin.migrate_paper_id_content --apply --merge-duplicates [--limit N]
"""
import argparse
import asyncio
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from conf.config import Settings
from libs.id_gen import (
    gen_content_hash_bytes,
    gen_paper_id,
    gen_paper_id_from_content_hash,
)
from libs.minio import MinioRepository


def _old_md_key(file_storage_path: str) -> str:
    """按 parse_worker._parsed_dir 规则，从原始文件 key 反推解析 .md 的 key。"""
    p = Path(file_storage_path)
    stem = p.stem
    return f"{p.parent}/{stem}_parsed/{stem}.md"


def _old_paper_id(file_storage_path: str) -> str:
    """旧方案派生：paper_id = md5(试卷 .md 的 object_key)。"""
    return gen_paper_id(_old_md_key(file_storage_path))


async def _ensure_content_hash_columns(engine) -> None:
    """幂等补齐 exam_papers / edu_construct_files 的 content_hash 列。"""
    stmts = [
        "ALTER TABLE exam_papers ADD COLUMN content_hash VARCHAR(32) NULL",
        "ALTER TABLE edu_construct_files ADD COLUMN content_hash VARCHAR(32) NULL",
    ]
    for stmt in stmts:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
            print(f"[列] 已执行: {stmt}")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print(f"[列] 已存在，跳过: {stmt}")
                continue
            raise


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际落库（默认 dry-run）")
    parser.add_argument("--merge-duplicates", action="store_true",
                        help="内容冲突时保留题数最多的一卷，删除其余重复卷")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 条（0=全部）")
    args = parser.parse_args()

    settings = Settings()
    minio = MinioRepository(settings)
    engine = create_async_engine(settings.mysql_url, pool_pre_ping=True)

    # 1. 现有 exam_papers.id（旧 paper_id 集合）
    async with engine.connect() as conn:
        existing_ids = {r[0] for r in (await conn.execute(text("SELECT id FROM exam_papers"))).fetchall()}

    # 2. 读取 construct 记录（apply 时带上 content_hash 以支持续跑跳过）
    if args.apply:
        await _ensure_content_hash_columns(engine)
        fields = "file_id, file_name, file_storage_path, content_hash"
    else:
        fields = "file_id, file_name, file_storage_path"
    async with engine.connect() as conn:
        rows = [
            dict(r)
            for r in (
                await conn.execute(text(
                    f"SELECT {fields} FROM edu_construct_files WHERE file_storage_path IS NOT NULL"
                ))
            ).mappings()
        ]
    if args.limit:
        rows = rows[: args.limit]

    # 3. 反推定位试卷记录（old id 命中 exam_papers）
    paper_records = [r for r in rows if _old_paper_id(r["file_storage_path"]) in existing_ids]

    # 4. 下载原始文件算 content_hash
    backfills: list[tuple[str, str]] = []
    records = []  # (old_id, new_id, content_hash, file_id, file_name)
    download_failures = []
    for r in paper_records:
        content_hash = r.get("content_hash")
        if not content_hash:
            storage = r["file_storage_path"]
            try:
                raw = await minio.get_object_bytes(storage)
            except Exception as e:  # noqa: BLE001
                download_failures.append((storage, str(e)))
                continue
            content_hash = gen_content_hash_bytes(raw)
            backfills.append((r["file_id"], content_hash))
        old_id = _old_paper_id(r["file_storage_path"])
        new_id = gen_paper_id_from_content_hash(content_hash)
        records.append((old_id, new_id, content_hash, r["file_id"], r["file_name"]))

    # 5. 冲突检测
    by_new: dict[str, list] = defaultdict(list)
    for rec in records:
        by_new[rec[1]].append(rec)
    to_migrate = []
    collisions = []
    for new_id, recs in by_new.items():
        if len(recs) > 1:
            collisions.append((new_id, recs))
        else:
            to_migrate.append(recs[0])

    # 6. 孤儿卷检测
    known_old_ids = {rec[0] for rec in records}
    orphans = existing_ids - known_old_ids

    # 7. 合并决策：每组保留题数最多的一卷，其余为待删重复
    losers: list[str] = []
    if collisions and args.merge_duplicates:
        async with engine.connect() as conn:
            qcount = {
                r[0]: r[1]
                for r in (await conn.execute(text(
                    "SELECT exam_paper_id, COUNT(*) FROM questions GROUP BY exam_paper_id"
                ))).fetchall()
            }
        for new_id, recs in collisions:
            recs_sorted = sorted(recs, key=lambda r: (-qcount.get(r[0], 0), r[0]))
            to_migrate.append(recs_sorted[0])  # 保留题数最多者
            losers.extend(r[0] for r in recs_sorted[1:])

    print(
        f"\nconstruct 记录={len(rows)} | 试卷={len(paper_records)} | 可迁移={len(to_migrate)} "
        f"| 内容冲突组={len(collisions)} | 待删重复={len(losers)} | 孤儿卷={len(orphans)} "
        f"| 下载失败={len(download_failures)}"
    )
    for new_id, recs in collisions:
        keep = sorted(recs, key=lambda r: (0, r[0]))[0][0]
        print(f"  [冲突] {new_id} <- {[r[0] for r in recs]}")
    for oid in sorted(orphans):
        print(f"  [孤儿] {oid}（无 construct 记录或原始文件缺失，保留旧 id）")
    for storage, err in download_failures[:20]:
        print(f"  [下载失败] {storage}: {err}")

    if not args.apply:
        print("\n[dry-run] 只读完成，未落库（加 --apply 才实际执行）")
        await engine.dispose()
        return

    if orphans or download_failures:
        print("\n[中止] 存在孤儿卷/下载失败，拒绝落库；请先人工处理后重跑。")
        await engine.dispose()
        return
    if collisions and not args.merge_duplicates:
        print("\n[中止] 存在内容冲突，需加 --merge-duplicates 合并（或人工处理后重跑）。")
        await engine.dispose()
        return

    # 8. 回填 edu_construct_files.content_hash
    if backfills:
        async with engine.begin() as conn:
            for fid, ch in backfills:
                await conn.execute(
                    text("UPDATE edu_construct_files SET content_hash=:c WHERE file_id=:f"),
                    {"c": ch, "f": fid},
                )

    # 9. 级联更新（单连接内关闭外键检查）
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for old_id, new_id, content_hash, _fid, _fname in to_migrate:
            await conn.execute(
                text("UPDATE exam_papers SET id=:n, content_hash=:c WHERE id=:o"),
                {"n": new_id, "c": content_hash, "o": old_id},
            )
            await conn.execute(
                text("UPDATE questions SET exam_paper_id=:n WHERE exam_paper_id=:o"),
                {"n": new_id, "o": old_id},
            )
            await conn.execute(
                text("UPDATE answer_sheets SET exam_paper_id=:n WHERE exam_paper_id=:o"),
                {"n": new_id, "o": old_id},
            )
            await conn.execute(
                text("UPDATE student_kp_scores SET exam_paper_id=:n WHERE exam_paper_id=:o"),
                {"n": new_id, "o": old_id},
            )

        # 10. 删除重复卷（children → exam_papers）
        for loser in losers:
            await conn.execute(
                text("DELETE FROM question_knowledge_point WHERE question_id IN "
                     "(SELECT id FROM questions WHERE exam_paper_id=:o)"),
                {"o": loser},
            )
            await conn.execute(
                text("DELETE FROM questions WHERE exam_paper_id=:o"),
                {"o": loser},
            )
            await conn.execute(
                text("DELETE FROM answer_sheets WHERE exam_paper_id=:o"),
                {"o": loser},
            )
            await conn.execute(
                text("DELETE FROM student_kp_scores WHERE exam_paper_id=:o"),
                {"o": loser},
            )
            await conn.execute(
                text("DELETE FROM exam_papers WHERE id=:o"),
                {"o": loser},
            )
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    # 11. 补 content_hash 唯一键（冲突已合并，此时可安全加）
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE exam_papers ADD UNIQUE KEY uk_content_hash (content_hash)"
            ))
        print("[索引] exam_papers.uk_content_hash 已添加")
    except Exception as e:
        if "Duplicate key name" in str(e) or "1061" in str(e):
            print("[索引] exam_papers.uk_content_hash 已存在，跳过")
        else:
            raise

    print(f"\n迁移完成：已迁移 {len(to_migrate)} 卷，删除重复 {len(losers)} 卷")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
