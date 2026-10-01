import {cleanup, render, screen, waitFor} from "@testing-library/react";
import {afterEach, expect, test, vi} from "vitest";
import {Catalog} from "./index";

afterEach(() => {cleanup(); vi.unstubAllGlobals();});

const source = {evidenceId:"00000000-0000-4000-8000-000000000001",url:"https://source.example/test",publisher:"隔離測試來源",checkedOn:"2026-09-28"};
const item = {
  itemId:"00000000-0000-4000-8000-000000000002", bottleVersionId:"00000000-0000-4000-8000-000000000003",
  name:"合成測試酒款",versionLabel:"測試版本", abv:"40",volumeMl:700,
  claims:[{kind:"fact",key:"tasting_notes",value:"合成測試風味",sources:[source]}],
  flavorTags:[{label:"果香",evidenceIds:[source.evidenceId],method:"editorial",methodVersion:"test-v1"}],
  prices:[{id:"00000000-0000-4000-8000-000000000004",amount:"999",currency:"TWD",market:"TW",volumeMl:700,checkedOn:"2026-09-28",unconditional:false,qualified:false,source}],
  priceUpperBoundTwd:null,priceQualification:"unqualified",
};
const catalog = {releaseId:"00000000-0000-4000-8000-000000000005",evaluatedOn:"2026-09-30",pricePolicyVersion:"price-30d-v1",items:[item]};

test("visitor sees exact version, editorial labels, cited facts and unqualified reference price", async () => {
  const fetcher=vi.fn(async (_url:string) => Response.json(catalog));
  vi.stubGlobal("fetch", fetcher);
  render(<Catalog />);
  expect(await screen.findByRole("heading", {name:"合成測試酒款"})).toBeTruthy();
  expect(screen.getByText("測試版本")).toBeTruthy();
  expect(screen.getByText(/編輯整理.*果香/)).toBeTruthy();
  expect(screen.getByText(/未符合目前價格政策，不能用於嚴格預算判定/)).toBeTruthy();
  expect(screen.getByText(/999 TWD.*700 ml.*2026-09-28/)).toBeTruthy();
  expect(screen.getAllByRole("link", {name:"隔離測試來源"}).every(link => link.getAttribute("href") === source.url)).toBe(true);
  expect(fetcher.mock.calls[0]?.[0]).toBe("/api/v1/catalog");
});

test("unavailable catalog is an explicit retryable error, never an empty success", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("unavailable", {status:503})));
  render(<Catalog />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByRole("button", {name:"重新讀取酒款"})).toBeTruthy();
  expect(screen.queryByText("目前沒有已覆核酒款。")).toBeNull();
});

test("malformed data is rejected before rendering facts", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({...catalog, items:[{...item, bottleVersionId:"not-a-version"}]})));
  render(<Catalog />);
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  expect(screen.queryByRole("heading", {name:"合成測試酒款"})).toBeNull();
});

test("a non-HTTP source URL is rejected before rendering a link", async () => {
  const unsafe = {...item, claims:[{...item.claims[0],sources:[{...source,url:"javascript:alert(1)"}]}]};
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({...catalog,items:[unsafe]})));
  render(<Catalog />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByRole("heading", {name:"合成測試酒款"})).toBeNull();
});
