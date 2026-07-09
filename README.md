# AI PAC 智能除磷加药平台

本项目是一个本地部署的 PAC 除磷智能加药系统。系统提供 FastAPI 后端、SQLite WAL 数据库、PAC 加药推荐、数据采集、历史趋势、报警、模型训练/投用、S7-1500/Modbus TCP PLC 通讯配置和系统访问地址展示。

## 功能范围

- **投加点管理**：维护投加点、工艺参数组、采集点来源和 PLC 关联。
- **工艺参数**：维护目标 TP、出水 TP 上限、PAC 密度、加药流量上下限、计算周期、单耗配置曲线、TP 预测系数和 PAC 流量系数。
- **单耗曲线**：在工艺参数页以折线曲线方式配置关键点，支持新增、删除、拖动和手动输入 X/Y。
- **推荐计算**：保守模式按实时出水 TP 查单耗曲线计算 PAC 加药流量；双任务 AI 模型投用后进入智能模式，模型输出 PAC 加药量预测 + 下次出水 TP 预测。
- **模型管理**：支持双任务模型（`ai_pac_dual_task`），同时预测 PAC 加药量和出水 TP 变化量；支持参数配置、实时记录训练样本、CSV 导入、训练、下载、投用和停用。旧单任务模型（`tp_out_response`、`pac_flow_predict`）已标记 DEPRECATED，保留兼容。
- **虚拟采集点**：推荐计算完成后，将预测出水 TP 和推荐 PAC 加药量写入虚拟采集点，趋势图可像普通传感器一样查询。
- **数据采集**：支持 API/CSV 写入、手动轮询和 S7-1500/Modbus TCP PLC 读取采集点，后台异步采集循环 1 秒轮询。
- **历史数据**：展示采集点历史曲线和表格，支持按天数清理。
- **报警事件**：记录并确认数据质量、PLC 等报警，条件恢复时自动清除。
- **节省加药流量**：在总览页展示实际加药流量与推荐流量的差值曲线和累计节省量，支持自由选择时间范围。
- **用户管理**：支持管理员和普通用户两种角色，未登录为访客。右上角登录/切换/登出。密码使用 PBKDF2-HMAC-SHA256 + 随机 salt 存储，传输使用 session token 机制。
- **系统设置**：支持数据库备份、运行设置维护、密码修改、PLC 自动重连配置，并显示本机外部访问地址。

## 推荐与模型逻辑

### 保守模式

未投用双任务 AI 模型时，推荐值按以下逻辑计算：

```text
参考流量 × 单耗曲线(实时出水TP) / PAC密度 / 1000
```

其中单耗曲线是用户在工艺参数页配置的分段线性函数（至少 2 个关键点），通过线性插值获取对应出水 TP 下的单位加药量。参考流量 = 进水流量 × `in_flow_weight`。

如果关键实时数据异常，系统会保留上一次推荐值并产生数据质量报警。若保守模式下实时出水 TP 高于上限，则直接输出最大加药流量。

### 双任务 AI 模型（当前主流模型）

- **模型类型**：`ai_pac_dual_task`（当前唯一支持的模型类型）
- **任务 1（PAC 加药量预测）**：目标 = `pac_dosage`，约 97 个特征
- **任务 2（出水 TP 变化量预测）**：目标 = `tp_delta`（未来 TP - 当前 TP），约 84 个特征
- **输出字段**：PAC 加药量（L/h）+ 下次出水 TP 预测（mg/L）
- **输入字段（13 个过程变量）**：进水流量、进水 TP、进水 PH、出水 TP、回流流量 1、回流流量 2、生化池 ORP 1~4、生化池 MLSS 1~2、PAC 加药流量
- **投用效果**：双任务模型预测的 PAC 加药量作为推荐值，按工艺参数中的最小/最大 L/h 限幅；同时展示预测的下次出水 TP。

**推理要求**：需要最近 72 小时、至少 36 条有效历史数据（所有 13 个过程变量）。

**标签构建**（任务 2）：
- 固定延迟模式（`fixed_hrt`）：用户指定 HRT（水力停留时间），`lag_rows = hrt_minutes / sample_interval_minutes`
- 自适应推断模式（`auto_detected`）：用 PAC 变化量与 TP 变化量的互相关分析自动推断最佳对齐 lag（候选范围 30~360 分钟）

### 推荐流程优先级

```
1. 检查双任务 AI 模型 → 推理成功 → mode=dual_task_ai
2. 回退保守模式 → mode=conservative
3. 实时出水TP高于上限且为保守模式 → 直接输出最大加药量
```

### 虚拟采集点

推荐计算完成后自动写入两个虚拟采集点：
- `PREDICT_TP`：预测出水 TP，写入 `sensor_samples`
- `RECOMMEND_PAC`：推荐 PAC 加药流量，写入 `sensor_samples`

