// ==================== 公共属性键定义 ====================
// 通用属性（仅知识点与题目使用 source_file_id，其余实体已去除）
graph.schema().propertyKey('biz_id').asLong().ifNotExist().create();
graph.schema().propertyKey('source_file_id').asLong().ifNotExist().create();
graph.schema().propertyKey('sub_file_id').asLong().ifNotExist().create();
graph.schema().propertyKey('name').asText().ifNotExist().create();
graph.schema().propertyKey('title').asText().ifNotExist().create();
graph.schema().propertyKey('description').asText().ifNotExist().create();
graph.schema().propertyKey('content').asText().ifNotExist().create();
graph.schema().propertyKey('subject').asText().ifNotExist().create();
graph.schema().propertyKey('level').asInt().ifNotExist().create();
graph.schema().propertyKey('created_at').asText().ifNotExist().create();
graph.schema().propertyKey('updated_at').asText().ifNotExist().create();

// 知识点 knowledge_point 属性
graph.schema().propertyKey('knowledge_point_id').asLong().ifNotExist().create();

// 题型 question_type 属性
graph.schema().propertyKey('question_type_id').asLong().ifNotExist().create();

// 解法 solution 属性
graph.schema().propertyKey('solution_id').asLong().ifNotExist().create();

// 公式定理 formula_theorem 属性
graph.schema().propertyKey('formula_theorem_id').asLong().ifNotExist().create();
graph.schema().propertyKey('expression').asText().ifNotExist().create();
graph.schema().propertyKey('formula_type').asInt().ifNotExist().create();

// 易错点 error_prone 属性
graph.schema().propertyKey('error_prone_id').asLong().ifNotExist().create();
graph.schema().propertyKey('cause_analysis').asText().ifNotExist().create();

// 试卷 exam_paper 属性
graph.schema().propertyKey('exam_paper_id').asLong().ifNotExist().create();
graph.schema().propertyKey('grade').asText().ifNotExist().create();
graph.schema().propertyKey('total_score').asInt().ifNotExist().create();
graph.schema().propertyKey('duration_minutes').asInt().ifNotExist().create();

// 题目 question 属性
graph.schema().propertyKey('question_id').asLong().ifNotExist().create();
graph.schema().propertyKey('answer').asText().ifNotExist().create();
graph.schema().propertyKey('score').asInt().ifNotExist().create();

// 关系通用属性
graph.schema().propertyKey('sequence').asInt().ifNotExist().create();
graph.schema().propertyKey('relation_desc').asText().ifNotExist().create();
graph.schema().propertyKey('create_time').asText().ifNotExist().create();

// ==================== 顶点标签定义（已配置可空字段） ====================
// 知识点 knowledge_point：非空 knowledge_point_id,name；其余可空
// 使用自定义 id（业务主键 knowledge_point_id），HugeGraph v4 对应 CUSTOMIZE_STRING 策略
// 注意：创建时需显式传 id（字符串，如 "kp_1"），无 primary_keys
graph.schema().vertexLabel('knowledge_point')
.properties('knowledge_point_id','name','description','subject','level','source_file_id','created_at','updated_at')
.nullableKeys('description','subject','source_file_id','created_at','updated_at')
.useCustomizeId().enableLabelIndex(true).ifNotExist().create();

// 题型 question_type：非空 question_type_id,name；不含 source_file_id
graph.schema().vertexLabel('question_type')
.properties('question_type_id','name','description','created_at','updated_at')
.nullableKeys('description','created_at','updated_at')
.useAutomaticId().enableLabelIndex(true).ifNotExist().create();

// 解法 solution：非空 solution_id,title,content；不含 source_file_id 与 difficulty_level
graph.schema().vertexLabel('solution')
.properties('solution_id','title','content','created_at','updated_at')
.nullableKeys('created_at','updated_at')
.useAutomaticId().enableLabelIndex(true).ifNotExist().create();

// 公式定理 formula_theorem：非空 formula_theorem_id,name,expression,formula_type；不含 source_file_id
graph.schema().vertexLabel('formula_theorem')
.properties('formula_theorem_id','name','expression','description','formula_type','created_at','updated_at')
.nullableKeys('description','created_at','updated_at')
.useAutomaticId().enableLabelIndex(true).ifNotExist().create();

// 易错点 error_prone：非空 error_prone_id,title,description；不含 source_file_id
graph.schema().vertexLabel('error_prone')
.properties('error_prone_id','title','description','cause_analysis','created_at','updated_at')
.nullableKeys('cause_analysis','created_at','updated_at')
.useAutomaticId().enableLabelIndex(true).ifNotExist().create();

