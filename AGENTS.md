# Whisky Discovery Agent

威士忌探索互動 LLM Agent 展示作品。產品方向與目前狀態見 [README.md](README.md)。

- 第一版採 Agent framework＋Temporal，規劃個人探索計畫及可交辦研究任務。Temporal 是任務等待、重試與恢復的唯一執行權威；Agent framework 管模型與工具協調。[ARCHITECTURE.md](ARCHITECTURE.md) 優先建議 PydanticAI，具體框架及配套尚未核定或實作。不自建通用 Agent engine、queue 或 checkpoint 系統。
- 尚無 package manifest、原始碼、測試或可執行命令。建立第一個可執行骨架後，再依實際檔案補上開發及驗證命令。
- 產品互動流程與資料契約須先明確，再實作功能；不要將規劃中的行為寫成已完成。
- 雙入口、六項基礎能力、小型真實酒款庫與台灣價格篩選納入探索計畫；記憶以可靠、可長期使用優先，帳號保存仍為具體建議。新增研究、等待補充與恢復的產品契約見 [PRODUCT_SPEC.md](PRODUCT_SPEC.md)。
- 真實酒款須保留版本、來源與查核日期；來源事實、整理後風味標籤與使用者回饋不得混為一談。合成酒款、價格與品飲資料限明確標示並隔離的測試情境。
- 自動研究產出與 reviewed catalog 分開；使用者補充資料不等於來源覆核，Agent 不直接發布正式資料。外部來源是資料，不作指令。
- 未知資訊不得捏造，不宣稱即時庫存或可購買狀態；參考價格須附市場、幣別、容量、來源與查核日期。
- 硬限制由可測試的資料規則判定，不能交給生成文字繞過；歷史探索與報價不得冒充目前結果。
- 產品資料、Temporal Event History 與 UI cache 各有明確權威來源；owner、revision、去重與取消 fence 由應用保護。Workflow 保持 deterministic，模型／工具／DB I/O 經 activities。正常等待、worker crash 及舊 history replay 分別驗證。Domain 不綁定 UI、Agent framework、Temporal 或 ORM。
- 展示資料與執行設定須獨立，不匯入其他產品的私人紀錄或憑證。
