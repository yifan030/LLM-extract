# 模块化目录重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 `app/` 分层架构重构为顶层功能目录（`conf/`, `core/`, `libs/`, `model/`, `service/`, `utils/`, `logs/`），`main.py` 和 `cli.py` 提升至项目根目录，所有 API 接口和业务功能保持不变。

**Architecture:** 拆除 `app/` 父包，每个功能目录成为独立顶层 Python 包。import 路径从 `app.xxx.yyy` 改为直接 `xxx.yyy`。依赖关系：`model/` 零依赖 → `conf/`, `logs/`, `utils/` 基本零依赖 → `core/` 依赖 `logs/` → `libs/` 依赖 `conf/`, `logs/`, `model/` → `service/` 依赖 `libs/`, `model/`, `core/` → `service/api/` 依赖 `service/` → `main.py`/`cli.py` 依赖所有。

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, httpx, miniopy_async, redis-py, openai

## 全局约束

- 所有 API 端点路径、请求/响应格式不变
- 所有业务逻辑、流水线行为不变
- 测试逻辑不变，仅调整 import 路径和目录结构
- `.env` 配置格式不变
- Docker 部署方式不变

---

### Task 1: 创建目标目录结构和 `__init__.py`

**Files:**
- Create: `conf/__init__.py`
- Create: `core/__init__.py`
- Create: `libs/__init__.py`
- Create: `model/__init__.py`
- Create: `service/__init__.py`
- Create: `service/api/__init__.py`
- Create: `service/api/endpoints/__init__.py`
- Create: `utils/__init__.py`
- Create: `logs/__init__.py`
- Create: `bin/__init__.py`

**Produces:** 所有目标目录就绪，可接收文件移入

- [ ] **Step 1: 创建所有目录和空的 `__init__.py`**

```bash
mkdir -p conf core libs model service/api/endpoints utils logs bin
touch conf/__init__.py core/__init__.py libs/__init__.py \
      model/__init__.py service/__init__.py service/api/__init__.py \
      service/api/endpoints/__init__.py utils/__init__.py logs/__init__.py
```

- [ ] **Step 2: 验证目录结构**

```bash
ls -la conf/ core/ libs/ model/ service/api/endpoints/ utils/ logs/ bin/
```

Expected: 每个目录均存在且包含 `__init__.py`

- [ ] **Step 3: 提交**

```bash
git add conf/ core/ libs/ model/ service/ utils/ logs/ bin/
git commit -m "chore: create target directory structure for modular restructure"
```

---

### Task 2: 移动 logs/ 模块

**Files:**
- Move: `app/core/logging.py` → `logs/logging.py`
- Modify: `app/core/events.py`（import `app.core.logging` → `logs.logging`）

**Interfaces:**
- Produces: `logs.logging.get_logger(name: str) -> logging.Logger`

- [ ] **Step 1: 复制文件到新位置并重写自身 import**

`logs/logging.py` 内容与原 `app/core/logging.py` 完全相同（无内部 import 依赖，无需修改）：

```bash
cp app/core/logging.py logs/logging.py
```

- [ ] **Step 2: 更新 `app/core/events.py` 的 import**

将第 7 行：
```python
from app.core.logging import get_logger
```
替换为：
```python
from logs.logging import get_logger
```

```bash
# 用 sed 完成替换
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' app/core/events.py
```

- [ ] **Step 3: 验证 Python 语法**

```bash
python -c "from logs.logging import get_logger; log = get_logger('test'); log.info('ok')"
```

Expected: 日志正常输出

- [ ] **Step 4: 提交**

```bash
git add logs/logging.py app/core/events.py
git commit -m "refactor: move logging to logs/ package"
```

---

### Task 3: 移动 conf/ 模块

**Files:**
- Move: `app/core/config.py` → `conf/config.py`

**Interfaces:**
- Produces: `conf.config.Settings` 类，包含所有 pydantic-settings 配置项和 `hg_base_url` 属性

- [ ] **Step 1: 复制文件**

```bash
cp app/core/config.py conf/config.py
```

`conf/config.py` 无内部 import 依赖，无需修改内容。

- [ ] **Step 2: 验证**

```bash
python -c "from conf.config import Settings; print(Settings().model_config)"
```

Expected: 输出 `{'env_file': '.env', ...}`

- [ ] **Step 3: 提交**

