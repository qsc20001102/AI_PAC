# 分文件编写规范

本文档定义当前项目的代码组织、单文件体量、拆分边界和命名规范。目标是在不改变业务行为的前提下，让后端、前端和测试保持可维护结构。

## 当前文件体量审计

| 文件 | 当前行数约 | 结论 |
| --- | ---: | --- |
| `app/main.py` | 98 | 已收敛为 app 创建、静态挂载、生命周期注册和 router include |
| `static/app.js` | 1 | 仅保留兼容性语法检查入口；运行时代码已拆至 `static/js/` |
| `static/js/pages/models.js` | 584 | 接近建议上限，后续模型页面新功能应优先拆 helper |
| `app/services/recommendation.py` | 654 | 接近服务文件阈值，后续可按数据读取、模型推理、推荐计算、持久化拆分 |
| `app/services/model_training.py` | 740 | 已超过建议阈值，后续可把 CSV、实时记录、LightGBM 训练拆分 |
| `app/database.py` | 883 | 偏大，但包含 schema 和历史兼容逻辑，拆分风险高 |
| `static/styles.css` | 341 | 可接受，继续增长时按页面分区 |
| `app/api/*.py` | 单文件最大约 439 | 已按业务域拆分，单个路由文件均低于 500 行 |
| `app/schemas/*.py` | 单文件最大约 101 | 已按功能域拆分 |

## 单文件建议阈值

- 后端路由文件：建议小于 500 行。
- 后端服务文件：建议小于 700 行。
- 前端页面模块：建议小于 600 行。
- 前端工具模块：建议小于 300 行。
- 测试文件：建议小于 500 行，按业务域拆分。

超过阈值时不一定立即重构，但新增功能不应继续堆到已超阈值文件中。

## 当前模块边界

```text
app/
  main.py                  # app 创建、静态文件挂载、生命周期注册、router include
  schemas/
    config.py              # 工艺参数组、系统设置请求模型
    dosing.py              # 投加点、采集样本、历史清理请求模型
    model.py               # 模型管理请求模型
    plc.py                 # PLC 请求模型
  api/
    health.py              # /api/health、/api/backend/status
    dashboard.py           # /api/dashboard
    dosing_points.py       # /api/dosing-points*
    process_groups.py      # /api/process-lines、/api/process-parameter-groups*
    collection.py          # /api/collection*、/api/history-data*
    ingest.py              # /api/ingest*、/api/import/csv
    alarms.py              # /api/alarms*
    models.py              # /api/models*
    plc.py                 # /api/plc*
    settings.py            # /api/settings、/api/settings/network、/api/backup、导出接口
    trends.py              # /api/trends
  services/
    recommendation.py      # 推荐计算、模型推理、结果持久化
    collection_data.py     # 采集质量、采集写入、本地模拟样本刷新
    collection_runtime.py  # 采集轮询、采集点校验
    model_training.py      # 模型样本、实时记录、CSV、训练
    plc.py                 # PLC 客户端和地址读取
    plc_devices.py         # PLC 设备运行态、设备列表和事件写入
    audit.py               # 审计日志写入
    seed.py                # 初始化数据
```

后续可在 SQL 重复或跨路由共享明显增多时再引入 repository 层，不提前过度设计。

## 已完成拆分进度

- 已完成：`schemas/` 请求模型拆分。
- 已完成：所有主要业务路由拆到 `app/api/`。
- 已完成：审计、采集数据、采集运行态、模型训练、PLC 设备运行态拆到 `app/services/`。
- 已完成：前端从单一主文件拆为 `static/js/state.js`、`api.js`、`format.js`、`boot.js`、`start.js` 和 `pages/*.js`。
- 待继续：`model_training.py` 可拆出 CSV 导入、实时记录、LightGBM 训练。
- 待继续：`recommendation.py` 可拆出模型推理和持久化。

## 命名规范

- Python 函数、变量：`snake_case`。
- Python 类和 Pydantic 模型：`PascalCase`。
- JavaScript 函数、变量：`camelCase`。
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
- LightGBM 训练细节。
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
- 对历史兼容逻辑加注释或在维护文档中说明。

## 数据访问规范

- 不改已有数据库结构，除非有明确迁移计划。
- `ensure_runtime_schema()` 中的兼容补列逻辑视为历史兼容逻辑，不能直接删除。
- SQL 参数必须使用参数化写法，不拼接用户输入。
- 新增表、字段、索引必须同步更新 README、维护文档和测试。
- 不直接删除旧字段；如果旧字段只为兼容保留，应在文档说明。

## 前端规范

- 页面渲染函数只负责当前页面 DOM 和事件绑定。
- API 错误处理优先复用通用 `api()` 和 toast 逻辑。
- 所有用户输入进入 HTML 前必须 `htmlEscape()`。
- 图表或复杂交互应拆成局部 helper，避免页面函数继续变长。
- 不改接口路径、请求参数和返回字段，除非明确同步后端和文档。
- 不新增构建工具或依赖，除非需求明确同意。
- 静态资源变更后更新 `static/index.html` 中对应 `?v=` 版本，避免浏览器缓存旧脚本。

## 当前关键业务规则

- `tp_out_response` 模型只用于展示下一次出水 TP 预测值，不驱动正常模式。
- `pac_flow_predict` 模型投用后驱动正常模式。
- 加药流量模型推理时用工艺目标 TP 覆盖模型输入中的 `TP_OUT`。
- `prediction_step=0` 表示直接预测当前条数据。
- 模型训练样本支持手动记录、实时记录和 CSV 导入。
- 工艺参数页单耗曲线是曲线编辑器，不再是纯表单。
- 系统启动应监听 `0.0.0.0:8000`，系统设置页展示外部访问地址。

## 测试规范

新增或拆分代码后至少运行：

```powershell
python -m unittest -q
python -m compileall -q app tests
node --check static/app.js
Get-ChildItem static/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

涉及以下内容时应补充或调整测试：

- 推荐计算。
- 模型训练、模型投用和模型推理。
- CSV 导入和时间格式解析。
- 实时训练样本记录。
- PLC 地址解析。
- 历史数据清理。
- 数据库兼容迁移。

前端视觉改动应尽量做浏览器渲染验证；如果本地浏览器插件因策略无法访问 localhost，应在最终说明中明确未截图验证。

## 历史兼容逻辑处理原则

如果发现疑似历史兼容逻辑：

- 不直接删除。
- 先查数据库字段、前端字段、测试和文档是否引用。
- 在代码注释或维护文档中说明用途。
- 如确需删除，先做单独变更，并给出回滚方案。

## 拆分时禁止事项

- 禁止一次性重命名接口字段。
- 禁止改 URL 路径。
- 禁止改请求参数格式。
- 禁止改返回 JSON 字段。
- 禁止破坏数据库兼容。
- 禁止把不相关重构混入业务修复。
- 禁止为了拆分引入新框架或构建工具。
