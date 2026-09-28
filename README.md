# Whisky Discovery Agent

威士忌探索互動 LLM Agent 展示作品，讓新手從口味出發、有經驗的使用者從喜歡的酒款出發，找到下一支想探索的威士忌。

## 目前狀態

T00／T01 的本機與遠端 deterministic CI 已通過；具備 JWT／身份映射、私有 API、固定 proxy 與 Auth0 登入接線。T02 已驗證 AG-UI 雙向契約、TaskView runtime schema 與本機 FastAPI→workerd→瀏覽器串流；正式 observe 尚待接入。尚無 Auth0 tenant 與 VPC 部署，不能宣稱真登入或跨帳號瀏覽器驗收完成。第一版以「個人探索計畫＋可交辦研究任務」為主軸，涵蓋背景研究、等待補充與恢復；產品探索功能與酒款庫仍待實作。

主軸是保留喜歡的特徵、探索剛剛好的差異，最後留下可回看的選擇與取捨。互動流程、資料契約、建議工程預設與驗收情境見 [PRODUCT_SPEC.md](PRODUCT_SPEC.md)。功能仍待實作，酒款庫也尚未建立。

## 開發方向

- [TDD 實作計畫](IMPLEMENTATION_PLAN.md) 保存 RED → GREEN 證據及尚未通過的 gate；目前執行 T02。
- [技術架構](ARCHITECTURE.md) 採 Cloudflare Workers 上的 Next.js、AG-UI Agent 互動、Oracle VM 上的 FastAPI／PostgreSQL／PydanticAI＋Temporal。無自有網域時，前端先用 `workers.dev`、登入採 Auth0 Free、同源 API 經 Workers VPC Service／具名 Tunnel 連私有後端；逐階段狀態與報告由產品 DB 支援重連。vinext、VPC/SSE、Workers CPU、Oracle 免費資格及備份還原仍待實測；目前帳單 US$0 不等於長期免費額度已確認，尚未開通新服務。
- 這是可獨立開發與部署的產品；不依賴其他作品的執行環境。
- 專案採單一 repo：前端依功能組織，後端以業務模組為主、模組內按需分層，保留 Python `backend/src/whisky/`。目錄與責任見 [技術架構](ARCHITECTURE.md)，首個流程契約與驗證見 [VERTICAL_SLICE.md](VERTICAL_SLICE.md)。目前有 bootstrap、identity、welcome 與 research 的契約／transport 基礎，未預建其他業務模組。
- 第一個垂直流程驗證委託研究、查證、等待補充、跨程序恢復與保存；另測 worker crash、Update 重送、取消與舊 history replay，再擴展完整探索 UI。
- 展示採用小型、人工查證的真實酒款庫，保留版本、來源與查核日期；合成資料限於明確標示並隔離的測試情境。
- 來源事實、研究草稿、風味整理與回饋分開保存；只有 reviewed 資料進正式推薦，未知資訊保持未知，參考價格不代表即時報價或供貨。

## 本機開發與驗證

開發前請讀 [AGENTS.md](AGENTS.md)。以下從 repo 根目錄執行；已驗證 Python 3.13.13、uv 0.12.9、Node 26.8.1、pnpm 11.2.2，完整版本見兩份 lockfile。Docker 必須啟動；測試自建 `whisky-test-<UUID>` 容器與隨機 loopback port，結束只清理自己建立的容器，不連既有 DB。

```bash
uv sync --project backend --frozen
pnpm install --frozen-lockfile
pnpm --filter @whisky/web exec playwright install chromium

uv run --project backend whisky-api                  # 127.0.0.1:8417
pnpm --filter @whisky/web dev                       # 127.0.0.1:3417

uv run --project backend pytest backend/tests -q    # 真 PostgreSQL、Temporal、timer
python3 scripts/test_wheel.py                       # 乾淨環境、repo 外 wheel＋worker
uv run --project backend ruff check backend scripts
uv run --project backend ruff format --check backend scripts
uv run --project backend mypy backend/src
python3 -m unittest discover -s scripts/tests -t scripts
python3 scripts/check_python_boundaries.py backend/src
pnpm --filter @whisky/web typecheck
pnpm --filter @whisky/web check:boundaries
pnpm --filter @whisky/web test
pnpm --filter @whisky/web build
pnpm --filter @whisky/web test:e2e                    # build 後，workerd :3418
```

