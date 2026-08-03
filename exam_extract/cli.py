import argparse
import json
import os
import sys

from exam_extract import paths
from exam_extract.adapter import HugeGraphAdapter
from exam_extract.llm import LlmConfig, run_llm_extraction
from exam_extract.logger import get_logger
from exam_extract.matcher import Matcher
from exam_extract.models import LlmExtractResult
from exam_extract.prompt import build_prompt, load_level4_knowledge_points

log = get_logger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="试卷抽取并导入 HugeGraph")
    parser.add_argument("--markdown", required=True, help="试卷 markdown 文件路径")
    parser.add_argument(
        "--output",
        default=None,
        help="中间 JSON 输出路径（默认：tmp/<stem>.intermediate.json）",
    )
    parser.add_argument("--host", default="202.107.249.39")
    parser.add_argument("--port", type=int, default=50045)
    parser.add_argument("--user", default="admin")
    parser.add_argument("--passwd", default="admin")
    parser.add_argument("--graphspace", default="DEFAULT")
    parser.add_argument("--graph", default="edu")
    parser.add_argument("--import-to-hg", action="store_true", help="是否直接导入 HugeGraph")
    parser.add_argument(
        "--llm-api-key",
        default=os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        help="LLM API key；提供则自动调用 LLM（默认读取 LLM_API_KEY / OPENAI_API_KEY 环境变量）",
    )
    parser.add_argument(
        "--llm-base-url",
        default=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        help="OpenAI-compatible API 基础地址",
    )
    parser.add_argument(
        "--llm-model",
        default=os.environ.get("LLM_MODEL", "gpt-4o"),
        help="模型名称",
    )
    parser.add_argument("--llm-temperature", type=float, default=0.0, help="采样温度")
    parser.add_argument("--llm-max-tokens", type=int, default=8192, help="最大输出 token")
    parser.add_argument("--llm-timeout", type=float, default=120.0, help="LLM 调用超时秒数")
    return parser.parse_args()


def _load_manual_llm_result(llm_output_path: str) -> LlmExtractResult:
    """从已保存的 .llm.json 加载 LLM 输出并校验。"""
    with open(llm_output_path, "r", encoding="utf-8") as f:
        return LlmExtractResult.model_validate(json.load(f))


def main():
    args = parse_args()

    # 确保项目 tmp 目录存在
    paths.get_tmp_dir()

    if args.output is None:
        args.output = paths.get_default_output_path(args.markdown)

    llm_output_path = paths.get_llm_output_path(args.markdown)

    with open(args.markdown, "r", encoding="utf-8") as f:
        markdown_content = f.read()

    log.info("加载四级知识点列表...")
    level4_names = load_level4_knowledge_points(
        args.host, args.port, args.user, args.passwd, args.graphspace, args.graph
    )
    log.info("加载到 %d 个四级知识点", len(level4_names))

    prompt = build_prompt(markdown_content, level4_names)

    if args.llm_api_key:
        config = LlmConfig(
            api_key=args.llm_api_key,
            model=args.llm_model,
            base_url=args.llm_base_url,
            temperature=args.llm_temperature,
            max_tokens=args.llm_max_tokens,
            timeout=args.llm_timeout,
        )
        log.info("自动调用 LLM (%s @ %s)...", config.model, config.base_url)
        try:
            extracted = run_llm_extraction(prompt, config)
        except Exception as exc:
            log.error("LLM 调用失败: %s", exc)
            sys.exit(1)

        with open(llm_output_path, "w", encoding="utf-8") as f:
            json.dump(extracted.model_dump(mode="json"), f, indent=2, ensure_ascii=False)
        log.info("LLM 输出已保存: %s", llm_output_path)
    else:
        log.info("Prompt 已生成，请将其发送给 LLM，并将 LLM 输出保存为 JSON 文件。")
        if not os.path.exists(llm_output_path):
            log.warning("未找到 LLM 输出文件: %s，请手动提供后再运行 --import-to-hg", llm_output_path)
            print(f"\n请将 LLM 输出保存到: {llm_output_path}\n")
            return
        extracted = _load_manual_llm_result(llm_output_path)

    matcher = Matcher()
    intermediate = matcher.match(extracted, source_file=args.markdown, level4_names=level4_names)

    with open(args.output, "w", encoding="utf-8") as f:
        # model_dump_json 不支持 ensure_ascii，用 json.dumps 保证中文可读
        json.dump(intermediate.model_dump(mode="json"), f, indent=2, ensure_ascii=False)
    log.info("中间 JSON 已保存: %s", args.output)

    if args.import_to_hg:
        hg = HugeGraphAdapter(args.host, args.port, args.user, args.passwd, args.graphspace, args.graph)
        report = hg.import_data(intermediate)
        log.info("HugeGraph 导入报告: %s", report)


if __name__ == "__main__":
    main()
