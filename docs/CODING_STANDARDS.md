# AI PAC 智能除磷加药系统 — 编码规范

> 适用技术栈：FastAPI + SQLite + LightGBM + python-snap7 + 原生 HTML/CSS/JS（ES6+，无构建步骤）

---

## 1. 项目结构规范

```
ai_pac/
├── app/                    # 后端 Python 包
│   ├── api/                # API 路由层（FastAPI APIRouter）
│   │   ├── __init__.py
│   │   ├── alarms.py
│   │   ├── collection.py
│   │   ├── dashboard.py
│   │   ├── dosing_points.py
│   │   ├── health.py
│   │   ├── ingest.py
│   │   ├── models.py
│   │   ├── plc.py
│   │   ├── process_groups.py
│   │   ├── settings.py
│   │   └── trends.py
│   ├── schemas/            # Pydantic 请求/响应模型
│   │   ├── config.py
│   │   ├── dosing.py
│   │   ├── model.py
│   │   └── plc.py
│   ├── services/           # 业务逻辑层（纯函数）
│   │   ├── audit.py
│   │   ├── collection_data.py
│   │   ├── collection_runtime.py
│   │   ├── model_training.py
│   │   ├── plc.py
│   │   ├── plc_devices.py
│   │   ├── recommendation.py
│   │   ├── seed.py
│   │   └── settings_config.py
│   ├── database.py         # Schema 定义、连接管理、迁移
│   └── main.py             # FastAPI 应用入口
│
├── static/                 # 前端静态资源（无构建步骤）
│   ├── js/
│   │   ├── pages/          # 按页面分文件
│   │   │   ├── alarms-settings.js
│   │   │   ├── data.js
│   │   │   ├── models.js
│   │   │   ├── overview.js
│   │   │   ├── plc.js
│   │   │   └── process.js
│   │   ├── state.js        # 全局状态管理
│   │   ├── format.js       # 格式化函数集
│   │   ├── api.js          # 统一 API 请求函数
│   │   ├── boot.js         # 应用启动引导
│   │   └── start.js        # 入口脚本
│   ├── styles.css          # 全局样式（CSS 变量定义在顶部）
│   ├── index.html          # 单页应用入口
│   └── app.js              # 应用主脚本
│
├── tests/                  # 单元测试（unittest 风格）
│   ├── __init__.py
│   └── test_recommendation.py
│
├── data/                   # 运行时数据
│   ├── ai_pac.sqlite      # SQLite 主数据库
│   ├── app.db              # 辅助数据库（如有）
│   ├── server.stderr.log   # 服务器标准错误日志
│   └── server.stdout.log  # 服务器标准输出日志
│
├── docs/                   # 项目文档
├── run_server.py           # 服务器启动脚本
└── requirements.txt        # Python 依赖清单
```

### 分层职责

| 层          | 职责                           | 依赖方向         |
| ----------- | ------------------------------ | ---------------- |
| `api/`      | 请求校验、参数转换、调用服务、返回响应 | 可调用 `services/` |
| `schemas/`  | Pydantic 模型定义              | 无业务依赖       |
| `services/` | 纯业务逻辑、数据库读写         | 可调用 `database` |
| `database`  | 连接管理、Schema、迁移         | 无上层依赖       |

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

### 2.4 API 路由

- 每个业务模块一个文件，使用 `APIRouter`，前缀统一：

  ```python
  from fastapi import APIRouter

  router = APIRouter(prefix="/api/v1/models", tags=["models"])
  ```

- 在 `main.py` 中通过 `app.include_router(router)` 注册。

### 2.5 服务层

- **纯函数风格**：函数接收 `con: sqlite3.Connection` 作为参数，不存储连接。
- 不在服务层定义类来持有状态；使用普通模块级函数或简单的数据容器。
- 服务函数应做到可独立测试（传入 mock 连接即可）。

### 2.6 错误处理

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

