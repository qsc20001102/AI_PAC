# AI PAC 智能除磷加药系统 — 编码规范

> 适用技术栈：FastAPI + SQLite + LightGBM + python-snap7 + pymodbus + 原生 HTML/CSS/JS（ES6+，无构建步骤）

---

## 1. 项目结构规范

```
ai_pac/
├── app/                    # 后端 Python 包
│   ├── __init__.py
│   ├── main.py             # FastAPI 应用入口、lifespan、静态挂载、router include
│   ├── database.py         # Schema 定义、连接管理、运行期迁移、工具函数
│   ├── api/                # API 路由层（FastAPI APIRouter），每个业务模块一个文件
│   │   ├── __init__.py
│   │   ├── common.py       # row_to_dict 工具（_json 后缀字段自动解析）
│   │   ├── health.py       # /api/health + /api/backend/status
│   │   ├── auth.py         # /api/auth/login/me/logout/password
│   │   ├── alarms.py       # /api/alarms*
│   │   ├── collection.py   # /api/collection* + /api/samples* + /api/history-data*
│   │   ├── dashboard.py    # /api/dashboard（带 60 秒 TTL 缓存）
│   │   ├── dosing_points.py # /api/dosing-points* + 虚拟采集点标签创建
│   │   ├── ingest.py       # /api/ingest/samples + /api/import/csv + 演示轮询
│   │   ├── models.py       # /api/models*（双任务模型配置、CSV 导入/导出、训练/部署）
│   │   ├── plc.py          # /api/plc*（设备 CRUD + 连接/断开）
│   │   ├── process_groups.py # /api/process-lines + /api/process-parameter-groups*
│   │   ├── settings.py     # /api/settings* + /api/backup + export
│   │   └── trends.py       # /api/trends + /api/savings
│   ├── schemas/            # Pydantic 请求/响应模型，统一在 __init__.py 导出
│   │   ├── __init__.py     # 所有 Pydantic 模型统一导出（__all__）
│   │   ├── config.py       # 工艺参数组、设置更新、单耗曲线点
│   │   ├── dosing.py       # 投加点 CRUD、采集标签、样本导入
│   │   ├── model.py        # 模型项目 CRUD、样本导入、部署
│   │   └── plc.py          # PLC 设备 CRUD
│   └── services/           # 业务逻辑层（纯函数风格）
│       ├── __init__.py
│       ├── audit.py            # 审计日志写入
│       ├── auth.py             # 用户认证、密码哈希、token 管理
│       ├── collection_data.py  # 采集质量判断、数据写入、模拟数据生成、数据质量统计
│       ├── collection_runtime.py # 采集循环调度（1 秒轮询）、PLC 读取、历史写入
│       ├── feature_schema.py   # 特征模式唯一数据源：13 个过程变量的映射（Single Source of Truth）
│       ├── model_training.py   # 模型样本记录、实时记录、CSV 导入、双任务模型训练
│       ├── plc.py              # PLC 协议层：S7-1500（snap7）+ Modbus TCP（pymodbus）
│       ├── plc_devices.py      # PLC 设备运行态管理、自动重连、事件写入
│       ├── recommendation.py   # 推荐计算核心：保守公式、双任务模型推理、二分搜索、持久化
│       ├── seed.py             # 空项目基础数据初始化
│       ├── settings_config.py  # 系统设置读取/写入
│       └── wwtp_ai_engine.py   # 污水处理 AI 引擎：DataImporter + FeatureEngineer + ModelTrainer + InferencePipeline
│
├── static/                 # 前端静态资源（无构建步骤）
│   ├── index.html          # 单页应用入口
│   ├── styles.css          # 全局样式（CSS 变量在 :root 中统一定义）
│   ├── js/
│   │   ├── state.js        # 全局状态管理（activePage, selectedPointId, trendHours 等）
│   │   ├── format.js       # 格式化工具函数（数值、日期、状态标签、htmlEscape）
│   │   ├── api.js          # 统一 API 请求封装（自动携带 X-Token）
│   │   ├── boot.js         # 应用引导、导航渲染、路由分发
│   │   ├── start.js        # 应用启动入口
│   │   └── pages/
│   │       ├── overview.js           # 总览页面（推荐卡片、趋势图、推荐解释、节省加药、报警）
│   │       ├── process.js            # 工艺配置页面（投加点、工艺参数组、单耗曲线编辑器）
│   │       ├── data.js               # 数据管理页面（采集点、历史曲线/表格、数据清理）
│   │       ├── models.js             # 模型管理页面（双任务配置、样本导入/导出、训练/部署）
│   │       ├── plc.js                # PLC 设备页面（设备列表、连接/断开、事件记录）
│   │       └── alarms-settings.js    # 报警与系统设置页面（告警确认、密码修改、备份）
│   └── app.js              # 兼容性语法检查入口
│
├── tests/                  # 单元测试（unittest 风格）
│   └── test_recommendation.py
│
├── data/                   # 运行时数据（不提交版本库）
│   └── ai_pac.sqlite       # SQLite 主数据库
│
├── docs/                   # 项目文档
│   ├── CODING_STANDARDS.md
│   ├── API_REFERENCE.md
│   └── MAINTENANCE.md
│
├── backup/                 # 数据库备份目录（自动创建）
├── logs/                   # 服务日志目录
├── run_server.py           # 服务器启动脚本（自动读取配置端口）
└── requirements.txt        # Python 依赖清单
```

