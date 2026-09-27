# Whisky Discovery Agent

威士忌探索互動 LLM Agent 展示作品，讓新手從口味出發、有經驗的使用者從喜歡的酒款出發，找到下一支想探索的威士忌。

## 目前狀態

目前處於產品與架構規劃階段，尚無可執行應用、套件清單、測試或部署。第一版已選 Agent framework＋Temporal，以「個人探索計畫＋可交辦研究任務」為主軸，涵蓋背景研究、等待補充與恢復。原有雙入口、六項基礎能力、小型真實酒款庫與台灣參考價格繼續提供探索依據。

主軸是保留喜歡的特徵、探索剛剛好的差異，最後留下可回看的選擇與取捨。互動流程、資料契約、建議工程預設與驗收情境見 [PRODUCT_SPEC.md](PRODUCT_SPEC.md)。功能仍待實作，酒款庫也尚未建立。

## 開發方向

- [技術架構](ARCHITECTURE.md) 已確定由 Temporal 管任務生命週期；Agent framework 優先建議 PydanticAI，Mastra TypeScript 為替代。Next.js、產品 PostgreSQL 及 Python API／worker 的配套仍為建議，尚未核定全部 stack 或開通服務。
- 這是可獨立開發與部署的產品；不依賴其他作品的執行環境。
- 第一個垂直流程驗證委託研究、查證、等待補充、跨程序恢復與保存；另測 worker crash、Update 重送、取消與舊 history replay，再擴展完整探索 UI。
- 展示採用小型、人工查證的真實酒款庫，保留版本、來源與查核日期；合成資料限於明確標示並隔離的測試情境。
- 來源事實、研究草稿、風味整理與回饋分開保存；只有 reviewed 資料進正式推薦，未知資訊保持未知，參考價格不代表即時報價或供貨。

開發前請讀 [AGENTS.md](AGENTS.md)。目前沒有可執行的安裝、啟動或測試指令。
