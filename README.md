# AI PAC 智能除磷加药平台

本项目是一个本地部署的 PAC 除磷智能加药系统。系统提供 FastAPI 后端、SQLite WAL 数据库、PAC 加药推荐、数据采集、历史趋势、报警、模型训练/投用、S7-1500 PLC 通讯配置和系统访问地址展示。

## 功能范围

- 投加点管理：维护投加点、工艺参数组、采集点来源和 PLC 关联。
- 工艺参数：维护目标 TP、出水 TP 上限、PAC 密度、加药流量上下限、计算周期和单耗配置曲线。
- 单耗曲线：在工艺参数页以折线曲线方式配置关键点，支持新增、删除、拖动和手动输入 X/Y。
- 推荐计算：保守模式按实时出水 TP 查单耗曲线并计算 PAC 加药流量；加药流量预测模型投用后进入正常模式。
- 模型管理：支持下次出水 TP 预测模型和加药流量预测模型，支持参数配置、实时记录训练样本、CSV 导入、训练、下载、投用和停用。
- 模型展示：出水 TP 预测模型投用后只展示预测 TP；加药流量预测模型投用后驱动投加点进入正常模式。
- 数据采集：支持 API/CSV 写入、手动轮询和 S7-1500 PLC 读取采集点。
- 历史数据：展示采集点历史曲线和表格，支持按天数清理。
- 报警事件：记录并确认数据质量、PLC 等报警。
- 节省加药流量：在总览页展示实际加药流量与推荐流量的差值曲线和累计节省量，支持自由选择时间范围。
- 用户管理：支持管理员和普通用户两种角色，未登录为访客。右上角登录/切换/登出。密码使用 PBKDF2-HMAC-SHA256 + 随机 salt 存储，传输使用 session token 机制。
- 系统设置：支持数据库备份、运行设置维护、密码修改，并显示本机外部访问地址。

## 推荐与模型逻辑

### 保守模式

未投用加药流量预测模型时，推荐值按以下逻辑计算：

```text
参考流量 × 单耗曲线(实时出水TP) / PAC密度 / 1000
```

如果关键实时数据异常，系统会保留上一次推荐值并产生数据质量报警。若保守模式下实时出水 TP 高于上限，则直接输出最大加药流量。

### 下次出水 TP 预测模型

- 模型类型：`tp_out_response`
- 输入字段：参考流量、进水 TP、进水 PH、出水 TP、回流流量1、回流流量2、生化池 A 东 ORP1、生化池 A 东 ORP2、生化池 A 西 ORP1、生化池 A 西 ORP2、生化池 MLSS1、生化池 MLSS2。
- 输出字段：下一次出水 TP 检测数据。
- 投用效果：只在总览和推荐解释中展示预测 TP，不直接替代加药流量推荐。

### 加药流量预测模型

- 模型类型：`pac_flow_predict`
- 输入字段：与下次出水 TP 预测模型一致。
- 输出字段：实际加药流量。
- 投用效果：投加点进入正常模式，模型预测的加药流量作为推荐值，并按工艺参数中的最小/最大 L/h 限幅。
- 推理规则：推荐时会把模型输入中的 `TP_OUT` 从当前出水 TP 临时替换为工艺参数的目标 TP，用于估算目标 TP 对应的加药流量。

示例推荐解释：

```text
正常模式：投用加药流量预测模型，将模型输入中的出水TP由当前值 0.196 mg/L 替换为目标TP 0.15 mg/L，预测目标TP对应加药流量 20.28 L/h
```

## 模型训练参数

模型管理页支持配置：

- `target_column`
- `feature_columns`
- `valid_ratio`
- `split_method`
- `objective`
- `metric`（支持多选：rmse / mae / mse）
- `boosting_type`
- `learning_rate`
- `num_boost_round`
- `early_stopping_rounds`
- `num_leaves`
- `max_depth`
- `min_data_in_leaf`
- `min_sum_hessian_in_leaf`
- `max_delta_step`
- `max_bin`
- `min_data_in_bin`
- `bin_construct_sample_cnt`
- `lambda_l1`
- `lambda_l2`
- `min_gain_to_split`
- `path_smooth`
- `linear_lambda`
- `feature_fraction`
- `feature_fraction_bynode`
- `bagging_fraction`
- `bagging_freq`
- `extra_trees`
- `monotone_constraints`
- `seed`、`feature_fraction_seed`、`bagging_seed`、`data_random_seed`、`extra_seed`
- `deterministic`