```bash
git add conf/config.py
git commit -m "refactor: move config to conf/ package"
```

---

### Task 4: 移动 model/ 模块

**Files:**
- Move: `app/domain/models.py` → `model/models.py`
- Move: `app/domain/schemas.py` → `model/schemas.py`

**Interfaces:**
- Produces: `model.models.ExamPaper`, `QuestionType`, `Question`, `LlmExtractResult`, `Vertex`, `Edge`, `UnmatchedItem`, `Metadata`, `IntermediateJson`
- Produces: `model.schemas.ExtractRequest`, `ExtractResult`, `MinioFileItem`, `PaperSummary`, `PaperDetail`, `QuestionSummary`, `QuestionDetail`, `KnowledgePointItem`, `KnowledgePointDetail`, `KnowledgePointRelationsResponse`, `PaginatedResponse`, `ScoringRequest`, `QuestionScore`, `SectionScore`, `ScoringResponse`

- [ ] **Step 1: 复制文件**

```bash
cp app/domain/models.py model/models.py
cp app/domain/schemas.py model/schemas.py
```

两个文件均零项目内部依赖，无需修改内容。

- [ ] **Step 2: 验证**

```bash
python -c "from model.models import ExamPaper, Vertex, Edge, IntermediateJson; from model.schemas import ExtractRequest, ScoringResponse; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: 提交**

```bash
git add model/models.py model/schemas.py
git commit -m "refactor: move domain models to model/ package"
```

---

### Task 5: 移动 core/ 模块

**Files:**
- Move: `app/core/exceptions.py` → `core/exceptions.py`
- Move: `app/core/events.py` → `core/events.py`

**Interfaces:**
- Produces: `core.exceptions.AppError`, `MinioObjectNotFound`, `LlmApiCallError`, `HugeGraphError`, `KnowledgePointNotFound`, `PaperNotFound`, `ExtractionValidationError`
- Produces: `core.events.publish_event(redis_url, object_key)`, `start_consumer(redis_url, extraction_svc)`, `STREAM_KEY`, `CONSUMER_GROUP`

- [ ] **Step 1: 复制文件**

```bash
cp app/core/exceptions.py core/exceptions.py
cp app/core/events.py core/events.py
```

- [ ] **Step 2: 确认 `core/exceptions.py` 无需修改**

该文件零内部 import 依赖，内容无需更改。

- [ ] **Step 3: 确认 `core/events.py` 的 import 已在 Task 2 中更新**

Task 2 已将 `app/core/events.py` 中的 `from app.core.logging import get_logger` 改为 `from logs.logging import get_logger`。复制后的 `core/events.py` 已经正确。

- [ ] **Step 4: 验证**

```bash
python -c "from core.exceptions import AppError, MinioObjectNotFound; from core.events import STREAM_KEY; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: 提交**

```bash
git add core/exceptions.py core/events.py
git commit -m "refactor: move exceptions and events to core/ package"
```

---

### Task 6: 移动 utils/ 模块

**Files:**
- Move: `app/utils/snowflake.py` → `utils/snowflake.py`
- Move: `app/utils/paths.py` → `utils/paths.py`

**Interfaces:**
- Produces: `utils.snowflake.Snowflake` 类（`next_id() -> int`）
- Produces: `utils.paths.get_project_root()`, `get_tmp_dir()`, `get_llm_output_path()`, `get_default_output_path()`

- [ ] **Step 1: 复制文件**

```bash
cp app/utils/snowflake.py utils/snowflake.py
cp app/utils/paths.py utils/paths.py
```

两个文件均零内部 import 依赖，无需修改内容。

- [ ] **Step 2: 验证**

```bash
python -c "from utils.snowflake import Snowflake; from utils.paths import get_project_root; print(get_project_root())"
```

Expected: 输出项目根目录路径

- [ ] **Step 3: 提交**

```bash
git add utils/snowflake.py utils/paths.py
git commit -m "refactor: move utils to utils/ package"
```

---

### Task 7: 移动 libs/ 模块并重写 import

**Files:**
- Move: `app/repositories/hugegraph.py` → `libs/hugegraph.py`
- Move: `app/repositories/minio.py` → `libs/minio.py`

**Interfaces:**
- Produces: `libs.hugegraph.HugeGraphRepository` — async HugeGraph REST API 封装
- Produces: `libs.minio.MinioRepository` — async MinIO SDK 封装

