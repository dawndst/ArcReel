# 场镜阶段局部修订
只修复 issues 中列出的精确字段路径，保持其他镜头、台词分配、次序与事实不变。base_revision 原样返回。
edits.path 必须与一个 issues.path 完全一致；replace 的 value_json 是该字段的合法 JSON 值，不是说明文字。仅 extra_forbidden 问题可使用 remove，value_json 填空字符串。
参考 context 中的本章来源索引、事件、对白和资产 ID；引用错误改为输入已提供的正确 ID，不重写原文。不猜说话人，不拼接台词，不靠删除正确内容逃避校验。确实缺少原文时可修订 source_requests，请求已提供索引中的来源 ID。
这些编辑是模型候选，不代表人工采纳或图片确认。不要修改未列出的字段，不重生成整场或整章。

若错误明确标记type=unsafe_proposal，可用operation=remove撤回这一条审核提议；不是删除场镜或原著事实。其他场景禁止移除必需字段。
