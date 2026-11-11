# 场镜编号、影视镜头清单与生产关联核查

核查日期：2026-11-11。范围：场镜素材库、第一章正式数据、导演组集、原生内容规划与视觉提示词结构。

## 已实施：展示编号按剧情排列

素材库按 Note 顺序、原文分块顺序、场与镜头数组顺序排列；展示场号 SCN-001…，展示镜号 SH-001…（全素材库连续）。编号在筛选前计算，搜索不会把后面的镜头改成第1镜。补齐更早的章节或片段后，展示编号随剧情位置更新。

旧 SCN/SH 值作为固定来源ID保留在“原文依据”的来源记录中。勾选、归属确认、审核、历史和组集接口仍引用固定ID。导演右栏显示素材镜号和自选播出位置；组集后现有 director.py 按所选顺序生成集内场/镜/SEG层级。素材库尚未归集，不预填EP号。没有重新生成场镜或改变第一章剧情。

## 行业参考与判断

- [Adobe：How to make a shot list](https://www.adobe.com/creativecloud/video/discover/shot-list.html)：镜号/场号、地点、镜头类型、角度、运镜、简要动作与声音备注；强调易扫描，过度堆砌细节也会妨碍执行。
- [StudioBinder：What is a Shot List](https://www.studiobinder.com/blog/what-is-a-shot-list-example/)：列出景别、机位、运镜、设备、画幅、内外景与准备时间等内容。
- [StudioBinder 官方镜头清单操作](https://support.studiobinder.com/en/articles/1455273-how-to-populate-the-shot-list)：支持附图/绘图及图片备注，帮助团队在制作前理解镜头意图。
- [Purchase College 公开制作镜头清单](https://www.purchase.edu/live/files/3701-dn-shot-list-v18pdf)：实际样例分列主体、景别、角度、运镜、镜头焦段、声音及时间，并记录人物位置、道具与连续性备注。

这些是不同制作实践，不是统一强制国标。SH/SCN 的字母和补零位数是项目约定；镜头清单、画面分镜图、拍摄通告表也不是同一份文件。对AI漫剧，摄影器材租赁、搭建时间通常不必机械照搬，景别、构图、动作、声音与连续性仍需明确。

结论：当前素材库 SH 是剧情动作规划草稿，不能等同于完整制作分镜。问题主要是镜头语法与关联结构不足，不是文字数量少。只把动作描述写得更长不会补上缺口。

## 实际实现对照

| 内容 | 素材库现状 | 后续生产侧/缺口 |
| --- | --- | --- |
| 场地、时间、戏剧目的 | SCN 有 location/time/purpose | 还需可执行内外景与时空连续性 |
| SH画面动作、原文 | title、quote/evidence；SEG.scene_description | 原文是追溯依据，不应整段当朗读台词 |
| 景别、光线、氛围 | SH无专门字段，描述中偶有提及 | 原生 image_prompt.composition 已有 shot_type/lighting/ambiance；组集后视觉编写阶段才补 |
| 运镜、动态、环境音 | SH无专门字段 | 原生 video_prompt 有 camera_motion/action/ambiance_audio；并非整个平台都没有这些能力 |
| 机位、主体构图、视线轴线、起止状态 | 没有充分结构化 | 目前依赖自由文本和模型发挥 |
| 台词 | SEG.utterances 保存顺序、kind、speaker、text | 组集原样传递，后续视觉模型不重写口播；缺发声方式、情绪、节奏、源对白ID等明确字段 |
| 人物/场景/道具 | SEG保存 characters_in_scene/scenes/props 名称列表 | 生成时校验登记名称；页面未渲染这些列表。SH未显式绑定asset_id/variant_id/参考图版本 |
| SVT | 输入含 mainline_links.svt_id 与 event_ids；批次保存svt_basis | SH输出不保存可点击SVT/事件关联；可经Note主归属粗粒度追溯 |
| 爆点/爽点 | SVT中保存climaxes/payoffs，含场面、dialogue_ids、note_ids | 生成场镜未直接传入这些对象；输入的Note.highlights不等于SVT爆点。SH未保存moment_id |
| 时长/SEG | 每段不超过15秒，有顺序 | 只控制数字上限，未充分校验对白能否说完、一个SH是否夹有应独立切镜的多个机位 |

代码依据：`lib/novel_workflow/{scene_models,scene_library,director}.py`、`lib/prompts/prompt_builders_script.py`、`lib/script/script_models.py`、`frontend/src/components/canvas/novel-workflow/SceneLibraryPanel.tsx`。

## 台词与资产应该归属哪里

推荐保留清晰分工，而不是把所有文字堆进SH描述：

1. Note：原文事实、事件、原始对白、资产提及，均有原文位置。
2. SVT / 爆点：为什么值得拍；爆点场面、关键对白的源ID、对应Notes。一个爆点可由多个镜头表达，不强求一爆点一镜。
3. SCN：连续时空、戏剧目的、关联SVT与爆点、场景资产。
4. SH：独立镜头意图、景别/机位/运镜/构图、可见动作、对应事件/爆点、必要声音、用到的资产与当前状态。
5. SEG：同一镜头受生成时长约束切出的连续片段，承载这一段实际台词、时长、起止状态与资产使用；切机位或剪辑点应新建SH，不能仅加SEG。
6. 组集：导演选择并排序场镜；继承台词和资产关联，生成集内编号。随后复用现有视觉编写生成图片/视频提示词，再接参考图与视频生成。

对白建议用 `source_dialogue_id + speaker_asset_id + delivery + text + timing`，区分对白、角色内心/画外音、叙述旁白、环境声；保留是否原句、删节或改编的标记。人物名不能代替稳定关联。画外说话人也不应被迫列为画内出场人物。

资产建议用 `asset_id + variant_id + reference_version + usage`；角色身份、年龄/形态/伤势版本、选用参考图分别绑定。关系继承到SEG，局部差异显式覆盖；对白说话人引用同一角色身份，但发声和入画分别表达。

## 建议后续补齐（本轮为调研，未宣称已实现）

- 给爆点稳定ID，生成输入传入当前原文揭示范围内的爆点场面、关键对白与依据；输出保留 scene/shot → event/moment 的可验证关联。不能把跨章SVT完整结局喂给较早镜头。
- 素材库先展示关联SVT/爆点、台词、人物/场景/道具及引用缺失状态；支持追溯到原文、资产与变体。禁止把“共同属于一个Note”冒充具体爆点覆盖。
- SH补充镜头设计，在原生视觉编写处复用这些决定，避免又生成一套相互冲突的景别/运镜。视觉参数属于改编设计，不伪装成小说原文事实。
- 组集前检查关键爆点覆盖、对白归属、片段时长可行性、镜头边界；制作前检查参考图确认和状态连续性。

以第一章“阳子拒绝杉本”为例：剧情摘要只说明拒绝；可执行分镜还需决定拍阳子的反应、同学施压还是杉本反应，何时切镜，谁说话。选择“平视近景、固定机位”等是导演设计，不是原文事实。无需先写几百字，必须把这些制作决定表达清楚。