`GET /health/live` 只代表 API 存活。worker 目前只註冊基礎設施用 `BootstrapProbe`，不代表研究功能；對自己的 Temporal server 可執行 `uv run --project backend whisky-worker --address <host:port> --namespace <namespace> --task-queue <isolated-queue>`。整合測試會建立短生命週期 Temporal server 與獨立 queue；首次執行可能下載 SDK 測試 server。Docker／Temporal 缺失會失敗，不會 skip。

邊界 gate 檢查直接、靜態可解析 imports：Python domain 只依賴同模組 domain 與非 framework 函式庫，跨模組經 `public.py`／`public/`；Web shared 不引用 features，feature 對外出口為 `index.ts(x)`。動態組合字串與執行時載入不在靜態 gate 的保證範圍，新增此類機制前須擴充檢查。CI 設定涵蓋 T00–T02 已實作的 deterministic checks；各提交遠端結果見實作計畫，不代表真 Auth0、恢復或 release gates 已通過。

## T01 身份設定與契約

Web 公開設定範本為 `apps/web/.env.example`；Auth0 SPA 使用 Authorization Code＋PKCE、memory token cache，不需要 client secret。建立專用 tenant 後，設定 callback 為 `<Web origin>/account`，logout URL／web origin 為 `<Web origin>`；變更公開值後重新 build。缺少設定時 `/account` 顯示準備中。

API 讀取 process environment，範例見 `backend/.env.example`，不自動載入 `.env`。三項身份設定必須同時存在，issuer 必須為含結尾 `/` 的 HTTPS origin。完全未設定時私有 API 回 503；不以測試帳號繞過登入。先在隔離的產品 DB 執行 `uv run --project backend whisky-migrate --scripts backend/migrations`，再啟動 API；安裝 wheel 後直接執行 `whisky-migrate`，migration 已隨包提供。API startup 不改 schema，migration 只 forward upgrade；回退需另行審查資料相容性。

Worker proxy 預留 `WHISKY_API` fetch binding，目前尚未設定 VPC binding；沒有 binding 回 503。只接受固定 `/api/v1/me`、`/api/v1/actors/<UUID>` 的 GET，不接收任意 upstream 或 query。真 VPC 接線留 T02 驗證。

契約由 Pydantic 產生，不手改 `contracts/`：

```bash
uv run --project backend python scripts/export_openapi.py
pnpm --filter @whisky/web generate:contracts
git diff --exit-code -- contracts/
```

`typecheck` 先以固定 Wrangler 版本產生 ignored runtime types。TypeScript 固定 5.9.3，因 openapi-typescript 7.13 依賴 TypeScript 5 compiler API；TypeScript 7 的實測 generator 不相容。

## T02 本機串流驗證

AG-UI 固定 Python 0.1.22／TypeScript core 0.0.59；`eventsource-parser` 負責 SSE transport。TaskView 的 JSON Schema、TS 與 standalone runtime validator 都由 Python 契約產生；不手改 `contracts/`。validator 在 build-time 編譯，避免在 Worker／瀏覽器執行動態 schema compilation。

`pnpm --filter @whisky/web test:e2e` 除 production preview `:3418`，會啟動 loopback FastAPI fixture `:8419` 與獨立 workerd fixture `:3420`，測試結束由 Playwright 清理。fixture 檔案位於兩端 tests，資料明示合成，不掛載到正式 API／Web routes。此流程驗分段 flush 與 EOF 保留 needs_input；不代替真 Auth0、owner／quota、VPC 或恢復驗收。
