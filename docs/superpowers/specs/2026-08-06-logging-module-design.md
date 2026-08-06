# 日志模块设计

**日期**: 2026-08-06
**状态**: 待审核

## 目标

为全项目提供统一的结构化日志、调用链追踪和边界异常体系，使排查从"翻多行日志拼凑调用栈"变为"按 correlation_id 过滤即可看到完整链路"。

## 非目标

- 不改动现有业务逻辑
- 不引入 ELK/Loki 等外部日志收集系统（保持 stdout 输出，Docker 友好）
- 不强依赖第三方 SDK（仅标准库 + 现有依赖）

---

## 模块结构

```
logs/
├── __init__.py          # 公开导出
├── logging.py           # 现有 get_logger，增量修改
├── decorators.py        # @log_step + 类级自动代理
├── context.py           # correlation_id + 请求上下文
```

`core/exceptions.py` 保留在原位，增量补充外部服务边界异常。

---

## 1. `logs/context.py` — 调用链上下文

### 1.1 `correlation_id`

基于 `contextvars.ContextVar`，在每个 HTTP 请求/Redis 消息处理开始时设置，结束时自动清理。

```python
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

def set_correlation_id(cid: str | None = None) -> str:
    """设置当前协程的 correlation_id；未传时自动生成 uuid4 短码。"""
    cid = cid or uuid.uuid4().hex[:12]
    _correlation_id.set(cid)
    return cid

def get_correlation_id() -> str:
    """获取当前协程的 correlation_id。"""
    return _correlation_id.get()
```

### 1.2 FastAPI middleware

在 `main.py` 中添加中间件：

```python
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    cid = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex[:12]
    set_correlation_id(cid)
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = cid
    return response
```

Redis 消费者在消费每条消息时也调 `set_correlation_id()`。

### 1.3 日志格式变更

`get_logger` 的输出格式增加 `[cid]` 字段：

```
%(asctime)s [%(levelname)s] [%(cid)s] %(name)s: %(message)s
```

通过 `logging.Filter` 注入 `cid` 字段，避免每个 logger 调用方手动传。

---

## 2. `logs/decorators.py` — `@log_step` 装饰器

### 2.1 方法级装饰器

```python
@log_step(skip=False, log_args=True, log_result=False, level="info")
```

**行为：**

| 时机 | 日志内容 | 级别 |
|---|---|---|
| 方法进入 | `→ method_name | args: (摘要) | elapsed: -` | DEBUG |
| 方法正常返回 | `← method_name | done | elapsed: 1.23s` | 传入的 level |
| 方法抛异常 | `✗ method_name | failed: <异常类名> | elapsed: 0.45s` | ERROR |

**args 摘要规则：**
- 基本类型 (str/int/float/bool/None) → 直接输出
- list/dict → 输出 `len=N` 摘要
- Pydantic/自定义对象 → 输出 `type:ClassName`
- 单参数超过 200 字符截断

**result 摘要规则：**
- `log_result=True` 时输出，规则同 args
- 默认 `False`，避免大 JSON 刷屏

**skip 语义：**
- `skip=True` → 完全不记录，原样透传（用于 property、简单 getter）

### 2.2 类级自动代理

`@log_step` 装饰在类上时，通过 `__init_subclass__` 自动为所有 public 方法添加日志。

**自动跳过的方法：**
- `__init__`, `__str__`, `__repr__`, `__getattr__` 等双下划线方法
- `@property`、`@staticmethod`、`@classmethod`（记录归属类名）
- 方法名以 `_` 开头（私有/内部方法）

**用法：**

```python
@log_step
class ExtractionService:
    async def run(self, object_key, ...):   # 自动记录
        ...

    def _save_artifacts(self, ...):          # _ 开头，跳过
        ...

    @staticmethod
    def _dedupe(items, max_capacity):        # _ 开头，跳过
        ...
```

### 2.3 与现有日志的共存