### 分层职责

| 层          | 职责                           | 依赖方向         |
| ----------- | ------------------------------ | ---------------- |
| `api/`      | 请求校验、参数转换、调用服务、返回响应 | 可调用 `services/`、`schemas/` |
| `schemas/`  | Pydantic 模型定义              | 无业务依赖       |
| `services/` | 纯业务逻辑、数据库读写         | 可调用 `database`、`feature_schema` |
| `database`  | 连接管理、Schema、迁移          | 无上层依赖       |

---

## 2. Python 后端规范

### 2.1 基本要求

- 所有 `.py` 文件首行使用：

  ```python
  from __future__ import annotations
  ```

- Python 版本目标：3.10+

### 2.2 类型注解

- 函数参数和返回值**必须**使用类型注解：

  ```python
  def get_recommendation(
      con: sqlite3.Connection,
      point_id: int,
      current_tp: float,
  ) -> dict[str, Any]:
      ...
  ```

- 集合类型使用内置泛型（`dict[str, Any]`、`list[int]`），不使用 `typing.Dict` / `typing.List`。
- 复杂返回值优先用 `TypedDict` 或 `NamedTuple`（如 `feature_schema.py` 中的 `ProcessVariable`）。

### 2.3 数据库连接

- **禁止**在模块级或类内缓存连接。
- 通过 `database.py` 中的上下文管理器获取连接：

  ```python
  from app.database import db_session

  async def endpoint():
      with db_session() as con:
          rows = con.execute("SELECT ...").fetchall()
      # 退出 with 块时自动 commit，异常时自动 rollback + close
  ```

- 连接返回 `sqlite3.Row`，通过列名访问字段，不使用索引。
- 批量查询前预加载映射数据，避免 N+1 查询模式（如 `collection_data.py` 中的标签批量预加载）。

### 2.4 API 路由

- 每个业务模块一个文件，使用 `APIRouter`，直接在 `main.py` 中 `include_router`：

  ```python
  from fastapi import APIRouter

  router = APIRouter()
  ```

- 路由路径以 `/api/` 开头，不使用额外的版本前缀（如 `/api/v1/`）。
- 在 `main.py` 中通过 `app.include_router(router)` 注册。
- 认证 token 验证直接从 `request.headers` 读取 `x-token`，不依赖 FastAPI `Header()` 对自定义 header 的解析。

### 2.5 服务层

- **纯函数风格**：函数接收 `con: sqlite3.Connection` 作为参数，不存储连接。
- 不在服务层定义类来持有状态；使用普通模块级函数或简单数据容器（NamedTuple）。
- 服务函数应做到可独立测试（传入 mock 连接即可）。
- **例外**：采集运行时（`collection_runtime.py`）使用 `asyncio` 后台循环，PLC 设备管理器（`plc_devices.py`）使用内存字典缓存客户端连接，这些是必要的状态持有，不属于普通业务服务。

### 2.6 特征模式（feature_schema）—— 单一数据源

