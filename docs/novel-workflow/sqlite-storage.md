# 小说核心业务的 SQLite 存储

## 范围与唯一数据源

小说工作流使用现有 `arcreel.db`。章节目录、管理组、阅读范围、Note、精简稿、理解报告、问题台账、结论及人工裁定、SVT、场镜素材库、组集审核记录进入数据库。正文仍以结构化 JSON 保存于数据库版本表；身份、引用、主归属和版本指针单独建表并受事务和外键约束。

- `nw_projects`：存储项目身份，独立于项目目录名。
- `nw_revisions`：不可变正文版本、内容摘要、时间及版本序号。
- `nw_documents`：各业务记录当前采用的版本。
- `nw_entities`：Note、事件、对白、SVT、爆点、场、镜及决策的身份和删除状态。
- `nw_links`：来源与依赖，包含生成时采用的依据版本。
- `nw_note_svt`：每 Note 唯一主归属，多个 Note 可以对应同一 SVT。SVT 是否仍适用还需核对来源及规则版本。

`.arcreel/novel-storage.json` 只保存项目 ID 和数据库位置。迁移后业务读取不会回退到原 JSON。旧文件移至 `.arcreel/novel-json-before-sqlite/`，仅用于恢复。移除场镜、事件等记录会保留旧版本及可追溯的身份；不会因为一次重新生成直接抹掉历史依据。

配置、SKILL、原文、图片、视频、LLM 原始响应、断点缓存保留文件。现有生产系统的 `project.json`（包括资产主档、已组集的剧集列表）及正式脚本仍使用原生产存储，本轮不迁移它们。SQL 中的资产引用是对生产资产主档的外部引用，不是第二套资产主档。

## 保存与并发

项目元数据锁内的小说业务修改在同一 SQL 事务中提交；引用校验失败会撤销版本、关系和采用指针。读出的正文携带版本号，保存过期正文会明确拒绝覆盖。工作台总览在同一读取事务中组装。模型请求不持有数据库事务。

业务层通过 `store.root` / `storage.load_json` / `store.write` 访问；不要对这些虚拟业务路径调用普通 `open`、`Path.read_text` 或直接写 JSON。数据库历史版本可通过 `storage.reading_version` 查询，供旧场镜回看当时依据。

## 迁移与恢复

先停止服务，使用 SQLite backup API 备份数据库，同时备份完整项目目录。WAL 模式不能仅复制正在运行的 `.db` 文件。

```bash
uv run alembic upgrade head
uv run python scripts/migrate_novel_storage.py /data/projects/book --database /data/arcreel.db
```

迁移逐条比对正文，检查外键，然后才激活数据库读取。重复执行不会重复导入。HTTP 工作流和后台任务入口会对未迁移的项目执行相同迁移，新导入项目也适用。

回到文件存储时，必须导出数据库里的**最新**内容，不能直接恢复迁移前旧 JSON：

```bash
uv run python scripts/migrate_novel_storage.py /data/projects/book --rollback
```

该操作停用数据库定位文件，保留数据库数据以便审计。服务恢复后工作流入口会再次迁入 SQLite；回滚旧程序时应先运行此导出命令，再切换程序版本。

项目 ZIP 导出包含当前核心正文和历史版本包，不包含本机数据库定位文件。导入后得到新的存储项目 ID；第一次进入工作流时导入数据库。完整实例备份仍应同时保存数据库与项目文件，项目 ZIP 不替代账号、供应商配置及任务数据库的备份。

## 验证

专项测试覆盖迁移内容一致性、旧 JSON 不复活、过期版本拒写、事务失败整体回滚、唯一主归属、实际 Note→SVT 流程、历史依据和导出恢复。迁移不触发模型调用，不重新生成内容。
