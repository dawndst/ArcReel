import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { WorkflowReviewGuide } from "./WorkflowReviewGuide";

it("distinguishes optional review, scoped generation requirements and final delivery approvals", () => {
  render(<WorkflowReviewGuide />);
  const table = screen.getByRole("table");
  const optional = within(table).getByRole("rowheader", { name: "改编取舍、造型与观众理解辅助" }).closest("tr")!;
  expect(optional).toHaveTextContent("不阻挡建立参考集");
  const images = within(table).getByRole("rowheader", { name: "图片参考确认" }).closest("tr")!;
  expect(images).toHaveTextContent("正式交付需确认");
  expect(images).toHaveTextContent("不妨碍参考集");
  const identity = within(table).getByRole("rowheader", { name: "跨章身份与因果结论" }).closest("tr")!;
  expect(identity).toHaveTextContent("只限制相关 Note");
  expect(screen.getByText(/组集最多 300 镜/)).toBeInTheDocument();
});