趋势 API 可像查询普通传感器一样查询虚拟采集点数据。

## 模型训练参数（双任务模型）

模型管理页支持配置两类训练参数：

**任务 1（PAC 预测）**：num_leaves(63), max_depth(8), min_data_in_leaf(50), learning_rate(0.05), feature_fraction(0.8), bagging_fraction(0.8), bagging_freq(5), lambda_l1(0.1), lambda_l2(1.0), num_boost_round(2000), early_stopping_rounds(100)

**任务 2（TP 变化预测）**：num_leaves(31), max_depth(6), min_data_in_leaf(80), learning_rate(0.05), feature_fraction(0.7), bagging_fraction(0.7), bagging_freq(5), lambda_l1(0.5), lambda_l2(2.0), num_boost_round(2000), early_stopping_rounds(150)

任务 2 使用更小的树和更强的正则化，因为 TP 变化量预测更困难。

**共享配置**：train_ratio(0.7), val_ratio(0.15), seed(42), sample_interval_minutes(5), HRT 模式(fixed_hrt 或 auto_detected)

**参数分组**：参数按功能分为 8 组——数据切分、任务与评价参数、树结构复杂度参数、分箱参数、正则化参数、采样参数、单调约束参数、随机性与复现参数。每组可展开或折叠。

**特征工程**：自动构建时间特征、交互特征（TP 负荷、ORP 均值/差值、MLSS 均值/差值、回流总量）、滞后特征（lag 1/2/3/6/12/18/24）、滑动窗口统计特征（窗口 3/6/12/36/72 的均值/标准差/最大/最小）、差分特征（diff 1/3/6/12）、PAC 有效剂量特征（EWMA, tau=60/120/180/240 分钟）。

## 总览页面布局

总览页分为三行区域：

**第一行**：投加点指标卡片，每个卡片显示投加点名称、模式标签、推荐流量(L/h)、参考流量、进水TP、出水TP、预测TP、加药流量。点击卡片切换选中投加点。

**第二行**（三个等宽趋势面板，每个面板右上角支持 3h/6h/12h 时间切换）：
- 出水TP趋势：显示 TP_OUT（实线）和 PREDICT_TP（虚线）两条曲线
- 加药流量趋势：显示 PAC_ACTUAL（实线）和 RECOMMEND_PAC（虚线）两条曲线
- 节省加药流量：顶部显示累计节省量（正值表示节省、负值表示多消耗），下方显示差值曲线（实际流量-推荐流量），支持自由选择起始和结束时间

**第三行**（三个等宽面板）：
- 推荐解释：展示保守公式→原始建议→限幅后的公式推导链、预测TP文本和推荐理由标签（最多6条）
- 报警事件：活动报警列表，支持全部确认
- PLC通讯：设备在线摘要和设备列表（名称、协议、IP、状态）

**右上角**：登录/用户信息区域，显示当前用户名和角色标签，未登录时显示登录按钮。

## 权限说明

| 角色 | 可见页面 | 编辑权限 |
|------|---------|---------|
| 管理员（admin） | 全部页面 | 全部操作 |
| 普通用户（user） | 总览、工艺参数、历史数据、PLC通讯、报警事件、系统设置 | 可编辑 |
| 访客（guest，未登录） | 总览、工艺参数、历史数据、PLC通讯、报警事件、系统设置 | 只读（按钮隐藏、输入禁用） |

内置用户：
- 管理员：`emen` / `emen@1234`
- 普通用户：`uesr` / `123456`

## 技术栈

- 后端：FastAPI
- 数据库：SQLite，启用 WAL
- 模型：LightGBM（双任务模型）
- PLC：python-snap7（S7-1500）、pymodbus（Modbus TCP）
- 前端：原生 HTML/CSS/JavaScript（ES6+），无构建步骤，Canvas 2D 手绘图表

## 项目结构

