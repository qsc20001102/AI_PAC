# 分文件编写规范

本文档定义当前项目的代码组织、单文件体量、拆分边界和命名规范。目标是在不改变业务行为的前提下，让后端、前端和测试逐步拆分到可维护结构。

## 当前文件体量审计

| 文件 | 当前行数约 | 结论 |
| --- | ---: | --- |
| `app/main.py` | 82 | 已收敛为 app 创建、静态文件挂载、生命周期注册和 router include |
| `static/app.js` | 1 | 仅保留兼容性语法检查入口；运行时代码已拆至 `static/js/` |
| `static/js/**/*.js` | 最大约 550 | 已按状态、工具、启动和页面模块拆分 |
| `app/services/recommendation.py` | 708 | 偏大，后续可按数据读取、计算、持久化拆分 |
| `app/database.py` | 626 | 偏大，但包含 schema 和兼容逻辑，拆分风险较高 |
| `app/services/seed.py` | 402 | 可接受，后续可按基础数据、样本、设置拆分 |
| `static/styles.css` | 280 | 可接受 |
| `app/schemas/*.py` | 229 | 已按功能域拆分 |
| `app/api/*.py` | 1892 | 已按业务域拆分，单个路由文件均小于 500 行 |
| `app/services/model_training.py` / `app/services/collection_data.py` / `app/services/collection_runtime.py` / `app/services/plc_devices.py` | 633 | 已按模型训练、采集数据、采集运行态和 PLC 设备运行态拆分 |

## 单文件建议阈值

- 后端路由文件：建议小于 500 行。
- 后端服务文件：建议小于 700 行。
- 前端页面模块：建议小于 600 行。
- 前端工具模块：建议小于 300 行。
- 测试文件：建议小于 500 行，按业务域拆分。

超过阈值时不一定立刻重构，但新增功能不得继续堆到已超阈值文件中。

## 后端拆分目标

建议从 `app/main.py` 逐步拆出以下模块：

```text
app/
  main.py                  # 只保留 app 创建、静态文件挂载、生命周期注册、router include
  schemas/
    config.py              # PAC、控制参数、系统设置请求模型
    dosing.py              # 投加点、采集样本请求模型
    model.py               # 模型管理请求模型
    plc.py                 # PLC 请求模型
  api/
    health.py              # /api/health、/api/backend/status
    dashboard.py           # /api/dashboard
    dosing_points.py       # /api/dosing-points*
    process_groups.py      # 药剂组、工艺参数组
    collection.py          # /api/collection*、/api/history-data*
    ingest.py              # /api/ingest*、/api/import/csv
    alarms.py              # /api/alarms*
    models.py              # /api/models*
    plc.py                 # /api/plc*
    settings.py            # /api/settings、/api/backup、导出接口
    trends.py              # /api/trends
  services/
    recommendation.py      # 推荐计算
    collection_data.py     # 采集质量、采集写入和本地模拟样本刷新
    collection_runtime.py  # 采集轮询、采集点校验和后台模型记录
    model_training.py      # 模型样本、CSV、训练和投用
    plc.py                 # PLC 客户端和地址读写
    plc_devices.py         # PLC 设备运行态、设备列表和事件写入
    seed.py                # 初始化数据
  repositories/
    *.py                   # 当 SQL 重复或跨路由共享时再抽，不提前过度设计
```

拆分顺序建议：

1. 先拆 Pydantic schema，纯类型移动，风险最低。
2. 再拆无后台任务依赖的路由，如 `health`、`alarms`、`settings`。
3. 再拆模型、采集、PLC 等复杂路由。
4. 最后处理生命周期任务和共享 helper。

当前进度：