// 试卷 exam_paper：非空 exam_paper_id,title；不含 source_file_id；
// 使用自定义 id（业务主键 exam_paper_id），HugeGraph v4 对应 CUSTOMIZE_STRING 策略
// 注意：创建时需显式传 id（字符串），无 primary_keys
graph.schema().vertexLabel('exam_paper')
.properties('exam_paper_id','title','subject','grade','total_score','duration_minutes','created_at','updated_at')
.nullableKeys('subject','grade','total_score','duration_minutes','created_at','updated_at')
.useCustomizeId().enableLabelIndex(true).ifNotExist().create();

// 题目 question（核心实体）：非空 question_id,content；不含 difficulty_level；
// 使用自定义 id（业务主键 question_id），HugeGraph v4 对应 CUSTOMIZE_STRING 策略
// 注意：创建时需显式传 id（字符串），无 primary_keys
graph.schema().vertexLabel('question')
.properties(
    'question_id','content','answer','score','question_type_id','exam_paper_id',
    'source_file_id','sub_file_id','created_at','updated_at'
)
.nullableKeys(
    'answer','score','question_type_id','exam_paper_id',
    'source_file_id','sub_file_id','created_at','updated_at'
)
.useCustomizeId().enableLabelIndex(true).ifNotExist().create();

// ==================== 关系标签定义 ====================
// 题目 --考查--> 知识点
graph.schema().edgeLabel('examines')
.sourceLabel('question').targetLabel('knowledge_point')
.properties('create_time')
.nullableKeys('create_time')
.enableLabelIndex(true).ifNotExist().create();

// 题目 --可由--> 解法求解（带解法顺序 sequence）
graph.schema().edgeLabel('solved_by')
.sourceLabel('question').targetLabel('solution')
.properties('sequence','create_time')
.multiTimes().sortKeys('sequence')
.nullableKeys('create_time')
.enableLabelIndex(true).ifNotExist().create();

// 题目 --关联--> 变式题（题目 -> 题目，带变式关系描述）
graph.schema().edgeLabel('variant_of')
.sourceLabel('question').targetLabel('question')
.properties('relation_desc','create_time')
.nullableKeys('relation_desc','create_time')
.enableLabelIndex(true).ifNotExist().create();

// 知识点 --包含--> 知识点（上下级层级关系）
graph.schema().edgeLabel('contains_kp')
.sourceLabel('knowledge_point').targetLabel('knowledge_point')
.properties('create_time')
.nullableKeys('create_time')
.enableLabelIndex(true).ifNotExist().create();

// 知识点 --相关--> 知识点（关联关系）
graph.schema().edgeLabel('related_kp')
.sourceLabel('knowledge_point').targetLabel('knowledge_point')
.properties('create_time')
.nullableKeys('create_time')
.enableLabelIndex(true).ifNotExist().create();

// 题目 --易犯--> 易错点
graph.schema().edgeLabel('prone_to_error')
.sourceLabel('question').targetLabel('error_prone')
.properties('create_time')
.nullableKeys('create_time')
.enableLabelIndex(true).ifNotExist().create();

// 题目 --使用--> 公式定理
graph.schema().edgeLabel('uses_formula')
.sourceLabel('question').targetLabel('formula_theorem')
.properties('create_time')
.nullableKeys('create_time')
.enableLabelIndex(true).ifNotExist().create();

// 题目 --属于--> 题型
graph.schema().edgeLabel('belongs_to_type')
.sourceLabel('question').targetLabel('question_type')
.properties('create_time')
.nullableKeys('create_time')
.enableLabelIndex(true).ifNotExist().create();

// 试卷 --包含--> 题目
graph.schema().edgeLabel('contains')
.sourceLabel('exam_paper').targetLabel('question')
.properties('create_time')
.nullableKeys('create_time')
.enableLabelIndex(true).ifNotExist().create();

// ==================== 索引定义 ====================
// 名称/标题二级索引，便于检索
graph.schema().indexLabel('knowledge_point_name').onV('knowledge_point').by('name').secondary().ifNotExist().create();
graph.schema().indexLabel('question_type_name').onV('question_type').by('name').secondary().ifNotExist().create();
graph.schema().indexLabel('formula_theorem_name').onV('formula_theorem').by('name').secondary().ifNotExist().create();
graph.schema().indexLabel('solution_title').onV('solution').by('title').secondary().ifNotExist().create();
graph.schema().indexLabel('error_prone_title').onV('error_prone').by('title').secondary().ifNotExist().create();
graph.schema().indexLabel('exam_paper_title').onV('exam_paper').by('title').secondary().ifNotExist().create();

// 学科过滤索引
graph.schema().indexLabel('knowledge_point_subject').onV('knowledge_point').by('subject').secondary().ifNotExist().create();

// 来源文件追溯索引
graph.schema().indexLabel('question_source_file').onV('question').by('source_file_id').secondary().ifNotExist().create();