- `feature_schema.py` 是 13 个过程变量映射的 **唯一数据源**，消除此前在 `model_training`、`recommendation`、`wwtp_ai_engine` 三处的重复映射。
- 使用 `ProcessVariable` NamedTuple 统一持有 6 种标识：`dosing_field`、`tag_type`、`logical_type`、`raw_col`、`unit`、`label`、`dual_label`。
- 其他模块通过 `raw_cols()`、`tag_to_raw_map()`、`dual_task_input_features()` 等方法派生所需数据。
- **禁止**在其他模块中硬编码过程变量映射。

### 2.7 wwtp_ai_engine —— AI 引擎规范

`wwtp_ai_engine.py` 包含四个内部类：

| 类 | 职责 | 说明 |
|---|---|---|
| `DataImporter` | CSV 数据导入与清洗 | 自动检测编码、列名映射、缺失值/异常值处理 |
| `FeatureEngineer` | 特征工程 | 所有特征构建方法均为 `@staticmethod`，可被训练和推理复用 |
| `ModelTrainer` | 模型训练 | 使用双任务 LightGBM 训练，评估指标保存 |
| `InferencePipeline` | 实时推理 | 通过 `deque` 维护滑动窗口历史，复用 FeatureEngineer 的静态方法保证特征一致性 |

**关键规则**：
- 推理时特征计算必须复用 `FeatureEngineer` 的静态方法（通过 `_compute_features()` 调用），不得重写，保证训练-推理特征一致。
- `InferencePipeline` 不能在 `__init__` 加载文件（仅用于训练产物加载），外部代码通过 `__new__` 绕过 `__init__` 直接设置 `model1/model2/features1/features2/history/sample_interval_minutes` 来构造实例用于推理。

### 2.8 认证规范

- 密码存储使用 PBKDF2-HMAC-SHA256 + 随机 salt，100000 轮迭代（纯 Python 标准库）：

  ```python
  def _hash_password(password: str) -> str:
      salt = secrets.token_hex(16)
      pwdhash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
      return salt + pwdhash.hex()
  ```

- 认证使用随机 session token（`secrets.token_urlsafe(32)`），有效期 7 天，存入 `user_sessions` 表。
- 验证 token 时从 `request.headers` 直接读取 `x-token` / `X-Token`。
- 修改密码后自动清除该用户的所有 session，强制重新登录。
- 无需额外依赖（bcrypt/jwt 等），纯 Python 标准库实现。

### 2.9 错误处理

- API 层统一使用 `try/except`，返回 HTTP 异常：

  ```python
  @router.get("/items/{item_id}")
  async def get_item(item_id: int):
      try:
          with db_session() as con:
              return service.get_item(con, item_id)
      except Exception as e:
          raise HTTPException(status_code=500, detail=str(e))
  ```

- 不在 API 层做业务判断型的异常区分；业务规则异常由服务层返回特定值（如 `None` + error message），API 层根据返回值决定响应。

### 2.10 命名约定

| 类别     | 风格             | 示例                    |
| -------- | ---------------- | ----------------------- |
| 函数/方法 | `snake_case`     | `get_recommendation`   |
| 变量     | `snake_case`     | `current_tp`            |
| 常量     | `UPPER_SNAKE_CASE` | `DB_PATH`, `SCHEMA`   |
| 类       | `PascalCase`     | `DosingPointConfig`     |
| APIRouter 变量 | `router`     | `router = APIRouter()` |
| Pydantic 模型 | `PascalCase` | `DosingPointCreate` |

### 2.11 日志规范

- 使用 Python 标准库 `logging`，不在此项目中使用 `print()`。
- 关键操作（模型训练/投用、PLC 连接/断开、数据导入、审计）必须记录日志。
- 异常堆栈使用 `logger.error("...", exc_info=True)` 记录。
- 异步采集循环的异常使用 `logger.error` + `continue` 处理，不影响循环继续运行。

### 2.12 时间处理

- 项目固定在北京时区（`datetime.now()`），不使用 UTC。
- 所有时间字符串使用 ISO 8601 格式（`datetime.isoformat()` / `datetime.fromisoformat()`）。
- 函数名 `utc_now_iso()` 为历史遗留名，实际返回本地时间，因调用方过多不便重命名。

---

## 3. 前端规范

### 3.1 基本要求

- 无构建步骤，原生 ES6+ 语法。
- 不引入 React / Vue / TypeScript，不使用 npm 构建流程。
- 图表使用原生 Canvas 2D API 手绘，**不引入**第三方图表库（如 ECharts、Chart.js）。
- 脚本加载顺序：`state.js` → `format.js` → `api.js` → `boot.js` → `start.js` + page 文件