- [ ] **Step 1: 复制文件**

```bash
cp app/repositories/hugegraph.py libs/hugegraph.py
cp app/repositories/minio.py libs/minio.py
```

- [ ] **Step 2: 重写 `libs/hugegraph.py` 的 import**

```bash
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' libs/hugegraph.py
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' libs/hugegraph.py
sed -i '' 's/from app\.domain\.models import Edge, Vertex/from model.models import Edge, Vertex/' libs/hugegraph.py
```

- [ ] **Step 3: 重写 `libs/minio.py` 的 import**

```bash
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' libs/minio.py
sed -i '' 's/from app\.core\.exceptions import MinioObjectNotFound/from core.exceptions import MinioObjectNotFound/' libs/minio.py
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' libs/minio.py
sed -i '' 's/from app\.domain\.schemas import MinioFileItem/from model.schemas import MinioFileItem/' libs/minio.py
```

- [ ] **Step 4: 验证语法**

```bash
python -c "from libs.hugegraph import HugeGraphRepository; from libs.minio import MinioRepository; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: 提交**

```bash
git add libs/hugegraph.py libs/minio.py
git commit -m "refactor: move repositories to libs/ package"
```

---

### Task 8: 移动 service/ 业务层并重写 import

**Files:**
- Move: `app/services/extraction.py` → `service/extraction.py`
- Move: `app/services/knowledge.py` → `service/knowledge.py`
- Move: `app/services/llm.py` → `service/llm.py`
- Move: `app/services/matcher.py` → `service/matcher.py`
- Move: `app/services/minio.py` → `service/minio.py`
- Move: `app/services/prompt.py` → `service/prompt.py`
- Move: `app/services/scoring.py` → `service/scoring.py`

- [ ] **Step 1: 复制所有 service 文件**

```bash
cp app/services/extraction.py service/extraction.py
cp app/services/knowledge.py service/knowledge.py
cp app/services/llm.py service/llm.py
cp app/services/matcher.py service/matcher.py
cp app/services/minio.py service/minio.py
cp app/services/prompt.py service/prompt.py
cp app/services/scoring.py service/scoring.py
```

- [ ] **Step 2: 重写 `service/extraction.py` 的 import**

```bash
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' service/extraction.py
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' service/extraction.py
sed -i '' 's/from app\.repositories\.hugegraph import HugeGraphRepository/from libs.hugegraph import HugeGraphRepository/' service/extraction.py
sed -i '' 's/from app\.repositories\.minio import MinioRepository/from libs.minio import MinioRepository/' service/extraction.py
sed -i '' 's/from app\.services\.llm import LlmService/from service.llm import LlmService/' service/extraction.py
sed -i '' 's/from app\.services\.matcher import MatcherService/from service.matcher import MatcherService/' service/extraction.py
sed -i '' 's/from app\.services\.prompt import PromptService/from service.prompt import PromptService/' service/extraction.py
```

- [ ] **Step 3: 重写 `service/knowledge.py` 的 import**

```bash
sed -i '' 's/from app\.core\.exceptions import KnowledgePointNotFound, PaperNotFound/from core.exceptions import KnowledgePointNotFound, PaperNotFound/' service/knowledge.py
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' service/knowledge.py
sed -i '' 's/from app\.domain\.schemas import (/from model.schemas import (/' service/knowledge.py
sed -i '' 's/from app\.repositories\.hugegraph import HugeGraphRepository/from libs.hugegraph import HugeGraphRepository/' service/knowledge.py
```

- [ ] **Step 4: 重写 `service/llm.py` 的 import**

```bash
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' service/llm.py
sed -i '' 's/from app\.core\.exceptions import LlmApiCallError/from core.exceptions import LlmApiCallError/' service/llm.py
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' service/llm.py
sed -i '' 's/from app\.domain\.models import LlmExtractResult/from model.models import LlmExtractResult/' service/llm.py
```

- [ ] **Step 5: 重写 `service/matcher.py` 的 import**

```bash
sed -i '' 's/from app\.domain\.models import (/from model.models import (/' service/matcher.py
```

- [ ] **Step 6: 重写 `service/minio.py` 的 import**

```bash
sed -i '' 's/from app\.domain\.schemas import MinioFileItem/from model.schemas import MinioFileItem/' service/minio.py
sed -i '' 's/from app\.repositories\.minio import MinioRepository/from libs.minio import MinioRepository/' service/minio.py
```

- [ ] **Step 7: 重写 `service/prompt.py` 的 import 并修正路径查找**

```bash
sed -i '' 's/from app\.repositories\.hugegraph import HugeGraphRepository/from libs.hugegraph import HugeGraphRepository/' service/prompt.py
```

修正 `build_prompt_sync` 和 `build_prompt` 中的路径查找逻辑。当前代码：
```python
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```
`service/prompt.py` 位于项目根下 1 层，改为向上 1 层：
```python
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```
实际上原来 `app/services/prompt.py` 向上 3 层是项目根，现在 `service/prompt.py` 向上 1 层就是项目根——等等，让我仔细算：`app/services/prompt.py` → dirname = `app/services` → dirname = `app` → dirname = 项目根。`service/prompt.py` → dirname = `service` → dirname = 项目根。所以从 3 层改为 2 层（`os.path.dirname` 调用次数从 3 次减少到 2 次）。

用 sed 替换：
```bash
# 将 3 次 dirname 改为 2 次（两处：build_prompt 和 build_prompt_sync）
sed -i '' 's/os\.path\.dirname(os\.path\.dirname(os\.path\.dirname(os\.path\.abspath(__file__))))/os.path.dirname(os.path.dirname(os.path.abspath(__file__)))/g' service/prompt.py
```

- [ ] **Step 8: 重写 `service/scoring.py` 的 import**

```bash
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' service/scoring.py
sed -i '' 's/from app\.domain\.schemas import QuestionScore, ScoringResponse, SectionScore/from model.schemas import QuestionScore, ScoringResponse, SectionScore/' service/scoring.py
sed -i '' 's/from app\.repositories\.hugegraph import HugeGraphRepository/from libs.hugegraph import HugeGraphRepository/' service/scoring.py
sed -i '' 's/from app\.services\.knowledge import KnowledgeService/from service.knowledge import KnowledgeService/' service/scoring.py
```

- [ ] **Step 9: 验证所有 service 文件语法**

```bash
python -c "
from service.extraction import ExtractionService
from service.knowledge import KnowledgeService
from service.llm import LlmService
from service.matcher import MatcherService
from service.minio import MinioService
from service.prompt import PromptService
from service.scoring import ScoringService
print('all services ok')
"
```

Expected: `all services ok`（注意：类实例化可能需要配置，仅 import 验证即可）

- [ ] **Step 10: 提交**

```bash
git add service/
git commit -m "refactor: move services to service/ package"
```

---

### Task 9: 移动 service/api/ 接口层并重写 import

**Files:**
- Move: `app/api/deps.py` → `service/api/deps.py`
- Move: `app/api/v1/router.py` → `service/api/router.py`
- Move: `app/api/v1/endpoints/extraction.py` → `service/api/endpoints/extraction.py`
- Move: `app/api/v1/endpoints/knowledge.py` → `service/api/endpoints/knowledge.py`
- Move: `app/api/v1/endpoints/minio.py` → `service/api/endpoints/minio.py`
- Move: `app/api/v1/endpoints/papers.py` → `service/api/endpoints/papers.py`
- Move: `app/api/v1/endpoints/scoring.py` → `service/api/endpoints/scoring.py`

- [ ] **Step 1: 复制所有 api 文件**

```bash
cp app/api/deps.py service/api/deps.py
cp app/api/v1/router.py service/api/router.py
cp app/api/v1/endpoints/extraction.py service/api/endpoints/extraction.py
cp app/api/v1/endpoints/knowledge.py service/api/endpoints/knowledge.py
cp app/api/v1/endpoints/minio.py service/api/endpoints/minio.py
cp app/api/v1/endpoints/papers.py service/api/endpoints/papers.py
cp app/api/v1/endpoints/scoring.py service/api/endpoints/scoring.py
```

- [ ] **Step 2: 重写 `service/api/deps.py` 全部 import**

```bash
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' service/api/deps.py
sed -i '' 's/from app\.repositories\.hugegraph import HugeGraphRepository/from libs.hugegraph import HugeGraphRepository/' service/api/deps.py
sed -i '' 's/from app\.repositories\.minio import MinioRepository/from libs.minio import MinioRepository/' service/api/deps.py
sed -i '' 's/from app\.services\.extraction import ExtractionService/from service.extraction import ExtractionService/' service/api/deps.py
sed -i '' 's/from app\.services\.knowledge import KnowledgeService/from service.knowledge import KnowledgeService/' service/api/deps.py
sed -i '' 's/from app\.services\.llm import LlmService/from service.llm import LlmService/' service/api/deps.py
sed -i '' 's/from app\.services\.matcher import MatcherService/from service.matcher import MatcherService/' service/api/deps.py
sed -i '' 's/from app\.services\.minio import MinioService/from service.minio import MinioService/' service/api/deps.py
sed -i '' 's/from app\.services\.prompt import PromptService/from service.prompt import PromptService/' service/api/deps.py
sed -i '' 's/from app\.services\.scoring import ScoringService/from service.scoring import ScoringService/' service/api/deps.py
```

- [ ] **Step 3: 重写 `service/api/router.py` 的 import**

```bash
sed -i '' 's/from app\.api\.v1\.endpoints import extraction, knowledge, minio, papers, scoring/from service.api.endpoints import extraction, knowledge, minio, papers, scoring/' service/api/router.py
```

- [ ] **Step 4: 重写各个 endpoint 文件的 import**

`service/api/endpoints/extraction.py`:
```bash
sed -i '' 's/from app\.api\.deps import get_extraction_service/from service.api.deps import get_extraction_service/' service/api/endpoints/extraction.py
sed -i '' 's/from app\.domain\.schemas import ExtractRequest, ExtractResult/from model.schemas import ExtractRequest, ExtractResult/' service/api/endpoints/extraction.py
sed -i '' 's/from app\.services\.extraction import ExtractionService/from service.extraction import ExtractionService/' service/api/endpoints/extraction.py
```

`service/api/endpoints/knowledge.py`:
```bash
sed -i '' 's/from app\.api\.deps import get_knowledge_service/from service.api.deps import get_knowledge_service/' service/api/endpoints/knowledge.py
sed -i '' 's/from app\.domain\.schemas import (/from model.schemas import (/' service/api/endpoints/knowledge.py
sed -i '' 's/from app\.services\.knowledge import KnowledgeService/from service.knowledge import KnowledgeService/' service/api/endpoints/knowledge.py
```

`service/api/endpoints/minio.py`:
```bash
sed -i '' 's/from app\.api\.deps import get_minio_service, get_redis/from service.api.deps import get_minio_service, get_redis/' service/api/endpoints/minio.py
sed -i '' 's/from app\.core\.events import publish_event/from core.events import publish_event/' service/api/endpoints/minio.py
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' service/api/endpoints/minio.py
sed -i '' 's/from app\.domain\.schemas import MinioFileItem/from model.schemas import MinioFileItem/' service/api/endpoints/minio.py
sed -i '' 's/from app\.services\.minio import MinioService/from service.minio import MinioService/' service/api/endpoints/minio.py
```

`service/api/endpoints/papers.py`:
```bash
sed -i '' 's/from app\.api\.deps import get_knowledge_service/from service.api.deps import get_knowledge_service/' service/api/endpoints/papers.py
sed -i '' 's/from app\.domain\.schemas import (/from model.schemas import (/' service/api/endpoints/papers.py
sed -i '' 's/from app\.services\.knowledge import KnowledgeService/from service.knowledge import KnowledgeService/' service/api/endpoints/papers.py
```

`service/api/endpoints/scoring.py`:
```bash
sed -i '' 's/from app\.api\.deps import get_scoring_service, get_settings/from service.api.deps import get_scoring_service, get_settings/' service/api/endpoints/scoring.py
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' service/api/endpoints/scoring.py
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' service/api/endpoints/scoring.py
sed -i '' 's/from app\.domain\.schemas import ScoringResponse/from model.schemas import ScoringResponse/' service/api/endpoints/scoring.py
sed -i '' 's/from app\.services\.scoring import ScoringService/from service.scoring import ScoringService/' service/api/endpoints/scoring.py
```

- [ ] **Step 5: 验证所有 api 文件语法**

```bash
python -c "
from service.api.deps import get_settings, get_extraction_service
from service.api.router import router
print('api layer ok')
"
```

Expected: `api layer ok`

- [ ] **Step 6: 提交**

```bash
git add service/api/
git commit -m "refactor: move api layer to service/api/ package"
```

---

### Task 10: 移动 main.py 和 cli.py 到根目录并重写 import

**Files:**
- Move: `app/main.py` → `main.py`（项目根）
- Move: `app/cli.py` → `cli.py`（项目根）

- [ ] **Step 1: 复制文件**

```bash
cp app/main.py main.py
cp app/cli.py cli.py
```

- [ ] **Step 2: 重写 `main.py` 全部 import**

```bash
sed -i '' 's/from app\.api\.v1\.router import router as v1_router/from service.api.router import router as v1_router/' main.py
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' main.py
sed -i '' 's/from app\.core\.events import start_consumer/from core.events import start_consumer/' main.py
sed -i '' 's/from app\.core\.exceptions import AppError/from core.exceptions import AppError/' main.py
sed -i '' 's/from app\.core\.logging import get_logger/from logs.logging import get_logger/' main.py
sed -i '' 's/from app\.repositories\.hugegraph import HugeGraphRepository/from libs.hugegraph import HugeGraphRepository/' main.py
sed -i '' 's/from app\.repositories\.minio import MinioRepository/from libs.minio import MinioRepository/' main.py
sed -i '' 's/from app\.services\.extraction import ExtractionService/from service.extraction import ExtractionService/' main.py
sed -i '' 's/from app\.services\.llm import LlmService/from service.llm import LlmService/' main.py
sed -i '' 's/from app\.services\.matcher import MatcherService/from service.matcher import MatcherService/' main.py
sed -i '' 's/from app\.services\.prompt import PromptService/from service.prompt import PromptService/' main.py
```

- [ ] **Step 3: 重写 `cli.py` 全部 import**

```bash
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' cli.py
sed -i '' 's/from app\.repositories\.hugegraph import HugeGraphRepository/from libs.hugegraph import HugeGraphRepository/' cli.py
sed -i '' 's/from app\.repositories\.minio import MinioRepository/from libs.minio import MinioRepository/' cli.py
sed -i '' 's/from app\.services\.extraction import ExtractionService/from service.extraction import ExtractionService/' cli.py
sed -i '' 's/from app\.services\.llm import LlmService/from service.llm import LlmService/' cli.py
sed -i '' 's/from app\.services\.matcher import MatcherService/from service.matcher import MatcherService/' cli.py
sed -i '' 's/from app\.services\.prompt import PromptService/from service.prompt import PromptService/' cli.py
```

- [ ] **Step 4: 验证语法**

```bash
python -c "import main; print('main.py ok')"
python -c "import cli; print('cli.py ok')"
```

Expected: `main.py ok` 然后 `cli.py ok`

- [ ] **Step 5: 提交**

```bash
git add main.py cli.py
git commit -m "refactor: move main.py and cli.py to project root"
```

---

### Task 11: 迁移测试目录和 import

**Files:**
- Move: `tests/unit/test_core_config.py` → `tests/unit/test_conf_config.py`
- Move: `tests/unit/test_domain/` → `tests/unit/test_model/`
- Move: `tests/unit/test_repositories/` → `tests/unit/test_libs/`
- Move: `tests/unit/test_services/` → `tests/unit/test_service/`

- [ ] **Step 1: 创建新测试目录并移动文件**

```bash
mkdir -p tests/unit/test_model tests/unit/test_libs tests/unit/test_service

