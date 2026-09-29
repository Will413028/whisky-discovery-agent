# Whisky Discovery Agent

威士忌探索互動 LLM Agent 展示作品，讓新手從口味出發、有經驗的使用者從喜歡的酒款出發，找到下一支想探索的威士忌。

## 目前狀態

T00–T08 已驗收：Oracle 原生 Next.js／Node 經薄 Worker／VPC 對外服務，真 Google 登入、跨帳號隔離、串流／重連／取消、reviewed catalog、可靠受理、durable Agent、等待恢復、控制命令、真來源與配額均有本機與 CI 證據；[固定模型對照](backend/evals/T08_REVIEW.md)已完成人工 rubric，選定 Qwen。原 vinext SSR 因 Free CPU 門檻撤回。研究 worker、三款 reviewed catalog 與 migrations 已部署 Oracle VM；加密全備份、WAL PITR 與外部停機 probe 已有真部署證據，T09 的完整登入旅程／回退與告警通知仍待驗，T10–T12 尚未完成。

主軸是保留喜歡的特徵、探索剛剛好的差異，最後留下可回看的選擇與取捨。互動流程、資料契約、建議工程預設與驗收情境見 [PRODUCT_SPEC.md](PRODUCT_SPEC.md)。目前有三款人工覆核起始樣本，完整探索功能仍待實作。

## 開發方向

- [TDD 實作計畫](IMPLEMENTATION_PLAN.md) 保存 RED → GREEN 證據及尚未通過的 gate；目前進行 T09 replay、安全部署與備份還原。
- [技術架構](ARCHITECTURE.md) 採 Oracle VM 上的 Next.js／Node、FastAPI／PostgreSQL／PydanticAI＋Temporal，AG-UI 管互動。`workers.dev` 薄 Worker 經 VPC／具名 Tunnel 連 VM Web，不執行 SSR；Web 固定轉送私有 API，Auth0 Free 管登入。完整新路徑、資源與備份還原仍須實測；目前 VM 帳單 US$0 不是未來保證。
- 這是可獨立開發與部署的產品；不依賴其他作品的執行環境。
- 專案採單一 repo：前端依功能組織，後端以業務模組為主、模組內按需分層，保留 Python `backend/src/whisky/`。目錄與責任見 [技術架構](ARCHITECTURE.md)，首個流程契約與驗證見 [VERTICAL_SLICE.md](VERTICAL_SLICE.md)。目前有 bootstrap、identity、catalog、welcome 與 research 的契約／transport 基礎，按用例加入模組。
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
pnpm --filter @whisky/edge check                     # 薄 Worker dry-run
pnpm --filter @whisky/web test:e2e                    # build 後，Node :3418
```

Catalog 人工發布：先設定此專案的 `WHISKY_DATABASE_URL`，執行
`uv run --project backend whisky-migrate --scripts backend/migrations`，再執行
`uv run --project backend whisky-catalog-publish data/catalog/first-journey.reviewed.json`。
只有明確 reviewed 的 real manifest 可發布，細節見 [覆核紀錄](data/catalog/REVIEW.md)。
發布檔是完整 release snapshot，須帶上仍保留的酒款與來源觀察；封存後不能覆寫。
重複匯入同一 release ID 會拒絕；更新須另建 release ID 與發布時間，保留舊檔與歷史引用。

`GET /health/live` 只代表 API 存活。研究 worker 要求 `WHISKY_DATABASE_URL`、`WHISKY_CLOUDFLARE_ACCOUNT_ID`、`WHISKY_CLOUDFLARE_AI_TOKEN` 同時存在，啟動命令為 `uv run --project backend whisky-worker --address <host:port> --namespace <namespace> --task-queue <research-queue>`；缺設定會在 polling 前失敗。預設模型為 Workers AI Free 的 `@cf/qwen/qwen3-30b-a3b-fp8`。`WHISKY_DAILY_MODEL_NEURONS` 須依此帳戶當日剩餘免費額度設定為 1–10,000；未設定時 worker 可啟動，但 live model 呼叫明確拒絕，不自動切付費模型。單一 worker process 僅綁一組模型／資料庫設定。基礎設施 probe 須明確加 `--probe-only`，並使用 `whisky-probe-` 前綴的獨立 queue；probe 不處理研究。整合測試會建立短生命週期 Temporal server 與獨立 queue；首次執行可能下載 SDK 測試 server。Docker／Temporal 缺失會失敗，不會 skip。

邊界 gate 檢查直接、靜態可解析 imports：Python domain 只依賴同模組 domain 與非 framework 函式庫，跨模組經 `public.py`／`public/`；Web shared 不引用 features，feature 對外出口為 `index.ts(x)`。動態組合字串與執行時載入不在靜態 gate 的保證範圍，新增此類機制前須擴充檢查。CI 設定涵蓋 T00–T02 已實作的 deterministic checks；各提交遠端結果見實作計畫，不代表真 Auth0、恢復或 release gates 已通過。

## T01 身份設定與契約

Web 公開設定範本為 `apps/web/.env.example`；Auth0 SPA 使用 Authorization Code＋PKCE、memory token cache，不需要 client secret。建立專用 tenant 後，設定 callback 為 `<Web origin>/account`，logout URL／web origin 為 `<Web origin>`；變更公開值後重新 build。缺少設定時 `/account` 顯示準備中。

API 讀取 process environment，範例見 `backend/.env.example`，不自動載入 `.env`。三項身份設定必須同時存在，issuer 必須為含結尾 `/` 的 HTTPS origin。完全未設定時私有 API 回 503；不以測試帳號繞過登入。先在隔離的產品 DB 執行 `uv run --project backend whisky-migrate --scripts backend/migrations`，再啟動 API；安裝 wheel 後直接執行 `whisky-migrate`，migration 已隨包提供。API startup 不改 schema，migration 只 forward upgrade；回退需另行審查資料相容性。

Node Web 透過 server-only `WHISKY_API_ORIGIN` 連 API；本機可設 `http://127.0.0.1:8417`，Compose 固定 `http://api:8417`，缺設定回 503。身份 proxy 只接受固定 `/api/v1/me`、`/api/v1/actors/<UUID>` 的 GET，不接收任意 upstream 或 query。薄 Worker 位於 `apps/edge`，只用 `WHISKY_WEB` VPC binding 連 Web；沒有 binding 回 503。部署／回復見 [deploy/README.md](deploy/README.md)。

