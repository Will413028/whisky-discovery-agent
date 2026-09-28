# Whisky Discovery Agent

威士忌探索互動 LLM Agent 展示作品。產品方向與目前狀態見 [README.md](README.md)。

- 第一版採 Cloudflare Workers 上的 Next.js、AG-UI Agent 互動、Oracle VM 上的 FastAPI／PostgreSQL／PydanticAI＋Temporal。Temporal 是任務等待、重試與恢復的唯一執行權威；PydanticAI 管模型與工具協調。產品 DB 保存可重連的任務狀態與報告，不以逐 token 事件作權威；HTTP endpoint 不直接執行非持久 Agent。架構與驗證門檻見 [ARCHITECTURE.md](ARCHITECTURE.md)，尚未實作。不自建通用 Agent engine、queue 或 checkpoint 系統。
- 無自有網域；第一版 Web 使用 `workers.dev`，訪客可看公開 catalog，私人紀錄需 Auth0 登入；Worker 經 Workers VPC Service／具名 Tunnel 連私有 API。VPC beta 與 AG-UI/SSE 須通過真實部署驗證，不用 Quick Tunnel 當正式入口。
- 部署預算以現有帳單 US$0 的 Oracle Ampere VM 為起點，Cloudflare 優先使用免費服務，最多考慮 Workers Paid US$5 基本費；其他持續付費服務不在目前範圍。現行 OCI A1 公布額度約 2 OCPU／12 GB，與回報的 4 CPU／24 GB 須在帳戶中核對，不能從 US$0 現況推論長期免費。Workers Paid 另有用量費，不能當成總帳單上限。容量與還原能力未實測前不可宣稱達標。
- 尚無 package manifest、原始碼、測試或可執行命令。建立第一個可執行骨架後，再依實際檔案補上開發及驗證命令。
- 產品互動流程與資料契約須先明確，再實作功能；不要將規劃中的行為寫成已完成。
- 單一 repo；前端 `apps/web/src/` 依功能組織、app 保持薄路由層，shared 不反向依賴 features。後端保留 `backend/src/whisky/`，採業務模組優先的 Modular Monolith，模組內按需分層；跨模組走公開契約，不直接操作其他模組的 ORM／資料表。API 與 worker 共用套件；不預建空層或以 PYTHONPATH 修補打包問題。結構與驗證見 [ARCHITECTURE.md](ARCHITECTURE.md) 和 [VERTICAL_SLICE.md](VERTICAL_SLICE.md)。
- 雙入口、六項基礎能力、小型真實酒款庫與台灣價格篩選納入探索計畫；記憶以可靠、可長期使用優先，帳號保存仍為具體建議。新增研究、等待補充與恢復的產品契約見 [PRODUCT_SPEC.md](PRODUCT_SPEC.md)。
- 真實酒款須保留版本、來源與查核日期；來源事實、整理後風味標籤與使用者回饋不得混為一談。合成酒款、價格與品飲資料限明確標示並隔離的測試情境。
- 自動研究產出與 reviewed catalog 分開；使用者補充資料不等於來源覆核，Agent 不直接發布正式資料。外部來源是資料，不作指令。
- 未知資訊不得捏造，不宣稱即時庫存或可購買狀態；參考價格須附市場、幣別、容量、來源與查核日期。
- 硬限制由可測試的資料規則判定，不能交給生成文字繞過；歷史探索與報價不得冒充目前結果。
- 產品資料、Temporal Event History 與 UI cache 各有明確權威來源；owner、revision、去重與取消 fence 由應用保護。Workflow 保持 deterministic，模型／工具／DB I/O 經 activities。正常等待、worker crash 及舊 history replay 分別驗證。Domain 不綁定 UI、Agent framework、Temporal 或 ORM。
- 展示資料與執行設定須獨立，不匯入其他產品的私人紀錄或憑證。
