import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import Home from "./page";

test("shows the product entry and honest implementation status", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { name: "威士忌探索", level: 1 })).toBeTruthy();
  expect(screen.getByText("探索功能建置中，尚未提供酒款推薦。", { exact: true })).toBeTruthy();
});
