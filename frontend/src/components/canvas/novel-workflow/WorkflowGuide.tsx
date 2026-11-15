import { WorkflowReviewGuide } from "./WorkflowReviewGuide";
const stages = [
  ["01", "导入与阅读范围", "识别章节目录，选择当前可用章节。每章对应一个 Note；不必读完整本书。"],
  ["02", "AI 泛读生成 Note", "把原文整理成有依据的改编资料：章节概况、人物／场景／道具、事件因果、人物变化、伏笔与关键对白。长章按片段依次提取，最后汇总成一章。"],
  ["03", "跨章精读与回查", "连接不同 Notes 的身份、状态、线索与回收；带着问题检索、回读相关原文，不用未读结局倒改早期事实。"],
  ["04", "SVT 与爆点", "每个 Note 必须按本章重点生成独立 SVT 标题、简介和剧情推进；多个 Notes 可以关联同一条主线，但不能共用本章剧情。优先查看本章新增爆点、台词和原文依据，跨章累计背景折叠展示。会调用模型；未变化的结果可复用缓存。"],
  ["05", "场与镜头素材", "以本章精简稿、SVT、事件与爆点先规划语义场面，再逐场生成 SH；一个连续镜头超过15秒才分 SEG。模型选择台词和资产 ID，程序回填原句与来源；有疑点时按需回读原文。逐场复审事实、因果、说话人、连续性和覆盖，通过校验的文字补正自动完成，只展示最终稿；无法确定的事实冲突定位到镜头交编导核对。局部失败保留结果并可继续，已有部分草稿不代表整章完成。生成素材不直接创建分集。"],
  ["06", "导演组集", "在素材库勾选场镜并填写标题，点击「预览所选场镜并组集」，再点击「创建参考分集并保存编排」。该操作不调用模型；AI 观众理解辅助是可选模型调用。Note 管理组合不等于一集。"],
  ["07", "制作交付", "完善并确认图片资产、镜头提示词及参考资料，交给生成画布制作与剪辑。"],
];

export function WorkflowGuide() {
  return <div className="min-h-0 flex-1 overflow-y-auto p-5">
    <h2 className="text-lg font-bold">工作台流程说明</h2>
    <p className="mt-2 text-sm text-muted-foreground">从原文理解到导演组集。点击步骤说明可查看输入、输出和校验方式；阅读本页不会调用模型。</p>
    <a href="#workflow-review-title" className="mt-3 inline-block text-sm font-semibold text-primary underline underline-offset-4">哪些复审可以稍后处理？查看放行条件</a>
    <ol aria-label="小说改编工作流程" className="mt-5 space-y-3">
      {stages.map(([number, title, description], index) => <li key={number} className="space-y-3">
        <article className="rounded-xl border bg-card p-4"><div className="flex items-start gap-3"><span className="rounded bg-primary/10 px-2 py-1 font-bold text-primary">{number}</span><div className="min-w-0 flex-1"><h3 className="font-bold">{title}</h3><p className="mt-2 text-sm leading-7">{description}</p>
          {number === "02" && <details className="mt-4 rounded-lg border bg-muted/20 p-4"><summary className="cursor-pointer font-semibold">泛读为什么做？原文如何审查？</summary>
            <p className="mt-3 text-sm leading-7"><strong>目的：</strong>把长篇原文变成可检索、可回读的结构化资料，供跨章理解、SVT 与场镜使用。它按指定范围实际阅读原文，不只是生成一段梗概，也不在这一步决定最终拍哪些内容。</p>
            <a href="#workflow-review-title" className="mt-3 inline-block text-sm font-semibold text-primary underline underline-offset-4">哪些复审可以稍后处理？查看放行条件</a>
    <ol aria-label="泛读与审查流程" className="mt-3 space-y-3 text-sm">
              <li className="rounded border p-3"><strong>原文片段 → LLM 提取</strong><p className="mt-1 leading-7">输入当前片段、前后承接窗口和有限的已读记忆；输出场景、资产、人物变化、事件、伏笔、关键对白及引用。承接窗口和记忆用于理解，不作为当前片段新增事实的证据。</p></li>
              <li className="rounded border p-3"><strong>提取草稿＋同一原文 → LLM 语义复审</strong><p className="mt-1 leading-7">再请求一次模型，对照原文逐项检查：引句是否支持整条结论，人物说法是否被误当事实，说话人是否正确，事件因果、人物变化和关键对白是否遗漏，是否提前使用后文身份。模型只返回问题和局部修订；程序保留未修改记录。有依据的保留，无依据的修正，不能确认的留疑点。这一步会调用模型。</p></li>
              <li className="rounded border p-3"><strong>修订稿 → 代码校验 → 保存片段</strong><p className="mt-1 leading-7">检查数据结构、引句能否在本片段逐字定位、重复引句是否有唯一上下文，以及伏笔、身份等关联是否合法。代码不调用模型，也不能判断所有结论是否符合语义。通过后保存，供后续片段续读；失败时保留响应与已完成片段。</p></li>
              <li className="rounded border p-3"><strong>全部片段 → 整章 Note 与精简稿</strong><p className="mt-1 leading-7">汇总整章概况并生成后续改编阅读使用的精简稿；事实依据仍回到原文，不能用精简转述替代原文证据。</p></li>
            </ol>
            <p className="mt-3 text-sm leading-7"><strong>任务何时结束：</strong>Note 与精简稿保存后，若已开启理解层，泛读任务会自动继续跨章回查；界面阶段会切换为跨章理解。它不是重新泛读本章。</p>
            <p className="mt-3 text-sm leading-7"><strong>为什么需要语义复审：</strong>原文确实存在某句话，不代表模型对它的解释正确。例如“景麒说没有危险”不能自动变成“客观上没有危险”。代码可以核验引句，LLM 帮助核验解释。</p>
            <p className="mt-2 text-sm leading-7"><strong>局限与成本：</strong>LLM 复审会增加调用、耗时与费用，也可能漏错或引入新错；它不是人工批准，不能替代跨章回查和编导判断。每片段仍核查全部栏目，但只输出问题与局部修订，减少重复返回；修改须匹配原稿版本，合并后仍执行原文与结构校验。</p>
          </details>}
        </div></div></article>{index < stages.length - 1 && <div aria-hidden="true" className="pl-6 text-lg text-muted-foreground">↓</div>}
      </li>)}
    </ol>
    <div className="mt-8 border-t pt-6"><WorkflowReviewGuide /></div>
  </div>;
}