### 3.2 全局状态管理

- 全部页面共享状态集中在 `static/js/state.js`：

  ```javascript
  const state = {
    activePage: "overview",
    selectedPointId: 1,
    trendHours: 3,
    // ...
  };
  ```

- 读取状态直接访问 `state.xxx`，修改后如需刷新页面调用对应的 render 函数。
- 禁止在页面脚本中新增全局变量；所有共享状态必须声明在 `state.js` 中。

### 3.3 API 请求

- 统一通过 `static/js/api.js` 中的 `api()` 函数发起请求：

  ```javascript
  const data = await api("/api/dashboard");
  ```

- `api()` 内部处理 JSON 序列化、错误提取和异常抛出，页面代码无需重复处理。
- GET 请求不带 `Content-Type` header，避免浏览器产生预检请求。
- 认证 token 从 `localStorage` 读取，通过 `X-Token` header 发送：

  ```javascript
  const token = localStorage.getItem("token");
  if (token) {
    init.headers = { ...init.headers, "X-Token": token };
  }
  ```

- token 失效时（后端返回 `{"authenticated": false}`），前端自动清除 `localStorage` 中的 token。

### 3.4 页面函数命名

- 渲染函数：`render{PageName}(main)`，参数为容器 DOM 元素。

  ```javascript
  async function renderOverview(main) {
    main.innerHTML = `...`;
    wireOverview(main.querySelector(".detail"));
  }
  ```

- 事件绑定函数：`wire{PageName}(detail)`，参数为详情区域 DOM 元素。

  ```javascript
  function wireOverview(detail) {
    detail.querySelector(".btn-refresh").addEventListener("click", async () => {
      await renderOverview(main);
    });
  }
  ```

### 3.5 格式化函数

- 所有格式化/显示用函数集中在 `static/js/format.js`：
  - 数值格式化（小数位、单位）
  - 日期时间格式化
  - 状态标签颜色映射（good/bad/unknown, dual_task_ai/conservative/abnormal）
  - `htmlEscape()` — HTML 转义函数
- 页面脚本中 **禁止** 内联格式化逻辑，统一调用 `format.js` 中的函数。

### 3.6 HTML 转义

- 所有用户数据插入 HTML 前 **必须** 经过 `htmlEscape()` 转义：

  ```javascript
  <div class="point-name">${htmlEscape(rec.dosing_point_name)}</div>
  ```

- 禁止使用 `innerHTML = userInput`（未经转义）。

### 3.7 CSS 规范

- CSS 变量在 `styles.css` 顶部 `:root` 中统一定义：

  ```css
  :root {
    --color-primary: #1a73e8;
    --color-danger: #d93025;
    --color-success: #0d904f;
    --color-warning: #f9ab00;
    --radius-sm: 4px;
    --radius-md: 8px;
    /* ... */
  }
  ```

- 样式类命名使用语义化连字符命名（如 `.panel-title`、`.alarm-meta`、`.metric-card`）。
- 禁止使用内联样式声明颜色/尺寸。

### 3.8 图表绘制（Canvas 2D）

- 全部手动绘制，Canvas 辅助函数（tooltip 绑定、图例渲染、轴刻度计算）在页面文件内定义。
- 趋势图至少包含：时间轴（X）、数值轴（Y）、图例、tooltip（鼠标悬停时显示数值+时间）、网格线。
- 节省加药流量图必须包含：零线（`y=0`）、正负值颜色区分（绿色节省/红色多用）、累计值显示。

---

## 4. 数据库规范

### 4.1 Schema 管理

- 所有建表 DDL 集中在 `app/database.py` 的 `SCHEMA` 常量中。
- 使用 `CREATE TABLE IF NOT EXISTS`，保证幂等执行。
- 运行期新增的表（在 `ensure_runtime_schema` 中）也要写 `CREATE TABLE IF NOT EXISTS`。

### 4.2 运行期兼容

- 通过 `ensure_runtime_schema(con)` 函数处理运行期 Schema 变更。
- 该函数负责：补列（`ALTER TABLE ADD COLUMN IF NOT EXISTS`）、补索引、回填默认值、数据迁移。
- 使用 `PRAGMA user_version` 门控需要只执行一次的迁移操作。
- `ensure_columns()` 包含表名白名单校验（`_ALLOWED_TABLE_NAMES`），防止 SQL 注入。