参数按功能分为 8 组：数据选择、任务与评价参数、树结构复杂度参数、分箱参数、正则化参数、采样参数、单调约束参数、随机性与复现参数。每组可展开或折叠。

参数项支持鼠标悬停查看建议默认值和调整建议。训练样本可手动记录，也可开启实时记录并设置记录周期。

CSV 样本导入支持 `utf-8-sig`、`utf-8`、`gb18030`、`gbk` 编码，时间格式支持：

- `2026/5/20  0:00:00`
- `2026/5/20 0:00`
- `2026/5/20`
- `2026-05-20 00:00:00`
- `2026-05-20T00:00:00`

## 总览页面布局

总览页分为三行区域：

**第一行**：投加点指标卡片，每个卡片显示投加点名称、模式标签、推荐流量(L/h)、参考流量、进水TP、出水TP、预测TP、加药流量。点击卡片切换选中投加点。

**第二行**（三个等宽趋势面板，每个面板右上角支持 3h/6h/12h 时间切换）：

- 出水TP趋势：显示 TP_OUT 和 PREDICT_TP 两条曲线
- 加药流量趋势：显示 PAC_ACTUAL 和 RECOMMEND_PAC 两条曲线
- 节省加药流量：顶部显示累计节省量（正值表示节省、负值表示多消耗），下方显示差值曲线（实际流量-推荐流量），支持自由选择起始和结束时间

**第三行**（三个等宽面板）：

- 推荐解释：展示保守公式→原始建议→限幅后的公式推导链、预测TP文本和推荐理由标签
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
- 模型：LightGBM
- PLC：python-snap7，S7comm/PUT-GET
- 前端：原生 HTML/CSS/JavaScript，无构建步骤

## 项目结构

```text
app/
  main.py                    # FastAPI 入口、生命周期、静态挂载和 router include
  api/
    common.py                # API 通用行转换工具
    health.py                # /api/health、/api/backend/status
    alarms.py                # /api/alarms*
    collection.py            # /api/collection*、历史数据
    dashboard.py             # /api/dashboard
    dosing_points.py         # /api/dosing-points*
    ingest.py                # /api/ingest*、/api/import/csv
    models.py                # /api/models*
    plc.py                   # /api/plc*
    process_groups.py        # /api/process-lines、工艺参数组
    settings.py              # /api/settings、/api/settings/network、/api/backup、导出
    trends.py                # /api/trends
  schemas/
    config.py                # 工艺参数组、设置请求模型
    dosing.py                # 投加点、采集、历史、导入请求模型
    model.py                 # 模型管理请求模型
    plc.py                   # PLC 请求模型
  database.py                # SQLite 连接、schema、运行期兼容和数据库工具
  services/
    audit.py                 # 审计日志写入
    collection_data.py       # 采集质量、采集写入、本地模拟样本刷新
    collection_runtime.py    # 采集轮询、采集点校验
    model_training.py        # 模型样本记录、实时记录、CSV 导入、训练
    recommendation.py        # 推荐计算核心逻辑
    plc.py                   # PLC 连接、地址解析和读值
    plc_devices.py           # PLC 设备运行态、设备列表和事件写入
    seed.py                  # 空项目基础数据初始化
static/
  index.html                 # 单页应用入口
  app.js                     # 兼容性语法检查入口
  js/
    state.js                 # 全局状态管理
    format.js                # 格式化工具函数
    api.js                   # API 请求封装
    boot.js                  # 应用引导、导航渲染
    start.js                 # 应用启动入口
    pages/
      overview.js             # 总览页面
      process.js              # 工艺配置页面
      data.js                 # 数据管理页面
      models.js               # 模型管理页面
      plc.js                  # PLC 设备页面
      alarms-settings.js      # 报警与设置页面
  styles.css                 # 页面样式
tests/
  test_recommendation.py     # 推荐计算、采集、模型样本相关测试
data/
  ai_pac.sqlite              # 运行时数据库，首次启动自动创建
docs/
  CODING_STANDARDS.md        # 代码组织和拆分规范
  API_REFERENCE.md            # 全部 API 接口文档
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

首次启动会自动创建 `data/ai_pac.sqlite` 并初始化数据库 schema。默认只写入运行所需的基础项目骨架，不再生成默认投加点、工艺参数组、模型项目、PLC 设备、采集点、历史样本或报警；这些业务数据需要在页面中手动创建。

## 验证命令

```powershell
python -m unittest -q
python -m compileall -q app tests
node --check static/app.js
Get-ChildItem static/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

