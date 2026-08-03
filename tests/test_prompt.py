from exam_extract.prompt import build_prompt, load_level4_knowledge_points


def test_build_prompt_replaces_placeholders():
    names = ["子集", "交集"]
    md = "# 测试卷\n1. 已知集合 A={1}..."
    prompt = build_prompt(md, names)
    assert "子集" in prompt
    assert "交集" in prompt
    assert "# 测试卷" in prompt
    assert "candidate_knowledge_points" in prompt
