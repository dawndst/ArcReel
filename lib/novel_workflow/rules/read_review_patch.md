# 抽取审核局部修订输出协议
完整核查原文与所有栏目，只返回 ReviewEdits，禁止返回完整 Reading。reviewed_sections 必须包含输入 review_sections 每一项；包括无修改和空栏目。snapshot 必须照抄输入。完成全部审核才令 complete=true；没有问题时 edits=[]。
replace/remove 的 target 为原始栏目名.从0开始的索引，如 events.2；summary 只可 replace。append 的 target 为栏目名。索引相对原稿，不随其他删除移动。每条修改必须给 reason；仅完全无依据才删除，不能用删除代替修正或精简。
value_json 是单条完整修订记录的 JSON 字符串，不是整个栏目；字段结构与原记录或 record_schema 一致。新增条目也必须有当前原文依据。嵌套对白在其所属事件内修订，保留未变字段和对白。禁止指定 id、evidence 坐标。
quote、context_quote 必须逐字连续，包括助词、内外引号、标点；人物说法、未知状态保持分类，不以引文存在就认定客观事实。无问题的记录不返回，由程序原样保留。