`@log_step` **不替代**方法内的业务日志（如 `log.info("开始抽取流水线")`）。两者共存：
- `@log_step` → 自动记录调用/耗时/异常（结构化的诊断信息）
- 方法内 `log.info/warning` → 业务语义日志（如 "知识点不存在"、"Milvus 双写完成"）

后续可以逐步从方法内删除冗余的"开始…"、"完成…"日志，但不强制。

---

## 3. `core/exceptions.py` 增量

### 3.1 新增边界异常

```python
class ExternalServiceError(AppError):
    """外部服务调用失败（超时/连接拒绝/DNS 解析失败等）。"""
    def __init__(self, service: str, message: str, detail: dict | None = None):
        d = detail or {}
        d["service"] = service
        super().__init__(message, status_code=502, detail=d)

class HugeGraphTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("hugegraph", message, detail)

class MilvusTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("milvus", message, detail)

class MinioTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("minio", message, detail)

class OcrServiceError(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("ocr", message, detail)

class RedisTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("redis", message, detail)
```

### 3.2 异常边界约定

libs 层捕获 `httpx.TimeoutException` / `ConnectTimeout` / `ReadTimeout` 后 → 抛对应 `ExternalServiceError` 子类。不是所有地方强制改，但 `hugegraph.py`、`milvus.py`、`minio.py` 的异常包装优先做。

---

## 4. 关键集成点

### 4.1 `libs/hugegraph.py`

- 类上加 `@log_step`
- `_client()` 的 timeout 异常 → `raise HugeGraphTimeout(...) from exc`
- 现有 `log.info` / `log.error` 保留

### 4.2 `libs/minio.py`

- 类上加 `@log_step`
- 连接超时 → `raise MinioTimeout(...) from exc`

### 4.3 `service/extraction.py`

- 类上加 `@log_step`
- `run()` 的每个步骤自动记录耗时，排查时一眼看出哪步卡住

### 4.4 `api/endpoints/*.py`

- 端点函数不用 `@log_step`（FastAPI 有自己的日志），但异常处理器在返回 500 时自动带 `correlation_id`

### 4.5 `core/events.py` (Redis consumer)

- 每条消息消费前调 `set_correlation_id()`
- 消费逻辑内自动继承 `correlation_id` 到所有 `@log_step` 日志

---

## 5. 测试策略

### 5.1 单元测试 (`tests/unit/`)

| 测试对象 | 验证点 |
|---|---|
| `logs/context.py` | set → get 在同一协程可见；不同协程隔离 |
| `logs/decorators.py` | 方法级记录进入/退出/异常；skip=True 不记录；类级自动包装；`_` 前缀方法跳过 |
| `core/exceptions.py` | 子类 status_code、detail 正确注入 service 字段 |

### 5.2 集成测试 (`tests/integration/`)

- middleware 注入 `X-Correlation-Id` 并返回在响应头中
- 异常处理器在 500 响应中携带 correlation_id

---

## 6. 迁移计划

1. 实现 `context.py` + middleware + logging 格式变更 → 全局 cid 生效
2. 实现 `decorators.py` → `@log_step` 可用
3. 为 `hugegraph.py`、`minio.py`、`extraction.py`、`llm.py` 四个核心模块加装饰器
4. 补充 `ExternalServiceError` 子类，在 hugegraph/minio 中替换裸 Exception
5. 后续 PR 逐步覆盖其余 service/libs

---

## 7. 风险

| 风险 | 缓解 |
|---|---|
| 装饰器引入性能开销（每个方法调用多两次 `time.time` + 日志格式化） | 开销 < 1ms，对于 I/O 密集的抽取流水线（总耗时 30-120s）可忽略 |
| args 序列化可能触发惰性求值或大对象 dump | 仅做摘要（len/type），不递归序列化；log_result 默认关闭 |
| 生产环境 `DEBUG` 日志量膨胀 | 方法进入日志用 DEBUG 级别；生产设 INFO 则只输出完成/异常日志 |
