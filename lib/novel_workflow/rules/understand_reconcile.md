# 跨章关联的局部汇总核对
输入是同类关联草稿与实际回读的原文片段。草稿及其 supported 标签不构成事实来源；只依据原文重新核对，不调用外部作品知识，不重读或猜测未提供章节。
合并相同依据、相同含义的重复关联；不同故事时间或不同形态的有效状态分别保留，不能把伤前与伤后当作矛盾。证据不足的身份、因果或世界规则降为 uncertain，不因多个草稿重复同一推测而提高确定性。
含义冲突但无法由本次原文排除的结论，保留为 contradiction 且 status=uncertain，解释冲突和缺少的依据；不选看起来最合理的一个。不得用后一章的揭晓倒写前一章的人物认知。
每条关联显式填写 claim_type、perspective、source_kind；只有 fact 且 narrative 的证据结论才允许 supported，其余保留 uncertain。每条 citations 至少覆盖两个不同 Note 且引用输入 fragment_id 和连续原句。story_time 为故事发生时间，揭示位置由系统从证据计算。
覆盖输入中所有不同的有效关联；被合并的重复内容可以省去。不能支持或需要进一步核实的内容写 unresolved，不能静默丢掉。只输出 Findings，不改写原始 Note、资产归属或 SVT。
