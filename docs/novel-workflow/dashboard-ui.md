# 创作台界面与制作交接

## 界面参考

配色与节奏条参考 [drama-skills 本地创作台](https://github.com/zenstory-ai/drama-skills/tree/8cf7404981b7095b498e061832bb3c9ffd6a42be/skills/short-drama/assets/dashboard)。其确实包含本地 dashboard；不能将它的交互能力概括为仅有技能文件。

浅色采用暖纸背景、深蓝文字、深青色主操作；深色采用海军蓝背景、浅米色文字、青色主操作。保留本站主题切换。主操作的浅色青色比参考项目进一步加深，以满足小字号白字对比度。卡片间距和边框收敛，分场头部与镜头内容保持清晰层级。

分镜节奏条位于场镜素材库搜索框下方。宽度代表 SH 内所有 SEG 的参考时长之和，颜色代表已有景别。没有景别或复合景别用单独样式和文字说明，不从画面描述猜测。支持按素材顺序、导演选定顺序浏览，点击定位镜头；悬停和键盘聚焦显示镜号、标题、时长及景别。长序列横向滚动，不压缩成无法操作的细线。

节奏条仅在前端读取现有字段，无新 API、模型调用、自动调序或时长预算限制；SEG 仍属同一个 SH。所有时长仅为编导参考，不限制实际视频长度。

## 已落实的工作流清理

剧情项目统一通过 Note → SVT → 场镜 → 导演组集进入生产。删除旧全书阅读实现及无调用的手工切集组件。共用摘要哈希、停止控制和生产适配迁入 `lib/novel_workflow/`。

旧 `POST /api/v1/projects/{name}/episodes` 已删除。解说模式独立使用 `POST /api/v1/projects/{name}/narration-episodes`；剧情项目不可通过此入口创建缺少 Note 来源的集。广告模式保持单集约束。

参考视频模式仍不支持从小说场镜组集；本轮不建设新的参考视频生产管线。

## 制作交接

- 改编取舍扩展已有编导决定：保留、压缩、合并、转化表达、重排、省略，以及戏剧功能和取舍理由。保留来源与版本；已过期决定不进入生产说明。
- 镜头执行可记录资产起止站位、持有者和视线。按导演实际选定顺序比较相邻 SH/SEG；不把未填写状态当成不变，不以文字差异直接断定穿帮。跨场变化不作为同场连续性冲突。
- 交付面板分为镜头与改编取舍、编导确认、参考图交付。比较结果由编导解释；不新增语速预算或自动时长门槛。
- 参考图沿用现有真实文件、图片哈希和人工批准记录，附加允许控制的身份、外观、环境、光照、构图范围及排除项。换图后原图片批准失效。最终交付提示词携带范围说明。
- Blender 仅列于 [未来研究](todo.md)，不安装、不渲染、不进入生产依赖。

## 参考配色许可

配色值取自上述项目 `tokens.css`（MIT）；本站 React 节奏条为独立实现。保留上游许可如下。

MIT License

Copyright (c) 2026 drama-skills contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
