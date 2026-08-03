import os
import requests
from typing import List


def build_prompt(markdown_content: str, level4_names: List[str]) -> str:
    """替换 Prompt 模板中的占位符。"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompt_path = os.path.join(base_dir, "prompts", "exam_extract.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    names_text = "\n".join(f"- {name}" for name in sorted(level4_names))
    return template.replace("{{level_4_knowledge_points}}", names_text) \
                   .replace("{{markdown_content}}", markdown_content)


def load_level4_knowledge_points(
    host: str,
    port: int,
    user: str,
    passwd: str,
    graphspace: str = "DEFAULT",
    graph: str = "edu"
) -> List[str]:
    """从 HugeGraph 查询所有 level=4 的知识点名称。"""
    url = (
        f"http://{host}:{port}/graphspaces/{graphspace}/graphs/{graph}"
        f"/graph/vertices?label=knowledge_point&limit=10000"
    )
    resp = requests.get(url, auth=(user, passwd))
    resp.raise_for_status()
    data = resp.json()
    names = []
    for v in data.get("vertices", []):
        props = v.get("properties", {})
        if props.get("level") == 4:
            names.append(props.get("name", ""))
    return [n for n in names if n]
