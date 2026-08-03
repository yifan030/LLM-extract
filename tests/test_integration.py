# -*- coding: utf-8 -*-
import json
import os

from exam_extract.matcher import Matcher
from exam_extract.models import LlmExtractResult


def test_end_to_end_matching():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_dir, "fixtures", "sample_exam.llm.json"), "r", encoding="utf-8") as f:
        llm_result = LlmExtractResult.model_validate(json.load(f))

    matcher = Matcher(level4_names=["交集", "并集", "子集"])
    intermediate = matcher.match(llm_result, source_file="sample_exam.md")

    assert intermediate.metadata.matching_mode == "strict"
    assert len(intermediate.vertices) == 2
    assert any(v.label == "exam_paper" for v in intermediate.vertices)
    assert any(v.label == "question" for v in intermediate.vertices)
    assert any(e.label == "examines" and e.inV == "level_4_交集" for e in intermediate.edges)
    assert len(intermediate.unmatched) == 0