# test_model
cp tests/unit/test_domain/test_models.py tests/unit/test_model/test_models.py
cp tests/unit/test_domain/test_schemas.py tests/unit/test_model/test_schemas.py
touch tests/unit/test_model/__init__.py

# test_libs
cp tests/unit/test_repositories/test_hugegraph.py tests/unit/test_libs/test_hugegraph.py
cp tests/unit/test_repositories/test_minio.py tests/unit/test_libs/test_minio.py
touch tests/unit/test_libs/__init__.py

# test_service (keep existing __init__.py if present)
cp tests/unit/test_services/test_extraction.py tests/unit/test_service/test_extraction.py
cp tests/unit/test_services/test_knowledge.py tests/unit/test_service/test_knowledge.py
cp tests/unit/test_services/test_llm.py tests/unit/test_service/test_llm.py
cp tests/unit/test_services/test_matcher.py tests/unit/test_service/test_matcher.py
cp tests/unit/test_services/test_prompt.py tests/unit/test_service/test_prompt.py
cp tests/unit/test_services/test_scoring.py tests/unit/test_service/test_scoring.py
```

- [ ] **Step 2: 重写 `tests/unit/test_conf_config.py` 的 import**

```bash
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' tests/unit/test_conf_config.py
```

- [ ] **Step 3: 重写 `tests/unit/test_core_exceptions.py` 的 import**

```bash
sed -i '' 's/from app\.core\.exceptions import (/from core.exceptions import (/' tests/unit/test_core_exceptions.py
```

- [ ] **Step 4: 重写 `tests/unit/test_model/` 下文件的 import**

```bash
sed -i '' 's/from app\.domain\.models import/from model.models import/' tests/unit/test_model/test_models.py
sed -i '' 's/from app\.domain\.schemas import (/from model.schemas import (/' tests/unit/test_model/test_schemas.py
```

- [ ] **Step 5: 重写 `tests/unit/test_libs/` 下文件的 import**

```bash
sed -i '' 's/from app\.core\.config import Settings/from conf.config import Settings/' tests/unit/test_libs/test_hugegraph.py
sed -i '' 's/from app\.domain\.models import Edge, Vertex/from model.models import Edge, Vertex/' tests/unit/test_libs/test_hugegraph.py
sed -i '' 's/from app\.repositories\.hugegraph import HugeGraphRepository/from libs.hugegraph import HugeGraphRepository/' tests/unit/test_libs/test_hugegraph.py
sed -i '' 's/from app\.core\.exceptions import MinioObjectNotFound/from core.exceptions import MinioObjectNotFound/' tests/unit/test_libs/test_minio.py
sed -i '' 's/from app\.repositories\.minio import MinioRepository/from libs.minio import MinioRepository/' tests/unit/test_libs/test_minio.py
```

- [ ] **Step 6: 重写 `tests/unit/test_service/` 下所有文件的 import**

```bash
# test_extraction.py
sed -i '' 's/from app\.domain\.models import (/from model.models import (/' tests/unit/test_service/test_extraction.py
sed -i '' 's/from app\.services\.extraction import ExtractionService/from service.extraction import ExtractionService/' tests/unit/test_service/test_extraction.py

