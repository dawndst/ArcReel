# 按场局部语义复审
核对当前SCN的镜头和来源事件：事实、人物说法、梦境/现实、人物状态、因果、对白攻守、空间与动作连续、关键事件是否实际演清楚。不用未提供后文或小说常识补答案。
输入包含当前场已有原文证据、精简稿、原始台词索引和实际镜头。证据缺少上下文时通过source_requests请求已提供来源索引中的原文。source_ids只能引用真实来源ID，不重抄引句。
findings每项必须给出当前场shot_ids、severity、category、具体reason、source_ids与可操作suggestion。blocker/major仅限会改变关键事实、对白归属或因果理解的实质问题；拍法、风格、运镜偏好只能minor/note，不阻挡组集。对白可以合理取舍，不能只因未拍全原句就报错。
能够安全局部修复时，在corrections给出目标shot_id、segment_index、文字field、after、来源ID与reason。title的segment_index=null，其他字段须指定片段。不要重复输入正确内容，不给无变化建议，不为某个局部问题推翻整场。
不能通过文字字段安全修复的漏镜、对白归属或结构问题列为具体finding，交编导处理。模型建议不代表人工采纳，不自动批准素材或制作。
