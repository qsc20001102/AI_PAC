# 维护文档

本文档面向日常开发、部署、回归测试和现场排障。

## 日常开发流程

1. 修改前先确认改动范围。
2. 涉及接口时先记录接口路径、请求字段和返回字段。
3. 小步修改，避免同时改后端、前端、数据库和文案。
4. 修改后运行验证命令。
5. 记录需要现场重点测试的页面或接口。

基础验证：

```powershell
python -m unittest -q
python -m compileall -q app tests
node --check static/app.js
```

启动服务：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

访问：

```text
http://127.0.0.1:8000/
```

## 发布前检查清单

- `requirements.txt` 是否有变更；若有，必须说明新增依赖原因。
- API 路径是否保持兼容。
- 请求参数是否保持兼容。
- 返回字段是否保持兼容。
- 数据库结构是否保持兼容。
- `ensure_runtime_schema()` 是否仍能处理旧数据库。
- 前端核心页面是否能打开并刷新。
- PLC 连接失败时是否有可读错误信息。
- 模型训练、CSV 导入、样本删除是否可用。
- `POST /api/backup` 是否能成功生成备份文件。

## 重点页面回归

- 总览：推荐卡片、推荐解释、报警、PLC 摘要、模型摘要、数据质量。
- 工艺配置：投加点新增、编辑、删除，采集来源绑定。
- 工艺参数：参数组新增、编辑、删除。
- 药剂参数：药剂组新增、编辑、删除。
- 数据采集：公共采集点、投加点采集点、PLC 地址配置、手动轮询。
- 历史数据：采集点选择、曲线、表格、历史清理。
- 模型管理：新建模型、记录样本、CSV 导入、训练、投用、停用、导出。
- PLC 通讯：新增设备、编辑设备、连接、断开、事件记录。
- 报警事件：单条确认、全部确认。
- 系统设置：设置保存、数据库备份。

## 常用运维接口

健康检查：

```text
GET /api/health
```

后端状态：

```text
GET /api/backend/status
```

数据库备份：

```text
POST /api/backup
```

采集手动轮询：

```text
POST /api/collection/poll
```

历史清理：

```text
POST /api/history-data/purge
```

## 数据库维护

默认数据库：

```text
data/ai_pac.sqlite
```

备份目录：

```text
backup/
```

注意事项：

- 生产或现场数据操作前先调用 `POST /api/backup`。
- 不要直接删除 `data/ai_pac.sqlite`，除非确认只需要重建演示数据。
- `data/ai_pac.db`、日志文件和旧数据库文件可能是历史遗留，处理前先确认运行配置实际使用的是 `DB_PATH`。
- SQLite WAL 运行时可能产生 `-wal` 和 `-shm` 文件，停止服务后再做文件级备份更稳妥。

## PLC 排障

检查顺序：

1. PLC 页面确认设备 `enabled`。
2. 确认 IP、端口、Rack、Slot。
3. 确认现场 PLC 启用 PUT/GET。
4. 确认网络能访问 PLC 的 102 端口。
5. 确认采集点地址格式，如 `M1.0`、`DB2.1186.0`、`I0.0`、`Q4.0`。
6. 确认数据类型为 `REAL`、`BOOL` 或 `INT`。
7. 查看 PLC 事件表和页面错误信息。

常见现象：

- `python-snap7` 不可用：确认依赖安装和运行环境。
- 连接失败：优先查网络、PUT/GET、Rack/Slot。
- 读取失败：优先查地址、DB 块权限、数据类型。
- 数据质量超时：确认采集周期、历史存储周期和后台采集任务是否运行。

## 模型维护

模型训练依赖 `model_training_samples` 和 `model_projects`。

建议流程：

1. 创建模型项目并选择投加点。
2. 记录实时样本或导入 CSV 样本。
3. 检查样本数量和 K_AI 标签。
4. 训练模型。
5. 检查指标。
6. 投用模型。
7. 观察总览推荐结果和报警。

注意事项：

- 少于 2 条有效 K_AI 样本无法训练。
- CSV 导入支持 `utf-8-sig`、`utf-8`、`gb18030`、`gbk`。
- 投用同一投加点的新模型会将旧投用模型置为 ready。
- 训练失败时不要清空样本，先检查字段映射和标签。

## 历史数据维护

历史数据主要在 `sensor_samples`。

清理策略：

- 使用页面或 `POST /api/history-data/purge` 清理。
- 不建议直接 SQL 删除，避免误删当前诊断所需样本。
- 清理前执行备份。

## 日志和审计

项目会写入：

- `logs/` 下的服务日志。
- `data/server.stdout.log` 和 `data/server.stderr.log` 等本地运行日志。
- 数据库 `audit_logs` 表中的用户操作审计。
- 数据库 `plc_device_events` 表中的 PLC 连接事件。

排障时优先看：

1. 页面 toast 或接口返回错误。
2. `GET /api/backend/status`。
3. `plc_device_events`。
4. 服务日志。
5. `audit_logs`。

## 文件过大处理计划

当前必须重点关注：

- `app/main.py`：仍超过合理体量；已拆出 `schemas/`、`api/health.py`、`api/alarms.py`、`api/settings.py`、`api/process_groups.py`、`services/audit.py`、`services/model_training.py` 和 `services/collection_data.py`，应继续拆为更多 `api/` 与 `services/` 模块。
- `static/app.js`：已超过合理体量，应逐步拆为 `static/js/` 下的状态、API、格式化、图表和页面模块。

建议拆分原则：

- 每次只拆一个业务域。
- 拆分前后运行验证命令。
- 不改变接口和 DOM 行为。
- 不把文案修复、样式重构和模块拆分混在同一次变更里。
- 拆分过程中保留历史兼容逻辑，并在提交说明中标注。

## 回滚建议

如果发布后出现问题：

1. 先停止服务。
2. 保留现场数据库和日志。
3. 使用最近的 `backup/` 数据库恢复。
4. 回退代码改动。
5. 运行基础验证。
6. 再启动服务。

如果只是前端异常，优先检查 `static/app.js` 语法：

```powershell
node --check static/app.js
```

如果只是后端无法启动，优先检查：

```powershell
python -m compileall -q app tests
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 不确定风险记录

- PLC 真机通讯无法只靠本地测试完全覆盖，涉及现场网络和 PLC 配置。
- 数据库历史兼容逻辑较多，删除或移动前必须用旧库验证。
- 前端当前是单文件无构建结构，拆分为多脚本后必须验证脚本加载顺序。