```text
app/
  main.py                    # FastAPI 入口、lifespan、静态挂载、router include
  database.py                # SQLite 连接管理、Schema 定义、运行期迁移、工具函数
  api/
    __init__.py
    common.py                # row_to_dict 工具（_json 后缀字段自动解析）
    health.py                # /api/health、/api/backend/status
    auth.py                  # /api/auth/login/me/logout/password
    alarms.py                # /api/alarms*
    collection.py            # /api/collection*、/api/samples*、/api/history-data*
    dashboard.py             # /api/dashboard（带 60 秒 TTL 缓存）
    dosing_points.py         # /api/dosing-points* + 虚拟采集点标签创建
    ingest.py                # /api/ingest/samples、/api/import/csv、/api/collector/demo-poll
    models.py                # /api/models*（含双任务模型配置、CSV 导入/导出、训练/部署）
    plc.py                   # /api/plc*（设备 CRUD + 连接/断开）
    process_groups.py        # /api/process-lines、/api/process-parameter-groups*
    settings.py              # /api/settings*、/api/backup、/api/export/recommendations.csv
    trends.py                # /api/trends、/api/savings
  schemas/
    __init__.py              # 所有 Pydantic 模型统一导出
    config.py                # 工艺参数组、设置更新、单耗曲线点
    dosing.py                # 投加点 CRUD、采集标签、样本导入
    model.py                 # 模型项目 CRUD、样本导入、部署
    plc.py                   # PLC 设备 CRUD
  services/
    __init__.py
    audit.py                 # 审计日志写入
    auth.py                  # 用户认证、密码哈希、token 管理
    collection_data.py       # 采集质量判断、数据写入、模拟数据生成、数据质量统计
    collection_runtime.py    # 采集循环调度（1 秒轮询）、PLC 读取、历史写入
    feature_schema.py        # 特征模式唯一数据源：13 个过程变量的映射（Single Source of Truth）
    model_training.py        # 模型样本记录、实时记录、CSV 导入、双任务模型训练
    plc.py                   # PLC 协议层：S7-1500（snap7）+ Modbus TCP（pymodbus）
    plc_devices.py           # PLC 设备运行态管理、自动重连、事件写入
    recommendation.py        # 推荐计算核心：保守公式、双任务模型推理、二分搜索反向优化、持久化
    seed.py                  # 空项目基础数据初始化
    settings_config.py        # 系统设置读取/写入
    wwtp_ai_engine.py        # 污水处理 AI 引擎：DataImporter + FeatureEngineer + ModelTrainer + InferencePipeline
static/
  index.html                 # 单页应用入口
  js/
    state.js                 # 全局状态管理（activePage, selectedPointId, trendHours 等）
    format.js                # 格式化工具函数（数值、日期、状态标签、htmlEscape）
    api.js                   # 统一 API 请求封装（自动携带 X-Token）
    boot.js                  # 应用引导、导航渲染、路由分发
    start.js                 # 应用启动入口
    pages/
      overview.js             # 总览页面（推荐卡片、趋势图、推荐解释、节省加药、报警）
      process.js              # 工艺配置页面（投加点、工艺参数组、单耗曲线编辑器）
      data.js                 # 数据管理页面（采集点、历史曲线/表格、数据清理）
      models.js               # 模型管理页面（双任务配置、样本导入/导出、训练/部署）
      plc.js                  # PLC 设备页面（设备列表、连接/断开、事件记录）
      alarms-settings.js      # 报警与系统设置页面（告警确认、密码修改、备份）
  styles.css                 # 全局样式（CSS 变量在 :root 中统一定义）
tests/
  test_recommendation.py     # 推荐计算、采集、模型样本相关测试
data/
  ai_pac.sqlite              # 运行时数据库，首次启动自动创建
docs/
  CODING_STANDARDS.md        # 代码组织和拆分规范
  API_REFERENCE.md           # 全部 API 接口文档
  MAINTENANCE.md             # 运维、发布、排障和回归测试文档
```

## 快速启动

```powershell
pip install -r requirements.txt
python run_server.py
```

默认端口为 8000，访问：

```text
http://<本机IP>:8000/
```

也可以在本机使用：

```text
http://127.0.0.1:8000/
```

系统设置页会显示当前检测到的外部访问地址，并可配置项目监听端口。修改端口后需要停止当前服务，再使用 `python run_server.py` 重启才会生效；若局域网设备无法访问，请检查 Windows 防火墙是否放行对应 TCP 端口。如果已在系统设置中修改端口，请把以上地址中的 `8000` 替换为配置端口。

也可以手动指定端口启动：

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

首次启动会自动创建 `data/ai_pac.sqlite` 并初始化数据库 schema。默认只写入运行所需的基础项目骨架（工厂、生产线），不再生成默认投加点、工艺参数组、模型项目、PLC 设备、采集点、历史样本或报警；这些业务数据需要在页面中手动创建。

## 验证命令

