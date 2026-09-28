import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import Home from "./page";

test("shows the product entry and research link", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { name: "威士忌探索", level: 1 })).toBeTruthy();
  expect(screen.getByRole("link", {name:"開始探索"}).getAttribute("href")).toBe("/research");
});
