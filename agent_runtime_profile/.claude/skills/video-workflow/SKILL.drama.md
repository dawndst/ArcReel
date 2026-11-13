---
name: video-workflow
description: 将小说转换为短视频的端到端工作流编排器。当用户提到做视频、创建项目、继续项目、查看进度时必须使用此 skill。触发场景包括但不限于："帮我把小说做成视频"、"开个新项目"、"继续"、"下一步"、"看看项目进度"、"从头开始"、"导演组集"、"自动跑完流程"等。即使用户只说了简短的"继续"或"下一步"，只要当前上下文涉及视频项目，就应该触发。不要用于单个资产生成（如只重画某张分镜图或只重新生成某个角色资产图——那些有专门的 skill）。
---
<!-- mode: drama -->

# 视频工作流编排

## 小说阅读与组集

使用小说工作台指定章节 → AI 精读生成 Notes → 跨章回查与问题结论 → SVT → 场镜 → 导演组集。不存在 AI 自动分集、重规划或重置工具。

你（主 Agent）是编排中枢。你**不直接**处理小说原文或生成剧本，而是：
1. 检测项目状态 → 2. 读计划的 `next_action` → 3. dispatch 合适的子智能体 → 4. 展示结果 → 5. 获取用户确认 → 6. 循环

**核心约束**：
- 小说原文**永远不加载到主 Agent context**，由子智能体自行读取
- 每次 dispatch 只传**文件路径和关键参数**，不传大块内容
- 每个子智能体完成一个聚焦目标就返回，主 Agent 负责动作间衔接

> 两种生成模式（分镜图生视频 storyboard，含 grid_storyboard 宫格开关 / 参考生视频 reference_video）的数据结构与 schema 差异详见 `.claude/references/generation-modes.md`；步骤适用性由计划表达，参考文档不重复。

---

## `collect_project_input`：项目设置

**重要**：项目目录的创建由 Web 端 `POST /api/v1/projects` 触发 `ProjectManager.create_project()` 完成（包括所有子目录与 `project.json`、按 content_mode 物化对应的 Agent profile）。**主 Agent 不创建目录、不写入 project.json 初始字段**——session 启动时 cwd 已绑定到已存在的项目根。

### 新项目

1. 提示用户在 Web 端先创建项目，**创建时指定 content_mode（narration / drama）与 generation_mode（storyboard / reference_video）**；两者创建后均不可变更，Agent 无对应写入权限。session 启动后 cwd 已绑定到对应项目根
2. 使用 Read 工具读取 `project.json`，确认 `title`、`content_mode`、`generation_mode` 字段（本 session 当前 content_mode 为 `drama`，创建后不可变更）
3. 请用户在 Web 端上传小说文本（整本源文），或经 `mcp__arcreel__upload_source` 写入；直接放进 `source/` 而未登记的文件不是源文。用户给的是写好的成品剧本时，经工具登记要带 `source_kind=screenplay`，缺省按小说
4. 在小说工作台对指定章节完成精读与回查，从已读范围归纳项目概述；不因上传自动扫描全书

> 标准项目子目录由 `create_project()` 自动建好：`source/`、`scripts/`、`drafts/`、`characters/`、`scenes/`、`props/`、`storyboards/`、`grids/`、`videos/`、`reference_videos/`、`thumbnails/`、`output/`。

### 现有项目

1. session cwd 已经绑定到目标项目根
2. 调用 `mcp__arcreel__get_workflow_plan({})` 取得服务端权威计划
3. 按返回的 `next_action` 继续（分岔处的备选在 `next_alternatives`）

---

## 计划查询

进入工作流、用户说“继续/下一步/查看进度”、以及每次工具或子智能体完成后，都调用
`mcp__arcreel__get_workflow_plan({})` 取回权威计划（用户指定某一集时，按其说的播出位置或标题在项目 `episodes[]` 里找到那一集，传它的集 ID `{"episode_id": X}`），
再按 `next_action.type` 路由到对应小节；小说内容阶段按「导演编排与内容确认」处理。

计划的字段含义、完整受控动作表、旁白交付、整批准入判定、四条状态轴与 stale / 历史纪律，见
[.claude/references/workflow-plan.md](../../references/workflow-plan.md)。**本 skill 不重复一张按创作类型
或生成模式展开的步骤表**：哪些步骤适用、建议的下一步、哪些操作此刻能执行，一律读 `plan.steps[]`、
`plan.next_action` 与 `plan.status.operations`，它们是阶段判断的唯一真相源。`plan.status` 内嵌完整状态快照
（`project` / `target` / `content` / `operations` / `blockers` / `issues` / `gates` / `artifacts`），不需要再单独查一次状态。