```powershell
# Python 语法检查
python -m compileall -q app tests

# 单元测试
python -m unittest -q
python -m pytest -q

# JavaScript 语法检查
node --check static/app.js
Get-ChildItem static/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

## 常用接口

### 健康检查

```text
GET /api/health
```

返回 `{"ok": true, "journal_mode": "wal", "dosing_points": N, "time": "..."}`

### 后端状态

```text
GET /api/backend/status
```

返回数据库文件名、表记录数、数据源状态和最新样本（不返回服务器文件系统绝对路径）。

### 认证

```text
POST /api/auth/login          登录，返回 token
GET  /api/auth/me             获取当前用户（需 X-Token header）
POST /api/auth/logout         退出
PUT  /api/auth/password       修改密码（需 X-Token header）
```

Token 通过 `X-Token` header 携带，前端存入 `localStorage`，有效期 7 天。修改密码后自动清除该用户所有 session。

### 仪表盘数据

```text
GET /api/dashboard
```

返回推荐结果（60 秒 TTL 缓存）、报警（最多 8 条）、PLC 状态、模型摘要和数据质量。

### 趋势数据

```text
GET /api/trends?dosing_point_id=1&hours=3
```

返回指定投加点和时间范围内的多组趋势序列，包括：过程变量系列、PAC_SUGGEST（推荐历史）、PREDICT_TP（预测出水TP）、RECOMMEND_PAC（推荐加药流量）。

### 节省加药流量

```text
GET /api/savings?dosing_point_id=1&start=2026-07-02T11:00:00&end=2026-07-02T14:00:00
```

返回累计节省量（L）和差值时间序列。差值 = 实际流量 - 推荐流量，正值表示多用，负值表示节省。梯形积分，120 秒窗口就近匹配。

### 系统访问地址

```text
GET /api/settings/network
```

返回监听地址、端口、本机 IPv4 地址列表和推荐启动命令。

### 外部采集写入

```powershell
$body = @{
  source_name = "外部采集 API"
  recalculate = $true
  samples = @(
    @{ tag_code = "PAC1_Q"; value = 1235; sample_time = "2026-06-25T10:00:00"; quality = "good"; source = "s7comm" },
    @{ tag_code = "PAC1_TP_OUT"; value = 0.18; sample_time = "2026-06-25T10:00:00"; quality = "good"; source = "s7comm" }
  )
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Method Post `
  -Uri http://<本机IP>:<系统配置端口>/api/ingest/samples `
  -Body $body `
  -ContentType "application/json"
```

### CSV 导入历史样本

```text
POST /api/import/csv

tag_code,value,sample_time,quality,source
PAC1_Q,1235,2026-06-25T10:00:00,good,s7comm
PAC1_TP_OUT,0.18,2026-06-25T10:00:00,good,s7comm
```

### 模型样本与训练

```text
POST /api/models/{model_id}/samples/record          手动记录当前实时样本
POST /api/models/{model_id}/recording/start          开启实时记录
POST /api/models/{model_id}/recording/stop           停止实时记录
POST /api/models/{model_id}/samples/import           CSV 批量导入样本
POST /api/models/{model_id}/train                    触发训练
POST /api/models/{model_id}/deploy                   投用/停用模型
GET  /api/models/{model_id}/artifact                 下载模型 artifact JSON
```

### 数据库备份

```text
POST /api/backup
```

备份文件会写入 `backup/` 目录，文件名格式为 `ai_pac_YYYYMMDD_HHMMSS.sqlite`。

## PLC 使用说明

PLC 页面使用 `plc_devices` 和 `plc_device_events` 表保存设备配置和连接事件。

当前支持：

- 协议：`s7_1500`（python-snap7）、`modbus_tcp`（pymodbus）
- 默认端口：102（S7）/ 502（Modbus）
- 默认超时：5000ms
- S7 地址范围：`M`、`DB`、`I`、`Q`
- Modbus 地址格式：标准 5 位地址（40001/30001）或简写前缀（H/I/C/D）
- 数据类型：`REAL`、`BOOL`、`INT`、`DINT`、`UINT`
- 字节序：`ABCD`（大端）、`DCBA`（小端）、`BADC`、`CDAB`

现场 PLC 侧需要启用 PUT/GET 通讯（S7）或启用 Modbus TCP Server，并确保地址规划和采集点配置一致。当前系统只通过采集点配置读取 PLC 数据，不写泵启停、频率、手自动模式、联锁旁路或控制强制值。

## 数据和兼容说明

- `data/ai_pac.sqlite` 是本地运行数据库，不建议提交到版本库。
- `app.database.ensure_runtime_schema()` 包含历史库兼容和补列逻辑，不应随意删除。
- 启动迁移保持非破坏性：旧版 `pac_configs`、`control_configs`、`model_versions`、`model_shadow_results`、`plc_connections`、`plc_tag_mappings`、`plc_write_tests`、`simulation_runs` 等遗留表会保留；旧模型训练样本会补充 `target_value` 并从 `k_ai` 回填，不删除原列或旧表。
- 时间处理：项目固定在北京时区（`datetime.now()`），不使用 UTC。此前 P0-1/P1-1 改为 UTC 导致前端显示偏移 8 小时，已回退。
- 数据库启用 WAL 模式，减少读写互斥，文件级别备份前需停止服务。
- SQLite WAL 运行时可能产生 `-wal` 和 `-shm` 文件，属正常现象。

## 代码规范和维护

- 分文件编写规范见 [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)。
- 日常维护、发布和排障见 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)。
- 全部 API 接口文档见 [docs/API_REFERENCE.md](docs/API_REFERENCE.md)。