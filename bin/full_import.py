# -*- coding: utf-8 -*-
"""全量抽取到 MySQL：列出桶内全部 .md，跳过纯答案卷与已入库，顺序导入。

用法:
    python -m bin.full_import [--limit N] [--retry 1] [--out /app/tmp/full_import_results.json]

说明:
    - 复用 MySqlImportService.import_paper（单篇导入逻辑，不连 HugeGraph/Milvus）。
    - 纯答案卷判定：文件名含「答案」且不含「含答案/及答案/试卷+答案」等标记 → 跳过。
    - 已入库判定：import_paper 内部按 content_hash 去重，命中即返回 imported=False。
    - 单文件失败按 --retry 重试，仍失败则记录并继续，不中断整批。
    - 进度每 20 份 flush 一次结果到 --out（JSON），中断后可重跑（跳过已入库续跑）。
"""
import argparse
import asyncio
import json

from conf.config import Settings
from libs.minio import MinioRepository
from libs.mysql import MySqlRepository
from service.llm import LlmService
from service.prompt import PromptService
from service.mysql_import import MySqlImportService

# 与 service/mysql_import.py 保持一致的纯答案卷标记
_ANSWER_KEEP_MARKERS = (
    "含答案", "及答案", "答案带题", "试卷+答案", "试题和答案", "学生版+答案", "无答案",
)


def _is_answer_only(object_key: str) -> bool:
    name = object_key.rsplit("/", 1)[-1]
    if any(m in name for m in _ANSWER_KEEP_MARKERS):
        return False
    return "答案" in name


def _flush(results: list[dict], out: str) -> None:
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="最多导入文件数（0=全部）")
    parser.add_argument("--retry", type=int, default=1, help="单文件失败重试次数")
    parser.add_argument("--out", default="/app/tmp/full_import_results.json")
    args = parser.parse_args()

    settings = Settings()
    minio_repo = MinioRepository(settings)
    mysql_repo = MySqlRepository(settings)
    llm_svc = LlmService(settings)
    prompt_svc = PromptService()
    svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

    md_files = await minio_repo.list_md_files(prefix="", limit=100000)

    # 已入库去重交由 import_paper 内部按 content_hash 判定（命中时零成本返回 imported=False）
    answer_only = [f.object_key for f in md_files if _is_answer_only(f.object_key)]
    to_import = [f.object_key for f in md_files if not _is_answer_only(f.object_key)]
    if args.limit:
        to_import = to_import[:args.limit]

    print(
        f"待导入={len(to_import)} | 跳过纯答案卷={len(answer_only)} | 总 .md={len(md_files)}",
        flush=True,
    )

    results: list[dict] = []
    for i, key in enumerate(to_import, 1):
        ok = False
        resp = None
        last_err: Exception | None = None
        for attempt in range(args.retry + 1):
            try:
                resp = await svc.import_paper(key)
                ok = True
                break
            except Exception as exc:  # noqa: BLE001 — 单文件失败不中断整批
                last_err = exc
                if attempt < args.retry:
                    print(
                        f"[{i}/{len(to_import)}] 重试({attempt + 1}) {key.split('/')[-1][:40]} err={exc}",
                        flush=True,
                    )
        results.append({
            "object_key": key,
            "paper_id": resp.paper_id if resp else "",
            "title": resp.title if resp else "",
            "question_count": resp.question_count if resp else 0,
            "status": "OK" if ok else "FAIL",
            "error": None if ok else str(last_err),
        })
        status = "OK" if ok else "FAIL"
        qc = resp.question_count if resp else 0
        print(f"[{i}/{len(to_import)}] {status} q={qc:>3} {key.split('/')[-1][:52]}", flush=True)
        if i % 20 == 0:
            _flush(results, args.out)

    _flush(results, args.out)
    ok_n = sum(1 for r in results if r["status"] == "OK")
    fail_n = len(results) - ok_n
    print(f"\n===== 完成：成功={ok_n} 失败={fail_n} =====")
    for r in results:
        if r["status"] == "FAIL":
            print("  FAIL", r["object_key"].split("/")[-1], r["error"])

    await mysql_repo.close()


if __name__ == "__main__":
    asyncio.run(main())