调用后把 `plan.status.target.episode`（目标集的集 ID，下文路径与参数中的 N 即它）作为目标集，把 `next_action.args` 与 `requested_ids` 原样带入
对应动作。Read / Glob 只用于执行已选定动作所需的内容，不用于另建状态机；不得根据空资产 bucket、
文件名、旧文件存在性或对话记忆覆盖服务端结论。

下文各节以 `next_action.type` 为标题；没有单列小节的动作（如 `resolve_draft`、`start_blank_script`、
`add_script_items`）按 workflow-plan 参考的受控动作表执行。`none` 时有 `blockers` 就展示并停止变更；
`steps` 中 `edit` 为 `completed` 表示工作流已走完；其余情况把 `status.issues` 与 `status.content` 讲给用户。
用户点名操作与说「继续」的区别见「灵活入口」。

---

## 动作间确认协议

**每个子智能体返回后**，主 Agent 执行：

1. **展示摘要**：将子智能体返回的摘要展示给用户
2. **获取确认**：使用 AskUserQuestion 提供选项：
   - **继续下一动作**（推荐）
   - **重做此动作**（附加修改要求后重新 dispatch）
   - **跳过此动作**
3. **根据用户选择行动**

---

## 导演编排与内容确认

小说工作台先生成 Notes、问题结论、SVT 和场镜，由工作人员选择场镜并决定顺序后组集。Note 与资料管理组合都不是一集；不得调用自动分集、重规划或 normalize-drama-script 从整段原文重新生成本集内容。缺少 `note_source` 绑定时返回工作台完成导演编排，不绕过依据校验。

`prepare_script_plan` 若出现在小说工作台集的计划中，先检查编排是否完整并告知缺口，不 dispatch 全集规范化。参考生视频仍可在计划明确准入时使用 `next_action.args.preprocessor` 指定的视频单元预处理；这不授权自动分集或重切原文。派发仅传项目路径、目标集 ID、`target.source` 与用户附加指令；预处理成功且 args 含 `expected_stale_script_plan_revision` 时，调用 `complete_script_plan_rebuild` 带回同一 revision，不能以内容是否变化代替完成事实，冲突时刷新计划。

导演编排会生成标准内容草稿。`confirm_script_plan` 时请工作人员审阅选镜、对白、来源和新增资产；取得明确同意后调用 `mcp__arcreel__confirm_script_review({"episode_id": N})`，或由工作人员在 Web 端确认。已有正式脚本时，工具要求覆盖确认的，先展示丢失清单，再按用户同意带回 `overwrite_revision`。确认前逐项展示新增资产及 `register` / `merge` / `derivative` / `skip` 处理；要改处理时在 Web 内容确认页或受控草稿编辑入口修订。`invalid_new_assets` 按工具回执修正，不绕过。确认完成后刷新计划。

内容确认后只在正式脚本上修改：用 `get_episode_script` 读取正文与 revision，再以 `patch_episode_script` 更新需要修订的条目。对应原文保持逐字依据，默认不改台词；工作人员明确采用改编时保留 `origin=adaptation` 与 `basis_quote`。问答承接或单镜问题只修受影响内容，不以重做整集代替局部修订。调整选镜和顺序回到导演编排。

## `generate_script` / `author_prompts`：正式脚本提示词编写

按计划 dispatch `create-episode-script`，传项目路径、目标集 ID、标题、播出位置及用户附加指令，由其使用 generate-script skill。默认只补缺失提示词；局部重写仅在用户明确要求时限定 `entry_ids` 并传 `rewrite: true`，遵循工具覆盖确认，不重新生成内容规划。

---

## `generate_asset_sheets`：本集资产图

**触发**：`next_action.type == "generate_asset_sheets"`，`next_action.args.episode_id` 是目标集的集 ID。
资产随内容确认登记，空资产 bucket 是合法状态，不得据此回退。

「本集引用了哪些资产」由服务端算：按集 ID 调一次 `generate_assets`，服务端生成本集引用、仍缺资产图的全部资产
（角色 / 场景 / 道具 / 商品及衍生），与 Web 集层「生成待生成的资产」同一份名单；衍生与本体同批，本体图生成成功后才提交衍生。

```text
dispatch `generate-assets` 子智能体：
  任务类型：asset_sheets
  项目名称：{project_name}
  工具调用：
    mcp__arcreel__generate_assets({"episode_id": <next_action.args.episode_id>})
  验证方式：按返回的 requested / succeeded / failed / blocked 逐 ID 汇报
```