契約由 Pydantic 產生，不手改 `contracts/`：

```bash
uv run --project backend python scripts/export_openapi.py
pnpm --filter @whisky/web generate:contracts
git diff --exit-code -- contracts/
```

`typecheck` 先執行 `next typegen`。TypeScript 固定 5.9.3，因 openapi-typescript 7.13 依賴 TypeScript 5 compiler API；TypeScript 7 的實測 generator 不相容。

## T02 本機串流驗證

AG-UI 固定 Python 0.1.22／TypeScript core 0.0.59；`eventsource-parser` 負責 SSE transport。TaskView 的 JSON Schema、TS 與 standalone runtime validator 都由 Python 契約產生；不手改 `contracts/`。validator 在 build-time 編譯，避免在 Worker／瀏覽器執行動態 schema compilation。

`pnpm --filter @whisky/web test:e2e` 啟動 Node preview `:3418`、loopback FastAPI fixture `:8419`、workerd 薄轉送 fixture `:3420`，以及連 fixture API 的 Node `:3421`，結束由 Playwright 清理。以 production build 驗薄 Worker→真 Node proxy→FastAPI 的分段 flush／重連；合成來源不掛正式 API。不代替真 Auth0、owner／quota、VPC 或恢復驗收。E2E build 把三個 `NEXT_PUBLIC_AUTH0_*` 設為空，避免本機 ignored 設定影響 fail-closed 案例。
