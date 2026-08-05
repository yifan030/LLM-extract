# -*- coding: utf-8 -*-
"""Tests for app.services.knowledge.KnowledgeService."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import KnowledgePointNotFound, PaperNotFound
from model.schemas import KnowledgePointRelationsResponse
from service.knowledge import KnowledgeService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mock_repo(**overrides) -> MagicMock:
    """Build a mock HugeGraphRepository with sensible defaults."""
    repo = MagicMock()
    repo.get_vertex = AsyncMock(return_value=None)
    repo.get_vertex_edges = AsyncMock(return_value=[])
    for k, v in overrides.items():
        setattr(repo, k, v)
    return repo


def _make_vertex(props: dict) -> dict:
    return {"id": "v_test", "properties": props}


def _make_edge(outV: str = "", inV: str = "", label: str = "contains") -> dict:
    return {"outV": outV, "inV": inV, "label": label}


# ---------------------------------------------------------------------------
# list_paper_questions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_paper_questions_raises_paper_not_found():
    repo = _mock_repo()
    svc = KnowledgeService(repo)

    with pytest.raises(PaperNotFound):
        await svc.list_paper_questions("paper_missing")


@pytest.mark.asyncio
async def test_list_paper_questions_returns_full_questions():
    # Paper vertex
    paper_v = _make_vertex({"title": "2024期末数学"})
    # Question vertices
    q1_v = _make_vertex({
        "question_id": 1001,
        "content": "1+1=?",
        "answer": "2",
        "score": 5,
        "question_type_id": 1,
        "exam_paper_id": 12345,
    })
    q2_v = _make_vertex({
        "question_id": 1002,
        "content": "sin(0)=?",
        "answer": "0",
        "score": 10,
        "question_type_id": 2,
        "exam_paper_id": 12345,
    })

    # contains edges: paper → q1, paper → q2
    paper_edges = [
        _make_edge(outV="paper_abc", inV="question_aaa"),
        _make_edge(outV="paper_abc", inV="question_bbb"),
    ]

    # examines edges for each question
    q1_examines = [
        _make_edge(outV="question_aaa", inV="level_4_集合", label="examines"),
    ]
    q2_examines = [
        _make_edge(outV="question_bbb", inV="level_4_三角函数", label="examines"),
        _make_edge(outV="question_bbb", inV="level_4_正弦函数", label="examines"),
    ]

    async def _get_vertex(vertex_id):
        if vertex_id == "paper_abc":
            return paper_v
        if vertex_id == "question_aaa":
            return q1_v
        if vertex_id == "question_bbb":
            return q2_v
        return None

    async def _get_edges(vertex_id, direction, label):
        if vertex_id == "paper_abc" and direction == "out" and label == "contains":
            return paper_edges
        if vertex_id == "question_aaa" and direction == "out" and label == "examines":
            return q1_examines
        if vertex_id == "question_bbb" and direction == "out" and label == "examines":
            return q2_examines
        return []

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(side_effect=_get_edges)
    svc = KnowledgeService(repo)

    result = await svc.list_paper_questions("paper_abc")

    assert len(result) == 2

    q1 = result[0]
    assert q1.question_id == "question_aaa"
    assert q1.content == "1+1=?"
    assert q1.answer == "2"
    assert q1.score == 5
    assert q1.question_type == "单选题"
    assert q1.exam_paper_id == "12345"
    assert q1.exam_paper_title == "2024期末数学"
    assert q1.knowledge_points == ["集合"]

    q2 = result[1]
    assert q2.question_id == "question_bbb"
    assert q2.content == "sin(0)=?"
    assert q2.answer == "0"
    assert q2.score == 10
    assert q2.question_type == "多选题"
    assert q2.knowledge_points == ["三角函数", "正弦函数"]


@pytest.mark.asyncio
async def test_list_paper_questions_skips_missing_question_vertex():
    """试题顶点被删除时不应报错，直接跳过。"""
    paper_v = _make_vertex({"title": "test"})
    edges = [_make_edge(inV="question_gone")]

    async def _get_vertex(vertex_id):
        if vertex_id == "paper_x":
            return paper_v
        return None  # question vertex missing

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(return_value=edges)
    svc = KnowledgeService(repo)

    result = await svc.list_paper_questions("paper_x")
    assert result == []


# ---------------------------------------------------------------------------
# list_kp_questions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_kp_questions_raises_kp_not_found():
    repo = _mock_repo()
    svc = KnowledgeService(repo)

    with pytest.raises(KnowledgePointNotFound):
        await svc.list_kp_questions("level_4_missing")


@pytest.mark.asyncio
async def test_list_kp_questions_returns_questions():
    kp_v = _make_vertex({"name": "集合", "level": 4})
    q1_v = _make_vertex({
        "question_id": 2001,
        "content": "A∪B=?",
        "answer": "{1,2}",
        "score": 5,
        "question_type_id": 1,
        "exam_paper_id": 100,
    })
    paper_v = _make_vertex({"title": "数学卷一"})

    examines_edges = [
        _make_edge(outV="question_111", inV="level_4_集合", label="examines"),
    ]
    q_examines_edges = [
        _make_edge(outV="question_111", inV="level_4_集合", label="examines"),
    ]
    contains_edges = [
        _make_edge(outV="paper_z", inV="question_111", label="contains"),
    ]

    async def _get_vertex(vertex_id):
        if vertex_id == "level_4_集合":
            return kp_v
        if vertex_id == "question_111":
            return q1_v
        if vertex_id == "paper_z":
            return paper_v
        return None

    async def _get_edges(vertex_id, direction, label):
        if vertex_id == "level_4_集合" and direction == "in" and label == "examines":
            return examines_edges
        if vertex_id == "question_111" and direction == "out" and label == "examines":
            return q_examines_edges
        if vertex_id == "question_111" and direction == "in" and label == "contains":
            return contains_edges
        return []

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(side_effect=_get_edges)
    svc = KnowledgeService(repo)

    result = await svc.list_kp_questions("level_4_集合")

    assert len(result) == 1
    q = result[0]
    assert q.question_id == "question_111"
    assert q.content == "A∪B=?"
    assert q.answer == "{1,2}"
    assert q.exam_paper_title == "数学卷一"
    assert q.knowledge_points == ["集合"]


@pytest.mark.asyncio
async def test_list_kp_questions_caches_paper_title():
    """同一试卷的多个试题不应重复查询试卷标题。"""
    kp_v = _make_vertex({"name": "函数", "level": 4})
    q_v = _make_vertex({
        "question_id": 1, "content": "x", "answer": "y",
        "score": 5, "question_type_id": 1, "exam_paper_id": 100,
    })
    paper_v = _make_vertex({"title": "同一张卷"})

    edges = [
        _make_edge(outV="q_a", inV="level_4_函数", label="examines"),
        _make_edge(outV="q_b", inV="level_4_函数", label="examines"),
    ]

    call_count = 0

    async def _get_vertex(vertex_id):
        nonlocal call_count
        if vertex_id == "level_4_函数":
            return kp_v
        if vertex_id in ("q_a", "q_b"):
            return q_v
        if vertex_id == "paper_z":
            call_count += 1
            return paper_v
        return None

    async def _get_edges(vertex_id, direction, label):
        if vertex_id == "level_4_函数" and direction == "in" and label == "examines":
            return edges
        if vertex_id in ("q_a", "q_b") and direction == "out" and label == "examines":
            return [_make_edge(outV=vertex_id, inV="level_4_函数", label="examines")]
        if vertex_id in ("q_a", "q_b") and direction == "in" and label == "contains":
            return [_make_edge(outV="paper_z", inV=vertex_id, label="contains")]
        return []

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(side_effect=_get_edges)
    svc = KnowledgeService(repo)

    await svc.list_kp_questions("level_4_函数")
    assert call_count == 1  # 两个试题共用同一试卷，只查一次


# ---------------------------------------------------------------------------
# get_question (enhanced)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_question_returns_full_detail():
    q_v = _make_vertex({
        "question_id": 3001,
        "content": "2+2=?",
        "answer": "4",
        "score": 3,
        "question_type_id": 3,
        "exam_paper_id": 200,
    })
    paper_v = _make_vertex({"title": "小测验"})
    examines_edges = [
        _make_edge(outV="question_ccc", inV="level_4_算术", label="examines"),
    ]
    contains_edges = [
        _make_edge(outV="paper_y", inV="question_ccc", label="contains"),
    ]

    async def _get_vertex(vertex_id):
        if vertex_id == "question_ccc":
            return q_v
        if vertex_id == "paper_y":
            return paper_v
        return None

    async def _get_edges(vertex_id, direction, label):
        if vertex_id == "question_ccc" and direction == "out" and label == "examines":
            return examines_edges
        if vertex_id == "question_ccc" and direction == "in" and label == "contains":
            return contains_edges
        return []

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(side_effect=_get_edges)
    svc = KnowledgeService(repo)

    result = await svc.get_question("question_ccc")

    assert result.question_id == "question_ccc"
    assert result.content == "2+2=?"
    assert result.answer == "4"
    assert result.score == 3
    assert result.question_type == "填空题"
    assert result.exam_paper_title == "小测验"
    assert result.knowledge_points == ["算术"]


# ---------------------------------------------------------------------------
# _resolve_type_name
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("type_id,expected", [
    (1, "单选题"),
    (2, "多选题"),
    (3, "填空题"),
    (4, "解答题"),
    (None, ""),
    (99, "99"),  # unknown → string representation
])
def test_resolve_type_name(type_id, expected):
    assert KnowledgeService._resolve_type_name(type_id) == expected


# ---------------------------------------------------------------------------
# get_kp_relations
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_kp_relations_by_id():
    """通过 kp_id 查询：返回相关四级知识点和祖先知识点。"""
    kp_v = _make_vertex({"name": "正弦函数性质", "level": 4, "subject": "数学"})

    # 相关知识点（related_kp 双向）
    related_out_v = _make_vertex({"name": "余弦函数性质", "level": 4, "subject": "数学"})
    related_in_v = _make_vertex({"name": "三角函数图像", "level": 4, "subject": "数学"})
    # 一个三级相关知识点（应被过滤掉）
    related_level3_v = _make_vertex({"name": "三角函数", "level": 3, "subject": "数学"})

    # 祖先链：四级→三级→二级→一级
    level3_v = _make_vertex({"name": "三角函数", "level": 3, "subject": "数学"})
    level2_v = _make_vertex({"name": "函数", "level": 2, "subject": "数学"})
    level1_v = _make_vertex({"name": "代数", "level": 1, "subject": "数学"})

    async def _get_vertex(vertex_id):
        mapping = {
            "level_4_正弦函数性质": kp_v,
            "level_4_余弦函数性质": related_out_v,
            "level_4_三角函数图像": related_in_v,
            "level_3_三角函数": level3_v,
            "level_2_函数": level2_v,
            "level_1_代数": level1_v,
        }
        return mapping.get(vertex_id)

    async def _get_edges(vertex_id, direction, label):
        if vertex_id == "level_4_正弦函数性质" and label == "related_kp":
            if direction == "out":
                return [
                    _make_edge(outV="level_4_正弦函数性质", inV="level_4_余弦函数性质", label="related_kp"),
                    _make_edge(outV="level_4_正弦函数性质", inV="level_3_三角函数", label="related_kp"),
                ]
            if direction == "in":
                return [
                    _make_edge(outV="level_4_三角函数图像", inV="level_4_正弦函数性质", label="related_kp"),
                ]
        # contains_kp 入边：向上找父节点
        if label == "contains_kp" and direction == "in":
            chain = {
                "level_4_正弦函数性质": [{"outV": "level_3_三角函数", "inV": "level_4_正弦函数性质", "label": "contains_kp"}],
                "level_3_三角函数": [{"outV": "level_2_函数", "inV": "level_3_三角函数", "label": "contains_kp"}],
                "level_2_函数": [{"outV": "level_1_代数", "inV": "level_2_函数", "label": "contains_kp"}],
                "level_1_代数": [],
            }
            return chain.get(vertex_id, [])
        return []

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(side_effect=_get_edges)
    svc = KnowledgeService(repo)

    result = await svc.get_kp_relations(kp_id="level_4_正弦函数性质")

    assert isinstance(result, KnowledgePointRelationsResponse)
    assert result.kp_id == "level_4_正弦函数性质"
    assert result.name == "正弦函数性质"
    assert result.level == 4

    # 相关知识点：仅四级
    assert len(result.related) == 2
    related_names = {r.name for r in result.related}
    assert related_names == {"余弦函数性质", "三角函数图像"}
    for r in result.related:
        assert r.level == 4

    # 祖先知识点：三级→二级→一级
    assert len(result.ancestors) == 3
    assert result.ancestors[0].name == "三角函数"
    assert result.ancestors[0].level == 3
    assert result.ancestors[1].name == "函数"
    assert result.ancestors[1].level == 2
    assert result.ancestors[2].name == "代数"
    assert result.ancestors[2].level == 1


@pytest.mark.asyncio
async def test_get_kp_relations_by_name():
    """通过 name 查询：自动构造 level_4_{name} ID。"""
    kp_v = _make_vertex({"name": "集合运算", "level": 4, "subject": "数学"})
    level3_v = _make_vertex({"name": "集合", "level": 3, "subject": "数学"})

    async def _get_vertex(vertex_id):
        mapping = {
            "level_4_集合运算": kp_v,
            "level_3_集合": level3_v,
        }
        return mapping.get(vertex_id)

    async def _get_edges(vertex_id, direction, label):
        if label == "related_kp":
            return []
        if label == "contains_kp" and direction == "in" and vertex_id == "level_4_集合运算":
            return [{"outV": "level_3_集合", "inV": "level_4_集合运算", "label": "contains_kp"}]
        if label == "contains_kp" and direction == "in" and vertex_id == "level_3_集合":
            return []
        return []

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(side_effect=_get_edges)
    svc = KnowledgeService(repo)

    result = await svc.get_kp_relations(name="集合运算")

    assert result.kp_id == "level_4_集合运算"
    assert result.name == "集合运算"
    assert len(result.related) == 0
    assert len(result.ancestors) == 1
    assert result.ancestors[0].name == "集合"


@pytest.mark.asyncio
async def test_get_kp_relations_not_found_by_id():
    """kp_id 不存在时抛出 KnowledgePointNotFound。"""
    repo = _mock_repo()
    svc = KnowledgeService(repo)

    with pytest.raises(KnowledgePointNotFound):
        await svc.get_kp_relations(kp_id="level_4_不存在")


@pytest.mark.asyncio
async def test_get_kp_relations_not_found_by_name():
    """name 不存在时抛出 KnowledgePointNotFound。"""
    repo = _mock_repo()
    svc = KnowledgeService(repo)

    with pytest.raises(KnowledgePointNotFound):
        await svc.get_kp_relations(name="不存在的知识点")


@pytest.mark.asyncio
async def test_get_kp_relations_no_args_raises():
    """未提供 kp_id 或 name 时抛出 ValueError。"""
    repo = _mock_repo()
    svc = KnowledgeService(repo)

    with pytest.raises(ValueError, match="必须提供"):
        await svc.get_kp_relations()


@pytest.mark.asyncio
async def test_get_kp_relations_no_ancestors():
    """四级知识点没有祖先时返回空列表（例如独立 level_4 节点）。"""
    kp_v = _make_vertex({"name": "独立知识点", "level": 4})

    async def _get_vertex(vertex_id):
        return kp_v if vertex_id == "level_4_独立知识点" else None

    async def _get_edges(vertex_id, direction, label):
        return []

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(side_effect=_get_edges)
    svc = KnowledgeService(repo)

    result = await svc.get_kp_relations(kp_id="level_4_独立知识点")

    assert result.related == []
    assert result.ancestors == []


@pytest.mark.asyncio
async def test_get_kp_relations_dedup_related():
    """related_kp 双向出现同一个知识点时应去重。"""
    kp_v = _make_vertex({"name": "交集", "level": 4})
    related_v = _make_vertex({"name": "并集", "level": 4})

    async def _get_vertex(vertex_id):
        mapping = {
            "level_4_交集": kp_v,
            "level_4_并集": related_v,
        }
        return mapping.get(vertex_id)

    async def _get_edges(vertex_id, direction, label):
        if label == "related_kp":
            # 双向都指向同一个知识点
            if direction == "out":
                return [{"outV": "level_4_交集", "inV": "level_4_并集", "label": "related_kp"}]
            if direction == "in":
                return [{"outV": "level_4_并集", "inV": "level_4_交集", "label": "related_kp"}]
        return []

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(side_effect=_get_edges)
    svc = KnowledgeService(repo)

    result = await svc.get_kp_relations(kp_id="level_4_交集")

    assert len(result.related) == 1
    assert result.related[0].name == "并集"


@pytest.mark.asyncio
async def test_get_kp_relations_partial_ancestor_chain():
    """祖先链只有部分层级（四级→三级，三级无父节点）。"""
    kp_v = _make_vertex({"name": "子集", "level": 4})
    level3_v = _make_vertex({"name": "集合间关系", "level": 3})

    async def _get_vertex(vertex_id):
        mapping = {
            "level_4_子集": kp_v,
            "level_3_集合间关系": level3_v,
        }
        return mapping.get(vertex_id)

    async def _get_edges(vertex_id, direction, label):
        if label == "contains_kp" and direction == "in":
            if vertex_id == "level_4_子集":
                return [{"outV": "level_3_集合间关系", "inV": "level_4_子集", "label": "contains_kp"}]
        return []

    repo = _mock_repo()
    repo.get_vertex = AsyncMock(side_effect=_get_vertex)
    repo.get_vertex_edges = AsyncMock(side_effect=_get_edges)
    svc = KnowledgeService(repo)

    result = await svc.get_kp_relations(kp_id="level_4_子集")

    assert len(result.ancestors) == 1
    assert result.ancestors[0].name == "集合间关系"
    assert result.ancestors[0].level == 3