# test_knowledge.py
sed -i '' 's/from app\.core\.exceptions import KnowledgePointNotFound, PaperNotFound/from core.exceptions import KnowledgePointNotFound, PaperNotFound/' tests/unit/test_service/test_knowledge.py
sed -i '' 's/from app\.domain\.schemas import KnowledgePointRelationsResponse/from model.schemas import KnowledgePointRelationsResponse/' tests/unit/test_service/test_knowledge.py
sed -i '' 's/from app\.services\.knowledge import KnowledgeService/from service.knowledge import KnowledgeService/' tests/unit/test_service/test_knowledge.py

# test_llm.py
sed -i '' 's/from app\.core\.exceptions import LlmApiCallError/from core.exceptions import LlmApiCallError/' tests/unit/test_service/test_llm.py
sed -i '' 's/from app\.services\.llm import LlmService/from service.llm import LlmService/' tests/unit/test_service/test_llm.py

# test_matcher.py
sed -i '' 's/from app\.domain\.models import (/from model.models import (/' tests/unit/test_service/test_matcher.py
sed -i '' 's/from app\.services\.matcher import MatcherService/from service.matcher import MatcherService/' tests/unit/test_service/test_matcher.py
sed -i '' 's/from app\.utils\.snowflake import Snowflake/from utils.snowflake import Snowflake/' tests/unit/test_service/test_matcher.py