- 已完成：`schemas/` 请求模型拆分。
- 已完成：`api/health.py`、`api/alarms.py`、`api/settings.py`、`api/process_groups.py` 低耦合路由拆分。
- 已完成：`services/audit.py` 审计写入拆分。
- 已完成：`services/model_training.py` 模型样本、CSV 和训练逻辑拆分。
- 已完成：`services/collection_data.py` 采集质量、采集写入和本地模拟样本刷新拆分。
- 已完成：`api/models.py` 模型管理、样本导入导出、训练、投用和发布路由拆分。
- 已完成：`api/dashboard.py`、`api/dosing_points.py`、`api/plc.py`、`api/collection.py`、`api/ingest.py`、`api/trends.py` 业务路由拆分。
- 已完成：`services/collection_runtime.py`、`services/plc_devices.py` 运行态 helper 拆分。
- 后端待继续：`app/services/recommendation.py` 仍略高于服务文件建议阈值，可在后续按数据读取、计算和持久化继续拆。

## 前端拆分目标

当前前端保持无构建的普通脚本，并在 `index.html` 按依赖顺序引入：

```text
static/js/
  state.js             # 全局 state、常量
  api.js               # api()、错误处理
  format.js            # fmt、dateMinute、htmlEscape 等工具
  boot.js              # 导航渲染、页面切换、刷新和时钟
  pages/
    overview.js
    process.js         # 工艺配置、药剂参数、工艺参数
    data.js
    models.js
    plc.js
    alarms-settings.js
  start.js             # resize 监听和 boot() 启动入口
```

如果未来允许引入构建工具，再考虑 Vite/ES modules；当前规范不要求新增依赖。

## 命名规范

- Python 函数、变量：`snake_case`。
- Python 类和 Pydantic 模型：`PascalCase`。
- JavaScript 函数、变量：`camelCase`。
- 常量：Python 使用 `UPPER_SNAKE_CASE`，JavaScript 使用 `camelCase` 或局部 `const`；跨模块稳定常量可使用 `UPPER_SNAKE_CASE`。
- 数据库字段、接口字段：保持现有命名，不为风格统一而改字段名。
- 路由函数名称应表达业务动作，例如 `create_model_project`、`update_plc_device`。

## 路由层规范

路由函数只做：

- 接收和校验请求。
- 调用服务或数据访问函数。
- 组装兼容现有接口的响应。
- 抛出明确的 `HTTPException`。

路由函数不应包含：

- 长 SQL 拼接和多段业务计算。
- 模型训练细节。
- PLC 协议细节。
- CSV 逐行解析细节。
- 可复用的数据质量判断。

## 服务层规范

服务函数应做到：

- 输入和输出清晰。
- 不直接依赖前端页面状态。
- 不改变接口字段名。
- 复杂计算应有单元测试。
- 与数据库强绑定的逻辑显式接收 `sqlite3.Connection`。

## 数据访问规范

- 不改已有数据库结构，除非有明确迁移计划。
- `ensure_runtime_schema()` 中的兼容补列逻辑视为历史兼容逻辑，不能直接删除。
- SQL 参数必须使用参数化写法，不拼接用户输入。
- 新增表、字段、索引必须同步更新 README、维护文档和测试。

## 前端规范

- 不在渲染函数中重复写 API 错误处理；优先抽工具函数。
- 页面渲染函数只负责当前页面 DOM 和事件绑定。
- 图表绘制逻辑放到图表模块，不散落在页面模块。
- 所有用户输入进入 HTML 前必须 `htmlEscape()`。
- 不改接口路径、请求参数和返回字段。
- 不新增依赖，除非需求明确同意。

## 测试规范

新增或拆分代码后至少运行：

```powershell
python -m unittest -q
python -m compileall -q app tests
node --check static/app.js
Get-ChildItem static/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

涉及推荐计算、模型训练、CSV、PLC 地址解析、历史数据清理时，应补充或移动对应测试。

## 历史兼容逻辑处理原则

如果发现疑似历史兼容逻辑：

- 不直接删除。
- 先在代码注释或维护文档中说明用途。
- 查找数据库字段、前端字段、测试和 README 是否引用。
- 如确需删除，先做一个单独 PR/变更，并给出回滚方案。

## 拆分时禁止事项

- 禁止一次性重命名接口字段。
- 禁止改 URL 路径。
- 禁止改请求参数格式。
- 禁止改返回 JSON 字段。
- 禁止改数据库结构。
- 禁止把不相关重构混入业务修复。
- 禁止为了拆分引入新框架或构建工具。