子智能体返回后，按 [generate-assets](../generate-assets/SKILL.md) 的「审核检查点：审图」为生成成功的资产派发
`review-images` 审图，把生成摘要与审图报告一起展示给用户，再进入动作间确认；用户要处理的资产按该节执行。
`blocked` 项的处理见 [workflow-plan](../../references/workflow-plan.md) 的 `generate_asset_sheets` 行。

---

## `generate_storyboards` / `generate_grid`：分镜图生成

**触发**：`next_action.type` 为 `"generate_storyboards"` 或 `"generate_grid"`；服务端不会在
参考生视频返回这两个动作。

按动作直接选择工具，不二次检查 `generation_mode` 或 `grid_storyboard`：

- `next_action.type == "generate_storyboards"` → dispatch `generate-assets`，调
  `mcp__arcreel__generate_storyboards({"script": target.script_filename, "segment_ids": requested_ids})`
- `next_action.type == "generate_grid"` → dispatch `generate-assets`，调
  `mcp__arcreel__generate_grid({"script": target.script_filename})`——**不传 `scene_ids`**：
  缺失即生成选中的正是 `requested_ids` 所在的分组，同时跳过联合图已就绪而未切分的宫格、沿用在途宫格；
  点名 `scene_ids` 会把它们当作重做请求再付一次费

`generate_storyboards` 把 `next_action.args` 与 `requested_ids` 原样传给子智能体；`generate_grid` 只传剧本文件名。

子智能体返回后，按 [generate-storyboard](../generate-storyboard/SKILL.md) 的「审核检查点：审图」为写入了分镜图的分镜派发
`review-images` 审图（宫格在切分落格之后），把生成摘要与审图报告一起展示给用户，再进入动作间确认。

> **宫格是两段式**：`generate_grid` 只产出联合图，分镜图要经切分落格才会写入，所以在切分之前计划会继续
> 给出 `generate_grid`。结果里的 `grid_ids_awaiting_split`（或摘要里「联合图已就绪、未切分」的宫格）
> 列出未切分的宫格：请用户去宫格面板审阅联合图（可重新生成、上传替换或回滚），**用户明确同意切分后**，
> 再调 `mcp__arcreel__split_grids({"grid_ids": [...]})`。不要在生成完成后自行切分；切分会覆写宫格
> 覆盖的全部分镜图，旧图留在版本历史里可回滚。

> **切换 `grid_storyboard` 后的重做**：本动作的常规触发条件是「缺分镜图」，而用户在设置页切换该开关不会让已有分镜图失效，剧本里也不记录分镜图由哪种装配方式产出——单看缺图会把整集判成已完成。用户在已有分镜图的项目上切换开关后要求按新方式出图时，与其确认要重做的分镜范围，再显式带 ID 重生：切到宫格用 `mcp__arcreel__generate_grid({"script": target.script_filename, "scene_ids": [...]})`，切回单图用 `mcp__arcreel__generate_storyboards({"script": target.script_filename, "segment_ids": [...]})`（`script` 必填；ID 列表省略时只补缺图，达不到重做效果）。已生成的视频同样不会自动失效，重出分镜图后需按新图重跑 `generate_videos` 对应分镜。

## `generate_videos`：视频生成

**触发**：`next_action.type == "generate_videos"`

入队前计划可能先交回 `confirm_request_duration`：整批准入判定要求确认申请档位。按
`admission.confirmation.tiers[]` 逐档位展示涉及的视频单元与费用，取得确认后经
`confirmed_request_durations` 带回下一次 `mcp__arcreel__get_workflow_plan`（见
[workflow-plan](../../references/workflow-plan.md)）。

只有 `plan.steps[].admission.decision == "admitted"` 才入队；`blocked` 或 `confirmation_required` 时
**一个任务都不入队**。此时逐视频单元报告 `admission.units[]` 的 `unit_id`、`problems[].code`、原因与
`problems[].action`；被别人挡住的视频单元带 `generation_batch_admission_withheld`，如实说明是被
`blocked_unit_ids` 连累而非自身有问题。修掉被拒视频单元后**整批重来**，不拆批先跑通过的那一半，
否则会重复提交已经付过费的视频单元。

**dispatch `generate-assets` 子智能体**：请求选择语义与 Web 完全一致。计划里的 `requested_ids` 总是数组：
非空表示**点名强制重做（必然计费）**；`[]` 表示计划未点名，应在工具调用中**省略 ID 参数**以只补缺。
工具入参显式空数组非法，绝不能把计划的 `[]` 原样传给工具。按这两种计划值二选一，不要两个工具都试：