# test_prompt.py
sed -i '' 's/from app\.services\.prompt import PromptService/from service.prompt import PromptService/' tests/unit/test_service/test_prompt.py

# test_scoring.py
sed -i '' 's/from app\.services\.scoring import (/from service.scoring import (/' tests/unit/test_service/test_scoring.py
```

- [ ] **Step 7: 重写 `tests/unit/test_utils_snowflake.py` 的 import**

```bash
sed -i '' 's/from app\.utils\.snowflake import Snowflake/from utils.snowflake import Snowflake/' tests/unit/test_utils_snowflake.py
```

- [ ] **Step 8: 重写 `tests/test_paths.py` 的 import**

```bash
sed -i '' 's/from app\.utils import paths/from utils import paths/' tests/test_paths.py
```

- [ ] **Step 9: 验证所有测试文件语法**

```bash
python -c "
import tests.unit.test_conf_config
import tests.unit.test_core_exceptions
import tests.unit.test_model.test_models
import tests.unit.test_model.test_schemas
import tests.unit.test_libs.test_hugegraph
import tests.unit.test_libs.test_minio
import tests.unit.test_service.test_extraction
import tests.unit.test_service.test_knowledge
import tests.unit.test_service.test_llm
import tests.unit.test_service.test_matcher
import tests.unit.test_service.test_prompt
import tests.unit.test_service.test_scoring
import tests.unit.test_utils_snowflake
import tests.test_paths
print('all test imports ok')
"
```

Expected: `all test imports ok`

- [ ] **Step 10: 提交**

```bash
git add tests/
git commit -m "refactor: migrate tests to new module structure"
```

---

### Task 12: 清理旧 `app/` 目录并更新 README

**Files:**
- Delete: `app/` 整个目录
- Modify: `README.md`（更新项目结构说明）
- Modify: `Dockerfile`（如有引用 `app` 的路径）

- [ ] **Step 1: 删除旧的 `app/` 目录**

```bash
rm -rf app/
```

- [ ] **Step 2: 更新 README.md 中的项目结构**

将 `README.md` 中的项目结构树从旧的分层结构更新为：

```markdown
## 项目结构

