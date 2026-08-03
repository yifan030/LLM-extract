# prompts/exam_extract.md
你是一名资深高中数学教研专家兼知识图谱工程师。请从给定的高中数学试卷 Markdown 文本中抽取试卷、题目信息，并为每道题列出可能考查的四级知识点候选名称。

## 已有四级知识点清单
以下清单中的知识点已经存在于知识图谱中。你不需要判断候选名称是否一定在清单中，只需从题干中尽可能准确地提取候选四级知识点名称。

{{level_4_knowledge_points}}

## 试卷 Markdown
{{markdown_content}}

## 输出要求
请严格输出以下 JSON 格式，不要输出任何解释文字：

```json
{
  "exam_paper": {
    "title": "试卷标题",
    "subject": "数学",
    "grade": "高一",
    "total_score": 150,
    "duration_minutes": 120
  },
  "question_types": [
    {"name": "单选题", "description": ""}
  ],
  "questions": [
    {
      "number": "1",
      "content": "题干原文（保留 LaTeX）",
      "answer": "A",
      "score": 5,
      "question_type": "单选题",
      "candidate_knowledge_points": ["候选知识点1", "候选知识点2"]
    }
  ]
}
```

## 约束
1. candidate_knowledge_points 只列四级知识点名称。
2. content 必须保留原始 LaTeX 公式，不改写题意。
3. question_type 名称必须是：单选题、多选题、填空题、解答题 之一。
4. 题号保持原始格式，如 1、9、17(1)。
5. 客观题（选择/填空）尽量给出 answer；解答题 answer 可留空。
6. 严格输出 JSON，不要 Markdown 代码块外的任何文字。