如已安装 pytest，也可运行：

```powershell
python -m pytest -q
```

## 常用接口

### 健康检查

```text
GET /api/health
```

### 后端状态

```text
GET /api/backend/status
```

返回数据库路径、表记录数、数据源状态和最新样本。

### 认证

```text
POST /api/auth/login          登录，返回 token
GET  /api/auth/me             获取当前用户（需 X-Token header）
POST /api/auth/logout         退出
PUT  /api/auth/password       修改密码（需 X-Token header）
```

Token 通过 `X-Token` header 携带，前端存入 `localStorage`，有效期 7 天。修改密码后自动清除所有 session。

### 仪表盘数据

```text
GET /api/dashboard
```

返回推荐结果、报警、PLC、模型和数据质量摘要。

### 趋势数据

```text
GET /api/trends?dosing_point_id=1&hours=3
```

返回指定投加点和时间范围内的多组趋势序列。

### 节省加药流量

```text
GET /api/savings?dosing_point_id=1&start=2026-07-02T11:00:00&end=2026-07-02T14:00:00
```

返回累计节省量（L）和差值时间序列。`start`/`end` 为 ISO 时间字符串，默认 end 为当前时间、start 为 end 前 3 小时。差值计算方式为 `实际加药流量 - 推荐流量`，正值表示实际用量大于推荐（多用），负值表示实际用量小于推荐（节省）。积分方式为梯形积分。实际流量与推荐流量的时间匹配采用 120 秒窗口就近匹配。

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
POST /api/models/{model_id}/samples/record
POST /api/models/{model_id}/recording/start
POST /api/models/{model_id}/recording/stop
POST /api/models/{model_id}/samples/import
POST /api/models/{model_id}/train
POST /api/models/{model_id}/deploy
GET  /api/models/{model_id}/artifact
```

### 数据库备份

```text
POST /api/backup
```

备份文件会写入 `backup/`。

## PLC 使用说明

PLC 页面使用 `plc_devices` 和 `plc_device_events` 表保存设备配置和连接事件。

当前支持：

- 协议：`s7_1500`
- 默认端口：`102`
- 默认超时：`5000ms`
- 地址范围：`M`、`DB`、`I`、`Q`
- 数据类型：`REAL`、`BOOL`、`INT`

现场 PLC 侧需要启用 PUT/GET 通讯，并确保 DB 块访问方式、地址规划和采集点配置一致。当前系统只通过采集点配置读取 PLC 数据，不写泵启停、频率、手自动模式、联锁旁路或控制强制值。

## 数据和兼容说明

- `data/ai_pac.sqlite` 是本地运行数据库，不建议提交到版本库。
- `app.database.ensure_runtime_schema()` 包含历史库兼容和补列逻辑，不应随意删除。
- 启动迁移保持非破坏性：旧版 `pac_configs`、`control_configs`、`model_versions`、`model_shadow_results`、`plc_connections`、`plc_tag_mappings`、`plc_write_tests`、`simulation_runs` 等遗留表会保留；旧模型训练样本会补充 `target_value` 并从 `k_ai` 回填，不删除原列或旧表。

## 代码规范和维护

- 分文件编写规范见 [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)。
- 日常维护、发布和排障见 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)。