### 4.3 禁止操作

- **禁止直接删表**（`DROP TABLE`），避免运行期数据丢失。
- **禁止修改已有列的类型**（SQLite 不支持原生 `ALTER COLUMN`）。
- 只允许：补列、补索引、补表、回填数据、更新数据。
- 如需处理已停用的旧表，保留不动，不做自动删除。

### 4.4 WAL 模式

- 数据库连接启用 WAL 模式，减少读写互斥：

  ```python
  con.execute("PRAGMA journal_mode = WAL")
  con.execute("PRAGMA synchronous = NORMAL")
  con.execute("PRAGMA foreign_keys = ON")
  con.execute("PRAGMA busy_timeout = 10000")
  ```

### 4.5 时间格式

- `sample_time` 列使用 **ISO 8601 字符串**存储（如 `"2026-07-02T14:30:00"`）。
- Python 端通过 `datetime.isoformat()` 写入，读取时用 `datetime.fromisoformat()` 解析。
- 前端通过 `new Date(isoString)` 解析。

### 4.6 JSON 工具函数

- 使用 `dumps_json()` / `loads_json()` 统一处理 JSON 序列化/反序列化：

  ```python
  from app.database import dumps_json, loads_json

  config = loads_json(row["config_json"], {})
  json_str = dumps_json(config)
  ```

- `dumps_json` 使用 `ensure_ascii=False` + `separators=(",", ":")`，中文不转义。

---

## 5. 文件体量控制

| 文件类型       | 行数上限 | 超出时的处理方式                     |
| -------------- | -------- | ------------------------------------ |
| Python 文件    | 600 行   | 按职责拆分为多个模块（如 services 层拆分） |
| JavaScript 文件 | 500 行   | 按页面或功能拆分到 `pages/` 子目录    |
| styles.css     | 800 行   | 按页面拆分为独立 CSS 文件             |

### 拆分原则

- **不改变接口和 DOM 行为**：拆分前后，API 路由路径不变，前端页面渲染结果不变。
- 保持 `import` / `<script>` 引用的正确性。
- 拆分后更新 `main.py` 中的 `include_router` 或 `index.html` 中的 `<script>` 标签。
- 不把文档修复、样式重构和模块拆分混在同一次变更里。
- 保留历史兼容逻辑，并在变更说明中标注。

---

## 6. 注意事项

### 6.1 文件修改规范

- 修改 Python 文件后运行 `python -m compileall -q app tests` 确认无语法错误。
- 修改 JavaScript 文件后运行 `node --check <文件路径>` 确认无语法错误。
- 修改数据库 Schema 后必须用旧库验证 `ensure_runtime_schema()` 能正确处理。

### 6.2 依赖管理

- 新增 Python 依赖必须在 `requirements.txt` 中注明，并在变更说明中说明新增原因。
- 当前依赖：`fastapi`, `uvicorn[standard]`, `python-snap7`, `pymodbus`, `lightgbm`。
- 训练和推理额外依赖（SciPy 用于互相关分析）属于可选，无 SciPy 时回退到 NumPy 实现。

### 6.3 注释标记规范

- `Px-x` 标记用于标注修复记录（如 `P1-7 修复：推理时复用 FeatureEngineer`），便于追踪变更历史。
- DEPRECATED 标记用于标注已弃用但仍保留兼容的代码路径。
- FIXME/TODO 标记用于标注待处理的技术债，不应在发布前遗留。

---

## 7. 验证命令

### 7.1 Python 语法检查

```powershell
python -m compileall -q app tests
```

### 7.2 JavaScript 语法检查

```powershell
# 使用 Node.js 检查单个文件
node --check static/js/api.js

# 批量检查
Get-ChildItem static/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

### 7.3 单元测试

```powershell
# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试文件
python -m pytest tests/test_recommendation.py -v

# 使用 unittest 运行
python -m unittest discover -s tests -v
```

### 7.4 类型检查（可选）

```powershell
# 使用 mypy 进行静态类型检查（需安装 mypy）
mypy app/ --ignore-missing-imports
```

### 7.5 代码格式化（可选）

```powershell
# 使用 black 格式化 Python 代码（需安装 black）
black app/ tests/

# 使用 ruff 检查代码质量（需安装 ruff）
ruff check app/ tests/
```