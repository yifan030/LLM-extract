# 模块化目录重构设计

> 将当前 `app/` 分层架构拆分为顶层功能目录，接口与功能保持不变。

## 1. 目标目录结构

```
llm-extract-question/
├── main.py                     # FastAPI 应用工厂 + lifespan
├── cli.py                      # CLI 入口
│
├── bin/                        # 启动/部署脚本
├── conf/                       # 配置
│   └── config.py               # pydantic-settings
├── core/                       # 基础机制
│   ├── exceptions.py           # 全局异常类
│   └── events.py               # Redis Streams 消费者
├── libs/                       # 外部系统封装（数据访问层）
│   ├── hugegraph.py            # HugeGraph REST API
│   └── minio.py                # MinIO SDK 封装
├── model/                      # 纯 Pydantic 数据模型
│   ├── models.py               # 领域模型
│   └── schemas.py              # API 请求/响应 DTO
├── service/                    # 业务逻辑
│   ├── api/                    # HTTP 接口层
│   │   ├── deps.py             # FastAPI 依赖注入
│   │   ├── router.py           # 路由汇总
│   │   └── endpoints/
│   │       ├── extraction.py
│   │       ├── knowledge.py
│   │       ├── minio.py
│   │       ├── papers.py
│   │       └── scoring.py
│   ├── extraction.py           # 抽取流水线编排
│   ├── knowledge.py            # 知识点/试卷查询
│   ├── llm.py                  # LLM 调用
│   ├── matcher.py              # 知识点匹配
│   ├── minio.py                # MinIO 文件浏览
│   ├── prompt.py               # Prompt 构建
│   └── scoring.py              # OCR 解析（判分）
├── utils/                      # 通用工具
│   ├── snowflake.py
│   └── paths.py
├── logs/                       # 日志配置
│   └── logging.py
├── docs/                       # 文档（不变）
├── tests/                      # 测试（调整 import 路径）
├── prompts/                    # LLM Prompt 模板（不变）
├── reference/                  # 参考资料（不变）
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## 2. import 路径映射

### 源码文件

| 旧路径 | 新路径 |
|---|---|
| `app.core.config` | `conf.config` |
| `app.core.exceptions` | `core.exceptions` |
| `app.core.events` | `core.events` |
| `app.core.logging` | `logs.logging` |
| `app.domain.models` | `model.models` |
| `app.domain.schemas` | `model.schemas` |
| `app.repositories.hugegraph` | `libs.hugegraph` |
| `app.repositories.minio` | `libs.minio` |
| `app.services.extraction` | `service.extraction` |
| `app.services.knowledge` | `service.knowledge` |
| `app.services.llm` | `service.llm` |
| `app.services.matcher` | `service.matcher` |
| `app.services.minio` | `service.minio` |
| `app.services.prompt` | `service.prompt` |
| `app.services.scoring` | `service.scoring` |
| `app.api.deps` | `service.api.deps` |
| `app.api.v1.router` | `service.api.router` |
| `app.api.v1.endpoints.*` | `service.api.endpoints.*` |
| `app.utils.snowflake` | `utils.snowflake` |
| `app.utils.paths` | `utils.paths` |

### 测试文件

| 旧路径 | 新路径 |
|---|---|
| `tests/unit/test_core_config.py` | `tests/unit/test_conf_config.py` |
| `tests/unit/test_core_exceptions.py` | `tests/unit/test_core_exceptions.py`（不变） |
| `tests/unit/test_domain/` | `tests/unit/test_model/` |
| `tests/unit/test_repositories/` | `tests/unit/test_libs/` |
| `tests/unit/test_services/` | `tests/unit/test_service/` |
| `tests/unit/test_utils_snowflake.py` | 不变 |

## 3. 需要修改的关键点

### 3.1 PromptService 路径查找

当前 `PromptService.build_prompt_sync()` 通过 `os.path.dirname(__file__)` 向上 3 层查找 `prompts/`：

```python
# 旧：app/services/prompt.py → 向上 3 层到项目根
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

需改为向上 1 层：

```python
# 新：service/prompt.py → 向上 1 层到项目根
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

### 3.2 main.py 和 cli.py

从 `app/main.py`、`app/cli.py` 移动到项目根目录，路径引用：
- `app.api.v1.router` → `service.api.router`
- `app.core.config` → `conf.config`
- `app.core.events` → `core.events`
- `app.core.exceptions` → `core.exceptions`
- `app.core.logging` → `logs.logging`
- `app.repositories.*` → `libs.*`
- `app.services.*` → `service.*`

### 3.3 utils/paths.py

`get_project_root()` 从 `utils/` 向上查找 README.md，路径层级不变（`utils/` 和原来的 `app/utils/` 都是项目根下 1 层）。

## 4. 运行方式

### 4.1 安装

```bash
pip install -e .
```

每个顶层目录（`conf/`, `core/`, `libs/`, `model/`, `service/`, `utils/`, `logs/`）都是独立 Python 包，通过 `__init__.py` 标记。

### 4.2 启动

```bash
# Web API
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# CLI
python cli.py --object-key "education/uploads/.../模拟卷.md"
```

### 4.3 测试

```bash
python -m pytest tests/ -v
```

## 5. 不变项

- 所有 API 端点路径、请求/响应格式不变
- 所有业务逻辑、流水线行为不变
- LLM 调用、知识点匹配、幂等导入策略不变
- 配置文件格式（`.env`）不变
- Docker 部署方式不变
- `prompts/`、`reference/`、`docs/` 目录不变

## 6. 实施步骤

1. 创建所有目标目录和 `__init__.py`
2. 移动文件到新目录
3. 重写所有 import 路径
4. 修正 `PromptService` 的路径查找逻辑
5. 调整测试目录结构和 import
6. 删除空的 `app/` 目录
7. 运行测试验证
8. 更新 README.md 中的项目结构说明