- 不在 API 层做业务判断型的异常区分；业务规则异常由服务层抛出自定义异常，API 层捕获转换。

### 2.7 命名约定

| 类别     | 风格             | 示例                    |
| -------- | ---------------- | ----------------------- |
| 函数/方法 | `snake_case`     | `get_recommendation`   |
| 变量     | `snake_case`     | `current_tp`            |
| 常量     | `UPPER_SNAKE_CASE` | `DB_PATH`, `SCHEMA`   |
| 类       | `PascalCase`     | `DosingPointConfig`     |
| APIRouter 变量 | `router`     | `router = APIRouter()` |

---

## 3. 前端规范

### 3.1 基本要求

- 无构建步骤，原生 ES6+ 语法。
- 不引入 React / Vue / TypeScript，不使用 npm 构建流程。

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
  const data = await api("/api/v1/overview");
  ```

- `api()` 内部处理 JSON 序列化、错误提取和异常抛出，页面代码无需重复处理。

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
  - 状态标签颜色映射
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
    --radius-sm: 4px;
    /* ... */
  }
  ```

- 样式类命名使用 BEM 风格或语义化连字符命名（如 `.panel-title`、`.alarm-meta`）。

### 3.8 图表

- Canvas 图表使用原生 Canvas 2D API 手绘，**不引入**第三方图表库（如 ECharts、Chart.js）。
- 图表辅助函数（tooltip 绑定、图例渲染等）在页面文件内定义。

---

## 4. 数据库规范

### 4.1 Schema 管理

- 所有建表 DDL 集中在 `app/database.py` 的 `SCHEMA` 常量中。
- 使用 `CREATE TABLE IF NOT EXISTS`，保证幂等执行。

### 4.2 运行期兼容

- 通过 `ensure_runtime_schema(con)` 函数处理运行期 Schema 变更。
- 该函数负责：补列（`ALTER TABLE ADD COLUMN IF NOT EXISTS`）、补索引、回填默认值。

### 4.3 禁止操作

- **禁止直接删表**（`DROP TABLE`），避免运行期数据丢失。
- **禁止修改已有列的类型**（SQLite 不支持原生 `ALTER COLUMN`）。
- 只允许：补列、补索引、补表、回填数据。

### 4.4 WAL 模式

- 数据库连接启用 WAL 模式，减少读写互斥：

  ```python
  con.execute("PRAGMA journal_mode = WAL")
  con.execute("PRAGMA synchronous = NORMAL")
  con.execute("PRAGMA foreign_keys = ON")
  ```

### 4.5 时间格式

- `sample_time` 列使用 **ISO 8601 字符串**存储（如 `"2026-07-02T14:30:00"`）。
- Python 端通过 `datetime.isoformat()` 写入，读取时用 `datetime.fromisoformat()` 解析。
- 前端通过 `new Date(isoString)` 解析。

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

---

## 6. 验证命令

### 6.1 Python 语法检查

```bash
# 检查单个文件
python -m py_compile app/api/alarms.py

# 批量检查 app/ 目录下所有 .py 文件
python -m compileall app/
```

### 6.2 JavaScript 语法检查

```bash
# 使用 Node.js 检查单个文件（无需安装额外依赖）
node --check static/js/api.js

# 批量检查 static/js/ 目录
for %%f in (static\js\*.js static\js\pages\*.js) do node --check %%f
```

### 6.3 单元测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试文件
python -m pytest tests/test_recommendation.py -v

# 使用 unittest 运行
python -m unittest discover -s tests -v
```

### 6.4 类型检查（可选）

```bash
# 使用 mypy 进行静态类型检查（需安装 mypy）
mypy app/ --ignore-missing-imports
```

### 6.5 代码格式化（可选）

```bash
# 使用 black 格式化 Python 代码（需安装 black）
black app/ tests/

# 使用 ruff 检查代码质量（需安装 ruff）
ruff check app/ tests/
```
