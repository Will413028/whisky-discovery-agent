# Whisky Discovery Agent

威士忌探索互動 LLM Agent 展示作品，讓新手從口味出發、有經驗的使用者從喜歡的酒款出發，找到下一支想探索的威士忌。

## 目前狀態

已開始 T00：具備最小 Web、FastAPI 與 Temporal worker 入口、lockfiles、隔離 PostgreSQL／Temporal 測試及 CI 設定。本機 wheel、workerd 瀏覽器互動與 time-skipping 已驗證；尚未部署，產品功能未實作。第一版以「個人探索計畫＋可交辦研究任務」為主軸，涵蓋背景研究、等待補充與恢復。原有雙入口、六項基礎能力、小型真實酒款庫與台灣參考價格繼續提供探索依據。

主軸是保留喜歡的特徵、探索剛剛好的差異，最後留下可回看的選擇與取捨。互動流程、資料契約、建議工程預設與驗收情境見 [PRODUCT_SPEC.md](PRODUCT_SPEC.md)。功能仍待實作，酒款庫也尚未建立。

## 開發方向

- [TDD 實作計畫](IMPLEMENTATION_PLAN.md) 保存 RED → GREEN 證據及尚未通過的 gate；目前執行 T00。
- [技術架構](ARCHITECTURE.md) 採 Cloudflare Workers 上的 Next.js、AG-UI Agent 互動、Oracle VM 上的 FastAPI／PostgreSQL／PydanticAI＋Temporal。無自有網域時，前端先用 `workers.dev`、登入採 Auth0 Free、同源 API 經 Workers VPC Service／具名 Tunnel 連私有後端；逐階段狀態與報告由產品 DB 支援重連。vinext、VPC/SSE、Workers CPU、Oracle 免費資格及備份還原仍待實測；目前帳單 US$0 不等於長期免費額度已確認，尚未開通新服務。
- 這是可獨立開發與部署的產品；不依賴其他作品的執行環境。
- 專案採單一 repo：前端依功能組織，後端以業務模組為主、模組內按需分層，保留 Python `backend/src/whisky/`。目錄與責任見 [技術架構](ARCHITECTURE.md)，首個流程契約與驗證見 [VERTICAL_SLICE.md](VERTICAL_SLICE.md)。目前只建立 bootstrap 與 welcome，未預建業務模組。
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

邊界 gate 檢查直接、靜態可解析 imports：Python domain 只依賴同模組 domain 與非 framework 函式庫，跨模組經 `public.py`／`public/`；Web shared 不引用 features，feature 對外出口為 `index.ts(x)`。動態組合字串與執行時載入不在靜態 gate 的保證範圍，新增此類機制前須擴充檢查。CI 目前涵蓋 T00，不代表未實作的 schema、Auth0、AG-UI、恢復或 release gates 已通過。