```text
dispatch `generate-assets` 子智能体：
  任务类型：video
  项目名称：{project_name}
  工具调用：
    requested_ids 非空 →
      mcp__arcreel__generate_videos({"script": target.script_filename, "target": {"scope": "selected", "ids": requested_ids},
                                             "force": true})
    requested_ids == []（计划未点名；工具调用不传 scene_ids）→
      mcp__arcreel__generate_videos({"script": target.script_filename, "target": {"scope": "episode", "episode_id": target.episode}})
  验证方式：重新读取 target.script，检查各分镜的 video_clip 字段
```

返回后按逐 ID 分账陈述结果（`succeeded` / `failed` / `blocked` / `skipped`），并把 workflow 步骤状态、
队列任务、供应商 checkpoint、产物时效四轴**分开说**——「任务成功」不等于「当前产物有效」。
stale 产物照常可预览、可导出、可参与成片，是否重做由用户明确决定；不自动删除、覆盖或重生已付费产物。

---

## `create_edit_timeline`：剪辑

**触发**：`next_action.type == "create_edit_timeline"`，本集视频已齐、还没有剪辑时间线。

TTS 配音项目（`plan.status.artifacts.audio.missing_ids` 非空）先补齐缺失的旁白配音：按 `generate-narration-audio`
skill 调 `mcp__arcreel__generate_narration_audio({"script": target.script_filename})`，不带 `segment_ids`。项目选择
TTS 即已授权，无需另行确认。剪辑时间线一建好这一步就完成，之后工作流不会再回到这里补配音。

再调 `mcp__arcreel__create_timeline({"from": "script", "episode": target.episode, "name": "完整版"})` 按脚本
机械新建一条剪辑时间线，至少有一条剪辑时间线，这一步即完成。之后按 `edit-video` skill 在它上面剪辑，
只在用户要求时出成片或导出剪映草稿。

---

## `repair_video_units` / `patch_episode_script`：改剧本再重做

**触发**：`next_action.type` 为 `"repair_video_units"` 或 `"patch_episode_script"`。

Read `target.script`，**只处理 `requested_ids` 对应的条目**。revision 按动作取：
`patch_episode_script` 的 `next_action.args` 已直接给出 `base_revision` 与逐条 `problems`，
直接用，不必再查；`repair_video_units` 的 args 里没有，先调
`mcp__arcreel__get_episode_script({"script": target.script_filename})` 读取正文并取 revision。
再用**一次** `mcp__arcreel__patch_episode_script({"script": target.script_filename,
"base_revision": <上面取到的 revision>, "operations": [...]})` 把全部条目改完——每条一个有序 `update`。
`needs_replan` 之类的标记由工具重算，不要手写。工具报 revision 冲突时刷新计划重来，不得用旧
revision 重试。改完后按上面的请求选择语义点名重做这些 ID，再刷新计划。

---

## `wait_for_task`：有任务在跑

**触发**：`next_action.type == "wait_for_task"`。

已有任务在队列或供应商侧执行中。**不入队任何新任务**，把 `steps[].tasks[]` 的 `task_id`、`status`
与 `provider_checkpoint` 如实说给用户，等待后重新调 `mcp__arcreel__get_workflow_plan` 复查。
`provider_checkpoint.submitted == true` 表示供应商侧已提交、很可能已计费，此时重新提交等于重复付费。

---

## 灵活入口

工作流**不强制从头开始**。根据计划结果，自动从正确的动作开始：

- "继续" → 执行计划的 `next_action`；`next_alternatives` 非空时是分岔，列出选项由用户选
- 点名具体操作（如"分析小说角色""修订第2集镜头""生成分镜图"）→ 先查计划，`plan.status.operations`
  里该操作为 `admitted`（或未列出）就执行，即使 `next_action` 指向别处；为 `refused` 时把 `reason`
  转述给用户，说明缺什么、怎样补上。有 `blockers` 时一律不执行
- 用户说「第 N 集」指播出顺序第 N 个：按 `episodes[]` 的排列取那一集的集 ID，再查它的计划

---

## 数据分层

- 角色 / 场景 / 道具完整定义**只存 project.json**，剧本中仅引用名称
- 项目摘要 `episodes[]` 的派生字段（item_count、status、progress）**读时计算**，不存储
- 剧集元数据（episode 集 ID / title / script_file）在剧本保存时**写时同步**
