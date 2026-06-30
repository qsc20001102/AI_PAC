# AI PAC 智能除磷加药平台

本项目是一个本地部署的 PAC 除磷智能加药 MVP。系统提供 FastAPI 后端、SQLite WAL 数据库、PAC 推荐计算、数据采集、人工录入、历史趋势、报警、模型训练/投用以及 S7-1500 PLC 通讯配置。

## 功能范围

- 投加点管理：维护投加点、药剂组、工艺参数组和采集点来源；正磷酸盐与进水 TP 作为同级磷计算方式二选一。
- 推荐计算：根据流量、磷数据、反馈窗口和 AI 修正系数输出 PAC 建议加药量。
- 数据采集：支持 API/CSV 写入，也支持 S7-1500 PLC 读取采集点。
- 历史数据：展示采集点历史曲线和表格，支持历史清理。
- 报警事件：记录并确认数据质量、化学品、PLC 等报警。
- 模型管理：记录训练样本、导入 CSV、训练 LightGBM 模型并按投加点投用。
- 系统维护：支持数据库备份、运行状态查看和基础设置维护。

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
    common.py                # API 层通用行转换工具
    health.py                # /api/health、/api/backend/status
    alarms.py                # /api/alarms*
    collection.py            # /api/collection*、样本历史、历史数据清理
    dashboard.py             # /api/dashboard
    dosing_points.py         # /api/dosing-points*
    ingest.py                # /api/ingest*、CSV 导入、人工样本
    models.py                # /api/models*
    plc.py                   # /api/plc*
    process_groups.py        # /api/process-lines、药剂组、工艺参数组
    settings.py              # /api/settings、/api/backup、推荐导出
    trends.py                # /api/trends
  schemas/
    config.py                # PAC、控制参数、药剂组、工艺参数组、设置请求模型
    dosing.py                # 投加点、采集、历史、导入请求模型
    model.py                 # 模型管理请求模型
    plc.py                   # PLC 请求模型
  database.py                # SQLite 连接、schema、运行期兼容和数据库工具
  services/
    audit.py                 # 审计日志写入
    collection_data.py       # 采集质量、手动/接口写入、本地模拟样本刷新
    collection_runtime.py    # 采集轮询、采集点校验和后台模型记录
    model_training.py        # 模型样本记录、CSV 导入、模型训练
    recommendation.py        # 推荐计算核心逻辑
    plc.py                   # PLC 连接、地址解析和读值
    plc_devices.py           # PLC 设备运行态、设备列表和事件写入
    seed.py                  # 演示数据初始化
static/
  index.html                 # 单页应用入口
  app.js                     # 兼容性语法检查入口
  js/                        # 无构建前端脚本，按状态、工具、页面和启动拆分
  styles.css                 # 页面样式
tests/
  test_recommendation.py     # 推荐计算、采集、模型样本相关测试
data/
  ai_pac.sqlite              # 运行时数据库，首次启动自动创建
logs/
  *.log                      # 本地运行日志
docs/
  CODING_STANDARDS.md        # 分文件编写规范和代码组织标准
  MAINTENANCE.md             # 维护、发布、排障和测试文档
```

## 快速启动

```powershell
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000/
```

首次启动会自动创建 `data/ai_pac.sqlite`，初始化数据库 schema，并写入一套演示水厂、投加点、采集点、历史样本、报警和模型数据。

## 验证命令

```powershell
python -m unittest -q
python -m compileall -q app tests
node --check static/app.js
Get-ChildItem static/js -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

如果安装了 pytest，也可以运行：

```powershell
python -m pytest -q
```

当前环境中 FastAPI `TestClient` 需要额外的 `httpx2` 包；除非团队确认新增依赖，否则不要为了测试临时写入 `requirements.txt`。

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

### 仪表盘数据

```text
GET /api/dashboard
```

返回推荐结果、报警、PLC、模型和数据质量摘要。

### 外部采集写入

```powershell
$body = @{
  source_name = "外部采集 API"
  recalculate = $true
  samples = @(
    @{ tag_code = "PAC1_Q"; value = 1235; sample_time = "2026-06-25T10:00:00"; quality = "good"; source = "s7comm" },
    @{ tag_code = "PAC1_PO4_P"; value = 0.32; sample_time = "2026-06-25T10:00:00"; quality = "good"; source = "s7comm" }
  )
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/ingest/samples `
  -Body $body `
  -ContentType "application/json"
```

### CSV 导入历史样本

```text
POST /api/import/csv

tag_code,value,sample_time,quality,source
PAC1_Q,1235,2026-06-25T10:00:00,good,s7comm
PAC1_PO4_P,0.32,2026-06-25T10:00:00,good,s7comm
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

现场 PLC 侧需要启用 PUT/GET 通讯，并确保 DB 块访问方式、地址规划和采集点配置一致。当前系统只写入模拟写入测试记录，不写泵启停、频率、手自动模式、联锁旁路或控制强制值。

## 数据和兼容说明

- `data/ai_pac.sqlite` 是本地运行数据库，不建议提交到版本库。
- `app.database.ensure_runtime_schema()` 包含历史库兼容和补列逻辑，不能随意删除。
- 文案、接口字段、数据库字段可能已有现场或演示数据依赖，修改前应先查调用面。
- 如果不需要内置演示刷新，可在系统设置中将 `demo_live_refresh` 改为 `false`。

## 代码规范和维护

- 分文件编写规范见 [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)。
- 日常维护、发布和排障见 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)。
- 当前后端入口和前端主脚本已按业务域拆分；后续新增功能应继续放入对应 `app/api/`、`app/services/` 或 `static/js/pages/` 模块，避免回填到聚合入口。