```text
.
├── main.py                     # FastAPI 应用入口
├── cli.py                      # 命令行入口
├── bin/                        # 启动/部署脚本
├── conf/                       # 配置
│   └── config.py               # pydantic-settings 配置中心
├── core/                       # 基础机制
│   ├── exceptions.py           # 统一异常定义
│   └── events.py               # Redis Streams 消费者
├── libs/                       # 外部系统封装
│   ├── hugegraph.py            # HugeGraph REST API 封装
│   └── minio.py                # MinIO 异步 SDK 封装
├── model/                      # 纯 Pydantic 数据模型
│   ├── models.py               # 领域模型
│   └── schemas.py              # API 请求/响应 DTO
├── service/                    # 业务逻辑
│   ├── api/                    # HTTP 接口层
│   │   ├── deps.py             # FastAPI 依赖注入
│   │   ├── router.py           # 路由汇总
│   │   └── endpoints/          # 端点处理函数
│   ├── extraction.py           # 抽取流水线编排
│   ├── knowledge.py            # 知识点/试卷查询
│   ├── llm.py                  # AsyncOpenAI LLM 调用
│   ├── matcher.py              # 知识点严格匹配
│   ├── minio.py                # MinIO 文件浏览服务
│   ├── prompt.py               # Prompt 构建
│   └── scoring.py              # OCR markdown 解析（判分）
├── utils/                      # 通用工具
│   ├── snowflake.py            # 简易雪花 ID 生成器
│   └── paths.py                # 项目路径管理
├── logs/                       # 日志配置
│   └── logging.py
├── prompts/                    # LLM Prompt 模板
├── tests/                      # 测试集
├── reference/                  # 参考资料
├── docs/                       # 文档
├── requirements.txt
└── README.md
```
```

同时更新启动命令：
```bash
# 旧：python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
# 新：python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

- [ ] **Step 3: 检查 Dockerfile 是否需要更新**

```bash
grep -n "app" Dockerfile || echo "no app references in Dockerfile"
```

如果 Dockerfile 中有 `app.main:app` 需改为 `main:app`。

- [ ] **Step 4: 提交**

```bash
git rm -r app/
git add README.md Dockerfile  # 如果 Dockerfile 有改动
git commit -m "chore: remove old app/ directory, update docs"
```

---

### Task 13: 运行测试验证

- [ ] **Step 1: 运行全部测试**

```bash
python -m pytest tests/ -v
```

Expected: 所有之前通过的测试仍然通过。如果有 import 错误，检查遗漏的文件。

- [ ] **Step 2: 验证应用可启动**

```bash
python -c "from main import create_app; app = create_app(); print('App created successfully')"
```

Expected: `App created successfully`

- [ ] **Step 3: 如有失败，修复后提交**

```bash
git add -A
git commit -m "fix: resolve remaining import issues after restructure"
```
