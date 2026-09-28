# TDD 實作計畫

更新：2026-09-28。狀態：T00–T02 已驗收。Oracle 原生 Next.js／Node、薄 Worker→VPC→Web→API 已通過真 Google callback／跨帳號隔離、SSE／重連／取消／token 到期／未讀 consumer 期限與入口回退；獨立驗收對帳無阻擋缺口。T03 已驗收本機 catalog／真 DB／人工覆核出口；T04 開始可靠接受研究。依 [產品規格](PRODUCT_SPEC.md)、[架構](ARCHITECTURE.md) 與 [垂直流程設計](VERTICAL_SLICE.md) 實作，保留 AG-UI／PydanticAI／Temporal、業務模組及 `backend/src/whisky/`。本文件保存細項證據，不另立 roadmap。

## 開工前對帳與狀態規則

每次接續先執行 `git status --short`、`git log -5 --oneline`，核對上述三份設計及本表；命令須在實際 repo 根目錄執行。若版本、前提或其他人的變更影響下一項，先讀差異，不重跑已完成工作或覆蓋未提交內容。各階段按照相依順序執行；發現設計矛盾先修契約，不用測試固定矛盾行為。

| 主待辦對應 | 細項 | 進度 |
|---|---|---|
| 技術入口 | T00–T02 | 已驗收；自動化、真 Auth0／Node／VPC 及隔離／串流 gate 證據見文末及 deploy/t02-node-entry-evidence.json |
| 持久研究骨架與樣本 | T03–T09 | T03 已驗收；T04 開始；T05–T09 未開始 |
| 雙入口與探索計畫 | T10 | 未開始 |
| 比較、回訪與資料管理 | T11 | 未開始 |
| 展示資料與完整驗收 | T12 | 未開始 |

狀態可為未開始、RED、GREEN、REFACTOR、已驗收、受阻。只有本階段的必要自動化與外部 gate 均通過才標已驗收；blocked 的整合不得用 mock 結果代替。規劃階段已結束，現依 T00 開始實作；下載、登入與部署授權仍依當次工作範圍處理。

## 每個增量的 RED → GREEN → REFACTOR

1. 選一個可觀察的行為與最小反例，先寫測試，記錄測試路徑／名稱及預期失敗原因；表中每組案例都要拆成小循環，不能一次寫完整階段再補測試。
2. **RED**：在尚未實作該行為的版本執行，確認 assertion 指向缺少的功能。新模組必要時先放最小介面以讓測試能到達 assertion；依賴未安裝、syntax error、測試沒被收集、DB 沒啟動不算行為 RED。
3. **GREEN**：只補足此案例需要的 production code，重跑同一測試及受影響的既有案例。可以先固定 fixture 的流程，但不能把示例回答寫死當成完整 Agent。
4. **REFACTOR**：在綠燈下整理責任與重複，維持公開契約、依賴邊界與測試綠燈；不要求每輪都一定重構。
5. 檢查差異、lint／typecheck／契約生成與該層驗收。改動交易、授權、恢復或用量防線時，加指定 mutation／故障注入證明測試會抓到防線失效。
6. 記錄本階段證據再接下一個增量；不得用 skip、放寬 assertion、更新 snapshot 掩蓋失敗。主分支／可交付 commit 保持綠燈；RED 的實際結果記在證據中，不要求提交壞掉版本。

純設定與人工操作以 smoke／schema／部署檢查驗證，不為空資料夾、README 或套件清單寫無意義的 RED。生成 client 不手改：先更改契約與測試，再生成。UI 主要驗使用者可見行為，不把整頁 snapshot 當唯一測試。

## 測試分工與環境

| 層 | 工具與真實邊界 | 不能代替的證據 |
|---|---|---|
| Domain／用例 | pytest；日期、ID、外部 ports 可受控；測價格、偏好、引用與狀態規則 | mock repository 不證明 PostgreSQL 交易或唯一約束 |
| PostgreSQL／API | 真 PostgreSQL＋Alembic；FastAPI 測試 client；本機簽章 JWT／JWKS fixtures | 不用 SQLite 代替；本機 JWT 不證明 Auth0 真登入 |
| Temporal | Python SDK test environment、真 worker；時間跳躍驗等待期限，故障測試用分離 worker 程序 | 單純 raise exception 不等於 worker crash；replay 不等於外部 I/O 整合 |
| Web 狀態／元件 | Vitest＋React Testing Library 為骨架候選；測 reducer、互動、AG-UI parser 與錯誤顯示 | async Server Components／workerd 行為由瀏覽器與 runtime 驗證 |
| 契約 | 生成 OpenAPI／Web types；Python／TS AG-UI schema round-trip 與非法 payload cases | TypeScript 編譯不能代替 runtime 驗證 |
| E2E | Playwright＋真 API／DB／Temporal，模型與來源可用標示清楚的 deterministic fixture | fixture E2E 不代表模型品質或公開來源可用 |
| Live／恢復 | 真 Auth0、Workers／VPC、ARM VM、模型 eval、隔離 cluster restore | 本機測試不能勾選 live gate；還原不在唯一正式 DB 演練 |

Temporal 測試環境與 time-skipping 的平台支援在 T00 核對；不支援時用受支援 CI runner 或真 server＋短測試期限，不能 skip 恢復驗收。[Temporal 測試指引](https://docs.temporal.io/develop/python/best-practices/testing-suite)、[Next.js Vitest 指引](https://nextjs.org/docs/app/guides/testing/vitest)。

CI 預設不打 live 模型或公網酒款來源。測試資料、DB／namespace／queue／port 必須隔離且清理限本次建立的資源；JWT fixtures 不可包含正式 token。並行測試不共用可變時間、同一 task 或資料庫清除操作。

## T00 — 前提盤點與可重跑測試骨架

相依：無。範圍：工具鏈、測試設定、bootstrap、CI 與部署驗證記錄。

- 先盤點本機工具、Oracle OS／磁碟／既有負載與帳戶容量，列出 Python／Node／SDK／adapter 的相容組合；外部操作與下載需要時另取得授權，不在計畫中假設已完成。
- 建立最小 pnpm／uv 專案與 lockfiles、隔離測試環境；不一次預建所有業務模組。把實際可用命令寫進 README／AGENTS。
- RED：wheel 安裝後從非 repo 工作目錄載入 API／worker 入口失敗；Web smoke 看不到預期頁面。GREEN：建立最小可啟動入口與頁面，驗實際安裝產物。
- 邊界檢查：對臨時違規 import fixture 故意加入 domain→ORM、shared→feature、跨模組內部引用，確認 gate 拒絕；合法公開依賴通過。不在真業務程式留下違規 mutation。
- 出口：可重跑 backend、web、DB、Temporal、workerd 測試；缺少必要服務時必須明確失敗，不能空跑成功。記錄版本與實際命令，尚不宣稱任何業務完成。

## T01 — 登入與私有 API 入口

相依：T00。範圍：identity、bootstrap、Web auth、固定 upstream proxy。

- RED：有效 token 無法取得自己資料；錯誤 issuer／audience／簽章、過期、disabled actor 被接受；其他帳號的 ID 可讀。每個失敗各自成循環。
- GREEN：JWKS 驗證、內部身份 mapping、owner query 與 no-store；proxy 只允許固定 upstream／路徑／方法。錯誤不能洩漏 token 或內部例外。
- RED→GREEN：登入返回原頁、重新整理、登出清除私人 state、token 到期重新登入；不用 localStorage 保存 token。
- 出口：本機負面授權測試＋真 Auth0 callback／跨帳號瀏覽器測試；移除 owner filter 的 mutation 必須使隔離測試失敗。

## T02 — AG-UI 與 Oracle Web／Workers VPC 最小入口

相依：T01。本階段只用明示的測試狀態來源，不建立完整研究流程。

- RED：兩段延遲 snapshot 被緩衝到最後才抵達；EOF 被顯示為完成；interrupt 被當 success；新 run 的 resume payload 不能通過兩端 SDK schema。
- GREEN：固定 TaskView 契約、AG-UI adapter、串流 proxy 與最小前端狀態處理；observe 僅訂閱，不執行 start／answer。
- RED→GREEN：重複／較舊 view version、不同 task／revision 被丟棄；斷線後 observe 恢復；過期 token、慢 consumer 與多 tab 連線有界。
- 出口：真 workerd／Workers 薄轉送 → VPC → VM Next.js／Node → API 的瀏覽器 flush 時間證據、page errors、登入與重連；記錄 Worker CPU、VM Web／API connection／memory 用量。SDK 相容或 VPC gate 不過就重評，不能繼續宣稱部署路線成立。2026-09-28 使用者改選 Oracle 部署 Web，原 vinext／Workers SSR 證據保留為歷史，不要求再通過已撤回的 SSR 平台。

## T03 — Reviewed catalog 與價格規則

相依：T02。範圍：catalog、migration、data/catalog；先建支援一段旅程的小批樣本。

- RED→GREEN：版本／ABV／容量不符不混用；draft 不進候選；未知不當符合；每個引用能解析到不可變 release／來源。
- RED→GREEN：台灣日期 age=30 可用、31 不可用；未來／缺日期拒絕；最新撤價不退回舊價；每來源最新合格價格取上緣；預算相等通過、少一單位不通過。
- GREEN 最小範圍：純規則＋schema＋發布驗證與查詢用例；不做自動發布或全網搜尋。30 天政策仍是集中配置的驗證預設，正式展示前確認。
- 出口：真 PostgreSQL migration／約束通過，真實樣本人工覆核且 fixtures 分離；將日期比較或 reviewed filter 改錯時對應測試必須失敗。

## T04 — 建立計畫與可靠接受研究

相依：T03。範圍：discovery、research 的 task／receipt、Temporal start adapter。

- RED→GREEN：同 key 同 payload 回原結果；同 key 不同 payload 衝突；跨 owner／舊 revision 拒絕；並行兩個 start 只得到一個 task／workflow。
- RED：DB commit 後、Temporal start 前中斷；server 已接受但 HTTP 回應遺失；完成後重送誤啟新工作。GREEN：穩定 workflow ID、明確重用政策、receipt 與同 key 對帳。
- 出口：真 Temporal／DB 驗到 queued；未確認接受維持 acceptance_pending 且可重試，不提前顯示已開始。注入 start 回應遺失後必須找回原工作。

## T05 — Durable Agent、證據與原子保存

相依：T04。範圍：research agents／workflows／activities／application／adapters。

- RED→GREEN：使用 deterministic model adapter 讓 PydanticAI 實際選工具、查 catalog、保存 evidence 與 typed report；HTTP 斷開後工作仍可完成。不是用手寫 workflow 結果取代整條 Agent 整合。
- RED：report commit 後、activity completion 前中止造成第二份 report。GREEN：artifact key、交易式 fence、task completed 與 view version 原子更新。
- RED→GREEN：非法 evidence ID、無來源事實、未 reviewed 價格不能變成正式候選；預設不保存隱藏推理或 token。模型／工具呼叫需留可驗證的活動邊界。
- 出口：先以受控模型證明機制；真模型品質在 T08 驗證。已記錄完成的工具步驟不重做，未確認 I/O 允許重試但不重複寫入。

## T06 — 等待補充、跨程序恢復與 UI

相依：T05。範圍：clarification、Temporal Update、AG-UI resume、research UI。

- RED→GREEN：需要版本補充時保存問題，AG-UI 回合 interrupt 結束但 task 仍 needs_input；關頁、換瀏覽器、重啟 worker 後仍找到同一問題。
- RED→GREEN：答覆帶 question ID／等待版本，REST 與 AG-UI 走同 receipt；同答案重送冪等，不同答案並行只能接受一個；發布問題到 wait 的競爭不漏答覆。
- RED→GREEN：過期／已關閉問題拒絕；答覆 commit 後中斷可恢復；回覆後重新核對價格，不使用等待前舊查詢冒充新查核。
- 出口：以 time-skipping 測期限，以不同 worker 程序測恢復；Playwright 完成委託→等待→關頁→登入回覆→報告。不能用固定 sleep 猜測競爭時序，使用測試 barrier／可觀察狀態。

## T07 — 取消、條件變更、刪除與晚到結果

相依：T06。範圍：control command、跨模組用例、VM 外控制紀錄 adapter。

- RED→GREEN：外部意圖未保存不能執行 DB effect；成功意圖＋DB effect＋結果收據後才顯示完成；回應遺失沿原 command 對帳。
- RED→GREEN：取消先取得 fence 時，晚到 report 不可保存；修改研究條件推進 revision、關閉舊問題、標 superseded，完成報告留歷史，只有明確新命令建立新研究。
- RED→GREEN：上層 plan／actor 刪除涵蓋所有子 task；重新收藏的新 instance 不被舊命令刪掉；已拒絕控制命令不能被當成成功。
- 出口：DB 競爭使用兩個獨立連線與 barrier；移除 fence 的 mutation 必須失敗。外部紀錄先用故障可控 adapter 驗演算法，真 Object Storage 權限與恢復在 T09 驗證；本階段通過不代表已能正式刪除資料。

## T08 — 真來源、模型品質與用量防線

相依：T07。範圍：source reader、model adapter、配額與固定 eval。

- RED→GREEN：不在 allowlist 的來源、redirect 到私網、過大／逾時回應被拒絕；外部頁面指令不能擴張工具權限或發布 catalog。
- RED→GREEN：帳號／全站配額並行搶占不超限；重試計入用量；崩潰後預留不消失；未知完成結果不全額退款；等待不占主動執行名額；硬額度耗盡明確停止、不切付費模型。
- 固定 eval 先定輸入、可接受行為與 rubric，再跑真模型。硬限制、owner、reviewed 邊界、引用有效性要求全部通過；繁中可理解性、工具選擇與問題品質由人工 rubric 評分，不以精確字串限制自然語言。
- 出口：同一語料的模型版本、prompt／policy、失敗案例、latency／用量記錄；重複樣本可查不穩定性。live eval 失敗要修復並重測，不算 deterministic TDD 的 RED。是否鎖定模型依這份證據決定。

## T09 — Replay、安全部署、備份還原與入口總驗收

相依：T08。範圍：deploy、recovery／replay tests、CI gates。

- RED→GREEN：刻意不相容 workflow 對固定舊 history replay 失敗，版本相容方案後通過；等待中的舊工作在新 release 後仍有 executor。History 由隔離測試生成，不把正式私人 payload 提交 repo。
- RED→GREEN：在獨立 worker 程序注入非正常中止，重啟後接續；另驗 DB／Temporal 暫停、遺失回應與服務恢復，不能只測正常 shutdown。
- RED→GREEN：還原到刪除 effect 前，套用 VM 外完整控制紀錄後私人資料不復活；意圖超過 30 天才生效、漏頁、物件讀失敗、pending／rejected／新 generation 都有反例。無法確認時保持隔離。
- 真實演練：全 cluster 備份／WAL → 空的隔離環境還原 → 控制紀錄對帳 → 私人 API 驗證；記錄備份大小、最舊可還原點、實際遺失窗口與恢復時間。依量測收斂工具、保留期、RPO／RTO，不倒推捏造達標數字。
- 出口：ARM image、migration、rollback、健康檢查、外部停機告警實測；套用上一版相容 artifact 不退 schema；通過 T01–T08 的真整合旅程。到此才標持久研究骨架完成及允許正式保存私人紀錄。

## T10 — 雙入口與完整探索計畫

相依：T09。範圍：Web plans／catalog／research、後端 discovery。

- RED→GREEN：新手描述轉成可確認偏好，熟手先消歧酒款版本；推測不自動變硬條件，本次預算不偷偷變長期偏好。
- RED→GREEN：最多三支候選且不足不湊滿；保留／差異都能指出證據；「少煙燻」不能由缺少標籤推導；無符合結果可說明且不自行放寬條件。
- RED→GREEN：自然語言與點選使用相同 command；修正只改指定條件；舊回合結果保持歷史、不能存為新 revision 結論。
- 出口：新手／熟手各一條真瀏覽器旅程，重送與交錯 SSE 不覆寫新結果；規則用 unit tests、畫面行為用元件／E2E，模型說明另以 rubric 驗證。

## T11 — 比較、探索結論、回訪與資料管理

相依：T10。範圍：library、相關 discovery 用例與 Web。

- RED→GREEN：兩至三支同維度比較，單支顯示詳情、未知保持未知；詞彙解釋可回到當前酒款證據，不虛構強度或量測。
- RED→GREEN：可保存選中或「沒有適合的」結論；收藏不等於喜歡，喝過喜歡不代表喜歡每個標籤；帳號跨瀏覽器恢復，移除的 catalog item 保留歷史解析出口。
- RED→GREEN：重開用目前 catalog／價格判資格，歷史理由保持當時快照；偏好與回饋修改有 owner／revision 與重送保障。
- RED→GREEN：匯出僅包含自己的完整可匯出資料；刪除涵蓋 DB、相關 history、debug traces 與備份保存政策，重跑 T07／T09 對新增資料的防復活案例。
- 出口：比較→選擇→收藏／喝過→重開→匯出／刪除旅程及跨帳號負例通過；不拿匯出檔代替備份。

## T12 — 真實資料覆蓋與展示驗收

相依：T11。範圍：catalog、eval corpus、完整產品旅程。

- 先寫資料資格與覆蓋檢查，讓缺少引用、版本衝突、過期價格及無可解釋替代路徑被明確列出，再補真實覆核資料；不可為了讓測試綠燈捏造事實。
- 資料覆蓋對應 PRODUCT_SPEC 的新手、熟手、無結果與持久研究旅程；20–30 款是規劃參考，不是數量達標就自動驗收。
- 跑完整 deterministic CI、live model eval、實際部署 Playwright 與人工可用性檢查；鍵盤操作、錯誤提示、手機版主要流程都可完成。
- 出口：每個產品驗收條件對應測試 ID 或人工證據、來源查核日期與部署版本；所有必要 gate 通過才宣稱 MVP 完成。

## CI、完成證據與回退

骨架建立後才填可執行命令；以下是 job 責任，不是假裝已存在的 scripts：

- 每次改動：相關 pytest／Vitest、lint／typecheck、import 邊界與生成契約差異。
- PR：全部 deterministic domain、真 DB／Temporal integration、replay、wheel 安裝、workerd browser E2E；必要 job 未執行或被取消不算成功。
- Release：受控 live auth／VPC／模型、ARM artifact smoke、舊 workflow 接續與 migration／rollback；備份邏輯或 schema／控制紀錄改動再跑完整恢復演練。

每項完成後在下方追加精簡證據：`Txx／案例 → 測試路徑 → RED 命令與實際原因 → GREEN 命令與結果 → mutation／故障結果 → commit／artifact → 尚未驗證項`。命令含工作目錄與版本，失敗摘要不含秘密；較大的 log 留可定位 artifact，不整份貼進本計畫。

只有首次達成該行為前的真實失敗才記 RED；若工作已由另一提交實作，記錄「既有行為＋回歸驗證」，不能事後假造 TDD。抽樣 mutation 是測試辨別力證據，不改寫開發歷史。測試覆蓋率可輔助找漏測，不用單一百分比替代上述場景。

各增量未部署時用正常 forward fix／小範圍 revert，不抹去其他人的變更。已部署時依 VERTICAL_SLICE 的 artifact rollback 與相容 migration 順序操作；不以還原整庫解決一般程式錯誤。基礎設施 gate 受阻時記下缺少的具體證據，只繼續不依賴該 gate 的測試／設計工作，不把下游階段標完成。

## 執行證據

### T00 — 2026-09-28 本機骨架

基線：`git status --short` 為乾淨，`git log -5 --oneline` 起點 `7d2a7df`。以下命令以 repo 根目錄為工作目錄；實際執行使用絕對路徑。產物為本增量的 source、lockfiles、測試及 `.github/workflows/ci.yml`，沒有部署 artifact 或業務完成宣告。

| 案例／測試路徑 | 首次 RED 命令與實際原因 | GREEN／驗證 |
|---|---|---|
| wheel API：`backend/tests/test_installed.py::test_installed_api_answers_liveness` | `python3 scripts/test_wheel.py`：wheel 安裝成功、repo 外可 import，但 `create_app()` 回 None，assertion 失敗 | 加入 FastAPI 與 `/health/live` 後相同命令通過；後續改用 httpx ASGI transport 消除 TestClient deprecation，保持相同斷言 |
| wheel worker CLI：同檔 `test_installed_worker_entrypoint` | 同上：`whisky-worker --help` 空輸出，缺少 `--task-queue` | 實作 CLI 後通過；不以 help 當真正執行證據 |
| worker 程序：`backend/tests/integration/test_temporal.py::test_worker_process_executes_bootstrap_probe` | `uv run --project backend pytest backend/tests/integration/test_temporal.py -q`：真 server 接受 workflow 後 worker 提早 exit 0，assertion `worker exited before processing a workflow` | 註冊基礎設施用 BootstrapProbe、啟動 Worker poll 後通過；wheel 測試亦從 repo 外啟動獨立 worker 並完成相同工作 |
| Web：`apps/web/src/app/page.test.tsx` | `pnpm --filter @whisky/web test`：空 main 找不到「威士忌探索」heading | 加上入口及未完成提示後通過 |
| workerd hydration：`apps/web/tests/e2e/smoke.spec.ts` | build 後 `pnpm --filter @whisky/web test:e2e`：真頁面有 heading，但找不到「了解探索方式」button | 加入 welcome client component 後按鈕可展開說明，pageerror 為空，1 passed |
| Python domain/framework：`scripts/tests/test_python_boundaries.py` | `python3 -m unittest discover -s scripts/tests -t scripts`：4 個 framework 違規 fixtures 回傳空錯誤 | AST gate 拒絕 SQLAlchemy／FastAPI／Temporal／PydanticAI；合法 domain imports 通過 |
| Python 跨模組內部引用：同檔 | 同上：絕對、相對、from package import 三種引用形式及跨 domain 共 4 個反例未攔下 | gate 只允許跨模組 `public` 契約；同模組與合法公開 import 通過 |
| Python domain 經本地層接入 infrastructure：同檔 | 同上：adapters／platform／bootstrap 3 個反例未攔下 | domain 對專案內依賴限同模組 domain，4 個 test methods 全數通過 |
| 複核回歸 `domain.py`：同檔 `test_single_file_domain_obeys_same_boundaries` | 同上：單檔 domain 引入 SQLAlchemy／platform 2 個反例未攔下 | 依去除副檔名後的模組層判定，單檔／目錄同規則；5 個 methods 通過，獨立複核確認修正 |
| Web shared→feature：`apps/web/tests/boundaries.test.ts` | Vitest：import／re-export／dynamic literal import 3 個違規 fixtures 未攔下 | Babel AST gate 拒絕；app 組合公開 feature 通過 |
| Web 跨 feature 內部引用：同檔 | Vitest：alias／相對路徑 2 個違規 fixtures 未攔下 | gate 拒絕內部引用，公開 index 與同 feature 通過；含首頁共 10 tests passed |

純設定／真環境 smoke（不冒充 RED）：

- `uv run --project backend pytest backend/tests -q`：5 passed；PostgreSQL 18 digest 固定，獨立 UUID 容器／隨機 loopback port，驗真 UUID 欄位與 SQL 往返，finally 只停止自己的容器。沒有產品 migration，不能當 schema／交易競爭驗收。
- Temporal SDK 1.33.0 的 local server 實測 CLI 1.9.1／Server 1.32.0；macOS ARM64 可啟動 time-skipping，七天 timer 實際跳時通過。這是 SDK smoke，不是 worker crash、history replay 或 PostgreSQL persistence／restore 驗收。
- `python3 scripts/test_wheel.py`：乾淨 venv、非 editable wheel、repo 外 cwd、移除 PYTHONPATH，執行 API、CLI、獨立 worker 與 timer 共 4 個案例。
- `ruff check`、`ruff format --check`、`mypy backend/src`、Web `typecheck`、兩端實際 source 邊界掃描、`pnpm peers check`、production build 皆作本機驗證。依賴下載與最初 unittest discovery 問題未計入 RED。
- `.github/workflows/ci.yml` 使用相同命令；尚未 push／觸發 GitHub Actions。未實作的契約生成、replay、恢復及 live gates 不列假成功 jobs。

版本與相容性：

| 層 | 實測／候選 |
|---|---|
| Python／API | Python 3.13.13、uv 0.12.9、FastAPI 0.141.1、Pydantic 2.13.5；`backend/uv.lock` |
| Worker／DB 測試 | Temporal SDK 1.33.0、psycopg 3.3.6、PostgreSQL 18.6 多平台 image index digest（本機使用 ARM64）；`docker buildx imagetools inspect postgres@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873 --raw` 確認含 linux/amd64、linux/arm64，未在 VM 安裝 |
| Web | Node 26.8.1、pnpm 11.2.2、Next 16.3.6、React 19.3.0、vinext 1.0.0-beta.13、Vite 8.3.1、Cloudflare Vite plugin 1.61.0、Wrangler 4.142.0；`pnpm-lock.yaml` |
| 測試工具 | pytest 9.1.1、Vitest 5.0.2、Playwright 1.63.0、TypeScript 7.0.2 |
| Agent／AG-UI 候選 | PyPI metadata：PydanticAI slim 2.51.0 支援 Python ≥3.10、Temporal ≥1.27；其 AG-UI extra 要求 `ag-ui-protocol>=0.1.10,<1`，相容範圍最新 0.1.22。Python／TS AG-UI 最新均為 1.0.0，不能直接混裝最新版本。尚未加入產品依賴；T02 選定能通過 interrupt／resume round-trip 的組合，若不成立則重評。metadata 不等於整合成功。 |

前提盤點：已授權的唯讀 SSH 查得 Ubuntu 24.04.4 ARM64、4 CPU、RAM total 23,974 MiB／available 21,902 MiB、root available 128 GiB、load 0.16／0.16／0.17（2026-09-28 本輪快照）。主機另有 workload；此刻餘裕不等於新增 stack 的容量驗收。帳戶既有查核紀錄為 PAYG，Oracle [公開價目表](https://www.oracle.com/cloud/price-list/)的 paid tenancy A1 額度為每月 3,000 OCPU-hours／18,000 GB-hours；與 Free Tier 的 1,500／9,000 不可混用。未重新查 OCI Usage API、未改動 VM；個人 inventory／查核來源位置留於 ignored local context。

此處為 T00 首次驗證快照；後續 CI／Linux 與 T01 證據見下。Oracle 新增 workload、Agent／AG-UI 組合、真 Auth0／VPC／SSE、備份還原仍未驗證。T00 保持 GREEN 而非整體技術入口已驗收。

獨立複核：1 個 P2 finding（單檔 domain gate）已依 RED→GREEN 修正並回看；PostgreSQL ARM-only 疑點經 registry index 證據排除。主程序另以 `docker run --rm -v "$PWD:/repo:ro" -w /repo rhysd/actionlint:1.7.12 .github/workflows/ci.yml` 驗 CI YAML 通過；不等同 Actions job 已執行。

### T00 後續驗證／T01 — 2026-09-28

基線 commit `a9bb3bb` 已推送 main，T01 工作分支 `feat/t01-identity-entry`。T00 [Actions run 36391026128](https://github.com/Will413028/whisky-discovery-agent/actions/runs/36391026128) 的 backend／web jobs 均未啟動；逐一查 check-run annotations，原因為帳戶付款或 spending limit，不是程式 assertion。未修改帳戶 billing。

T00 額外 Linux 證據：`git archive a9bb3bb` 輸入 `docker run --rm --platform linux/amd64 --cpus 2 --memory 2g -i python:3.13-slim`，安裝 uv 0.12.9 後執行 `python scripts/test_wheel.py`，4 passed（13.13s）。這是該 commit 的 Linux wheel／Temporal smoke，不代替 Actions、完整 Linux DB／Web 或 Oracle 部署。

以下命令以 repo root 執行；實際操作使用絕對路徑。T01 證據隨 source／tests 保存於本分支的身份入口增量提交。

| 行為／測試 | 實際 RED | GREEN／回歸 |
|---|---|---|
| `backend/tests/test_tokens.py` 有效 RSA token | `uv run --project backend pytest backend/tests/test_tokens.py -q`：stub verifier 拒絕有效 token | 固定 issuer／audience／RS256，從固定 JWKS 取 key；有效 token 通過 |
| 同檔空 subject | 同命令：空 subject 未拋 InvalidToken | 拒絕空白 subject；issuer／audience／signature／exp／iat／nbf／sub type、null 必要 claims 為 library 既有保護的回歸測試，不冒充首次 RED |
| `backend/tests/integration/test_identity.py` 首次身份映射 | `uv run --project backend pytest backend/tests/integration/test_identity.py -q`：resolve 回 None | 真 PostgreSQL＋Alembic 建立 users／identities，同 issuer＋sub 回同 UUID |
| 有效 token 讀自己 | 同命令：GET /me 回 404 | 回 200 及 no-store |
| 停用帳號 | 同命令：預期 403 實際 200 | current_actor 檢查 active，拒絕停用帳號 |
| 自己／他人 actor resource | 自己最初 404；加入 endpoint 後，他人資料錯回 200 | SQL 同時比對 resource ID 與 owner ID，其他與不存在同為 404 |
| 安全錯誤 | 同命令：401 回 detail，缺少 code／request_id | 統一安全 envelope、不回 token；驗證錯誤與 DB failure 亦安全回應 |
| `account.test.tsx` 登入返回原頁 | `pnpm --filter @whisky/web test`：找不到登入按鈕 | SDK loginWithRedirect 帶 appState.returnTo |
| 帳號載入／登出／token 到期 | 同命令：找不到「帳號已連線」與「重新登入」 | memory bearer 呼叫生成 client；登出清除私人 state、abort 與 stale-response guard；SDK login_required 顯示重新登入 |
| `tests/proxy.test.ts` 固定 proxy | 同命令：stub 回 503 而非 200 | 固定 upstream、路徑／方法 allowlist，拒絕 query、redirect，不轉送 cookie；missing binding fail closed |
| 複核：失敗 callback 重試 | 同命令：returnTo 仍含已消耗 code/state/error | 統一 safeReturnTo，移除 OAuth response 參數並保留正常 query/hash；失敗 callback 清理及外部／無效 URL 回歸通過 |

Owner mutation：暫時移除 `users.c.id == owner`，執行 `uv run --project backend pytest backend/tests/integration/test_identity.py -q -k other_actor`，1 failed（foreign 200 != missing 404）；finally 還原，完整 suite 重新通過。並行首次登入測試用 barrier 強制四個 transaction 首次 lookup 均未找到身份，再驗同 actor 且 users／identities 各一筆；這是 savepoint 實作的回歸，不宣稱首次 RED。

最終本機檢查：

- `uv run --project backend pytest backend/tests -q`：29 passed，包含真 DB、Temporal、設定 fail-closed；`python3 scripts/test_wheel.py`：4 passed，另驗 wheel 內 Alembic revision／env 資源可解析。
- `pnpm --filter @whisky/web test`：22 passed；`build` 與 `test:e2e`：2 passed，包含未配置帳號頁及真 workerd 私有 API 503/no-store。沒有用 mock 宣稱 Auth0 真登入通過。
- Python ruff／format／mypy、Python／Web boundary gates、TS typecheck、OpenAPI→TypeScript 生成、peer 檢查、actionlint 均以本機命令檢查。CI 新增契約 drift 檢查；遠端仍受 billing 限制。
- TypeScript 7 無法提供 openapi-typescript 7.13 所需 compiler API，實測 generator 失敗後固定 5.9.3，生成成功。Auth0 React 2.27、PyJWT 2.15、SQLAlchemy 2.1.1、Alembic 1.20，完整依賴以 lockfiles 為準。

獨立複核：design-review 檢查 ID、transaction、schema、JWT/JWKS、cache、proxy、Auth0、migration、錯誤與契約生成，0 design findings（改／記／提／駁回均 0）。另一般 code review 提出 callback 重試 1 個 P2，已按 RED→GREEN 修正並由原複核者唯讀回看確認關閉。

尚缺：專用 Auth0 tenant domain／SPA client ID／API audience，真 callback、重新整理、跨帳號瀏覽器驗收；VPC／具名 Tunnel 與真部署仍屬 T02。T01 只標本機 GREEN，未標已驗收。沒有新增外部登入、設定 secrets 或改動 VM。

### T01 遠端 CI／T02 契約與串流基礎 — 2026-09-28

T01 commit `70c1c75` 已推送 `feat/t01-identity-entry`。repo 改為 public 後，[run 36394778639](https://github.com/Will413028/whisky-discovery-agent/actions/runs/36394778639) 與 [run 36394777273](https://github.com/Will413028/whisky-discovery-agent/actions/runs/36394777273) 的 backend／web jobs 各自 conclusion 均為 success；以 `gh run view <run> --json jobs` 查驗，不只看 run 層級。先前 billing 阻擋不再阻擋這次公開 repo 的執行，未修改帳戶 billing。

T02 工作分支 `feat/t02-agui-entry`，基線 `70c1c75`。本增量先完成可獨立驗證的 schema、projection、transport 與本機跨程序 fixture，不建立持久研究或假登入。正式產品 API 尚未掛載 `/agent/observe`，fixture server 僅位於 tests 並綁定 loopback。

SDK 前提：Python `ag-ui-protocol==0.1.22`、TS `@ag-ui/core==0.0.59` 的 interrupt／新 run resume 雙向往返保留欄位。隔離環境以 `uv run --no-project --python 3.13 --with 'pydantic-ai-slim[ag-ui,temporal]==2.51.0' --with ag-ui-protocol==0.1.22 python -c '<import AGUIAdapter 與 durable_exec.temporal>'` 成功解析依賴及 import；這不是模型／durable agent 執行驗收。PydanticAI 尚未加入產品依賴。

Transport 決定：`@ag-ui/client@0.0.59` 實測無法在 EOF 前解析 CRLF frame；已安裝 source map 的 `src/transform/sse.ts` 只以 `/\n\n/` 分隔，且自行 subscribe 的 teardown 未回傳外層。選項為限制 LF、獨立 parser、升級 SDK 組合；使用者明確選擇獨立 parser。移除 client dependency，保留 AG-UI schema，採 `eventsource-parser==4.1.1` 的 Web Streams parser，不自行重寫 SSE 語法。[parser 官方說明](https://github.com/rexxars/eventsource-parser)、[AG-UI interrupt 契約](https://docs.ag-ui.com/concepts/interrupts)。

| 案例／命令（repo root） | 真實 RED | GREEN／證據 |
|---|---|---|
| `uv run --project backend pytest backend/tests/test_agui_contract.py -q` | waiting adapter 只送普通 RUN_FINISHED，outcome 為 None | 明確 interrupt outcome 與 question correlation ID；TS/Python 雙向解析通過 |
| `uv run --project backend pytest backend/tests/test_task_view.py -q` | needs_input／completed／failed 缺少對應 payload 仍通過，3 個 DID NOT RAISE | Pydantic 與生成 JSON Schema 共用 status/payload 規則；TaskView 不接受未知 schemaVersion、非法版本或不一致終態 |
| `pnpm --filter @whisky/web exec vitest run tests/research-state.test.ts` | 首次 snapshot 被丟棄；後續另一輪 6 個 foreign／stale／connection／payload cases 失敗 | 同 task/thread/revision、遞增 viewVersion、connection generation 保護；EOF 只改 connected，不製造成功 |
| `… vitest run tests/research-transport.test.ts` | 最初整份 text() 無法在 EOF 前觸發 callback；換原 SDK 後 CRLF 仍失敗 | parser 對逐 byte UTF-8、CRLF、heartbeat 即時解析；非法 JSON/schema、過大 frame、截斷 EOF 回歸通過 |
| 同 transport suite 的 cancel/auth/consumer | abort 未取消 upstream；401 缺少安全分類；慢 consumer 尚未完成就收到第 2 個 event | abort 傳播與 reader cleanup、AUTH_REQUIRED、逐事件 await；單 frame 65,536 字元與單輸入 chunk 1 MiB 上限，非全系統容量承諾 |
| `… vitest run tests/research-proxy.test.ts` | cookie／Set-Cookie 被轉送、錯誤 path/method 放行、302 被照送 | 固定 POST `/agent/observe`／upstream、16 KiB request body 上限、Bearer-only forwarding、manual redirect、no-store；response body 串流傳遞 |
| `pnpm --filter @whisky/web exec playwright test tests/e2e/stream.spec.ts` | proxy 使用 response.text()，相隔 800ms 的兩 snapshot 在瀏覽器僅隔約 0.1ms | 改為 body pass-through；最後一次 API→本機 workerd→Chromium gap 790.5ms（門檻 >400ms），EOF 仍 needs_input；`stream-timing` attachment 與 test output 的 `stream-timing.json` 保存 152.3／942.8ms 時點 |
| 獨立 review 的 I/O error regression | 初始 fetch failure 洩出 raw TypeError；snapshot 後 body error 被標 INVALID_STREAM／不可重試 | I/O 邊界回安全 OBSERVATION_UNAVAILABLE／可重試，payload 格式錯誤與 caller abort 各自保留語意；review 回看關閉 |

既有 SDK 的空 interrupt 拒絕、其他 schema 保護與 fixture browser smoke 都記為回歸／整合驗證，不假造首次 RED。跨 Python subprocess 的測試使用 30 秒 test timeout、15 秒單次程序 timeout；一次 5 秒 test timeout 不算行為 RED。

契約生成：`uv run --project backend python scripts/export_openapi.py` 產生 OpenAPI＋TaskView JSON Schema；`pnpm --filter @whisky/web generate:contracts` 產生 TS 與 bundled standalone validator。Ajv 在 build-time 編譯，瀏覽器／Worker 不執行 schema compiler 或 eval。CI 從兩端重新生成並查 drift；生成兩次的內容 hash 相同。`rg -l 'TaskView|readEvents|observationProxy|waiting_event' backend/src backend/tests apps/web/src apps/web/tests scripts` 核對 production adapter、fixture、測試與 generator consumers。

版本 fence mutation：暫將 `state.view !== null && value.viewVersion <= state.view.viewVersion` 改為 false，`research-state.test.ts` exit 1；finally 還原後完整 suite 通過。

本機驗證：`uv run --project backend pytest backend/tests -q` 39 passed；Web Vitest 47 passed；production build 與 Playwright 3 passed；wheel 4 passed；ruff／format／mypy／TS／boundary／peers／actionlint 1.7.12 通過。過程中磁碟暫時不可寫，確認恢復後才重跑；Docker daemon 後來停止，因此 actionlint 改用本機同版本 binary，未啟停其他服務。本增量證據隨 T02 契約／串流基礎提交保存；遠端 CI 結果另記。

獨立複核：design 0 findings（改／記／提／駁回各 0）；一般 correctness review 1 個 P2，按 RED→GREEN 修正並回看關閉。

下一個 T02 增量：正式 observe 的 typed read-only input、owner／actor／token expiry 重驗、每使用者兩條連線、60 秒 lifetime／15 秒 heartbeat、2 秒 snapshot polling、重連與多 tab 整合；之後才接真 Auth0＋Workers VPC／具名 Tunnel，量 CPU／connection／memory。這些未通過前不標 T02 已驗收，也不展開 T03。現有 FastAPI/workerd fixture 只證明本機 transport，不證明 VPC、身份隔離或正式執行能力。

### T02 observe 增量進行中（2026-09-28）

- `d786941` 已推送；GitHub Actions run `36399701294` 的 backend／web job 各自 success（`gh run view 36399701294 --json status,conclusion,jobs`）。
- Auth0 CLI 1.36.0 已登入使用者選定的 tenant，建立 Whisky 專用 SPA（public client、authorization_code）與 RS256 API（900 秒 token、不開 offline access）；公開 identifiers 寫入 ignored `.env.local`。CLI read-back 已確認設定，尚不代表真 callback 或跨帳號驗收。
- `test_verified_access_preserves_signed_expiry`：RED 到期值為 0，GREEN 從已驗證 claims 回傳 expiry；既有 Principal 介面保留。
- `test_observation.py`：snapshot／owner／revision、只送更高版本、兩條連線上限、expired token 與 headers 前拒絕不存在 task，各自取得缺少行為的 RED 後 GREEN。heartbeat 使用可控 clock，RED 在第 16 秒仍未收到，GREEN 第 15 秒輸出 comment。取消及慢 consumer 釋放測試驗證既有 finally 防線，未宣稱另有 RED。
- 本次命令 `uv run --project backend pytest backend/tests/test_observation.py backend/tests/test_tokens.py`：22 passed；ruff 通過；`uv run --project backend mypy backend/src`：17 source files 通過。測試為 observation adapter 的受控 source／ASGI 測試，尚未接正式 HTTP route、真 DB actor 重驗或瀏覽器重連，不能替代這些 gate。

後續 HTTP／重連增量：

- `IdentityAccess` 抽出既有 JWT／內部 actor mapping，提供已驗證 expiry 與 live actor eligibility。真 PostgreSQL `test_live_access_rechecks_disabled_and_deleted_actor` 先 RED（停用仍 true），再 GREEN；原有身份與 owner 測試保持通過。
- 正式 FastAPI `/agent/observe` 與 Web 同名薄路由已掛載，input 由 OpenAPI 生成。HTTP RED 為 404／預期 200 或 401，GREEN 驗有效 JWT、跨 owner 404、額外 answer payload 422、缺設定 503／no-store。產品 source 尚未設定時 fail closed，T02 不提前建立研究持久表。
- actor 中途停用使用真 DB 與可控 polling clock；下一次讀 source 前拒絕，沒有第二份 snapshot。串流已開啟後的 DB 故障與資格失效按既有 SSOT 使用 `RUN_ERROR`，不變更 TaskView。CUSTOM 的初稿經獨立 review 發現契約偏差後撤回；RUN_ERROR assertion 先 RED 後 GREEN。
- `observeTask` 前端 adapter 已驗 EOF 只重新 observe、每次重取 token、暫時故障退避、資格失效停止、登出時晚到 token 不得開連線、已保存終態不重連。核心案例各取得 assertion RED 後 GREEN；登出案例是既有 abort fence 的回歸，不另宣稱 RED。尚未接產品研究 UI 或真瀏覽器重連 gate。
- 本機 `uv run --project backend pytest backend/tests`：56 passed（RUN_ERROR 修正後受影響 15 passed）；workerd Playwright 4 passed，新增正式 observe 路由從 404 RED 到 503/no-store GREEN。E2E build 明確把三個 NEXT_PUBLIC_AUTH0_* 設為空，避免 ignored 本機 tenant 設定改變 fail-closed fixture。
- design-review：1 項改（撤回未定義 CUSTOM、遵循既有 RUN_ERROR）、1 項記（process-local limiter 適用條件），提／駁回 0。沿用單程序計數是目前單 API process／instance 的明確選擇；增加 worker、replica 或新舊 API 重疊部署前，必須改為跨程序的原子限額並重驗多 tab gate。T02 部署不得使用多 worker／重疊 API。
- 真 Chromium／FastAPI／workerd 重連增量：新 browser test 先 RED（沒有第二次連線），接線後又抓到 native fetch receiver 錯誤（兩次重試但没有 snapshot），將 injected fetch 作獨立 function 呼叫後 GREEN。最終 Playwright 5 passed，包含兩次只讀訂閱、每次取得 token、舊版本不倒退、停止後完成清理；仍是合成 source，不取代真 Auth0／VPC。Web 51 passed、typecheck／雙端 boundary 通過；wheel 4 passed。
- 獨立 correctness review 未發現可重現 P1／P2；本輪仍未宣稱 T02 整體驗收。
- 部署前提再驗：VM root 約 125 GiB 可用、available RAM 21,832 MiB（SSH `df -h /; free -m; uptime; docker ps --format ...`）；沒有重啟或變更既有服務。Cloudflare VPC service list 為空，已建立專用 remotely managed named tunnel `whisky-discovery`，尚 inactive，尚未建立 service／connector 或宣稱能通。
- observe 增量提交 `360e0f6`；CI run `36402855031` 的 backend／web job 各自 success（`gh run view ... --json jobs`）。
- 部署設定進行中：`deploy/Dockerfile`／`compose.yaml`／runbook 已建立，固定 Python 3.13.13、uv 0.12.9、PostgreSQL 18 及 cloudflared 2026.9.0 的多平台 manifest digest。`docker compose --env-file deploy/.env.example -f deploy/compose.yaml config --quiet` 通過；本機 ARM64 image build 通過，image inspect 大小 78,362,467 bytes；唯讀、non-root UID 10001 下已安裝套件／migration assets／CLI liveness smoke 通過。這是本機容器證據，VM 尚未啟動此 stack；真登入／VPC／probe source 仍待接線。
- 後續實際部署：Oracle 上專用 `whisky-discovery` Compose project 的 DB／API healthy、migration exit 0、named Tunnel connector QUIC prechecks PASS；API image 對應 `360e0f6`。DB／API 沒有 host port，未更動既有服務。初次啟動抓到 YAML flow sequence 將 tmpfs 的逗號拆成兩個項目，改成 quoted string 後啟動成功；此為部署設定修正，不算行為 RED。token mount 依 image UID 65532 設定可讀，未把 secrets 加入 image 或 git。
- Workers VPC HTTP service 已指向此 Tunnel 的 `api:8417`，production `WHISKY_API` binding 已部署。Web：`https://whisky-discovery-web.fathompod.workers.dev`，Worker version `18a23938-71e8-4a6f-8bb0-354a5b14d67f`。真 HTTP `GET /api/v1/me` 回 401／`UNAUTHENTICATED`／`Cache-Control: no-store`，證明 Worker→VPC→API auth boundary 可達；不等於有效登入或 SSE gate 通過。部署 log `/tmp/whisky-worker-deploy.log`、VM `/tmp/whisky-vm-status.log`、HTTP `/tmp/whisky-live-me.headers`。Worker startup 12 ms 是啟動統計，不當成 request CPU 測量。
- Auth0 CLI 1.36.0 已經使用者完成 device login；建立此專案專用 SPA／RS256 API，設定 localhost 與正式 workers.dev callback。Chrome 真 Google 登入已到 Whisky Discovery Web 首次 consent，callback／refresh／logout／雙帳號及 VPC SSE 尚待驗證。`360e0f6` 遠端 CI run `36402855031` 的 backend 與 web jobs 各自 success。
- 後續 Google 驗收：使用者完成首次 consent 後，Chrome 正式 `/account` 顯示「帳號已連線」；reload 後先 loading，再恢复「帳號已連線」。API 的專用 users 表已有此帳號內部 UUID。尚未以這項結果代替 logout／雙帳號隔離及 SSE。
- 隔離 probe：`deploy/entry_probe.py` 只由額外 Compose override 掛載，固定 owner／task／run／revision、2 秒兩段 synthetic snapshot、重連維持新版，沒有研究持久寫入。`test_entry_probe.py` 首次 RED 為合法請求仍回 None；GREEN 後完整 backend 57 passed、Web 51 passed、mypy／ruff／TypeScript 通過。顯式 browser harness build 與 Compose 合併設定檢查通過；常規 Web build 不包含 harness。獨立唯讀 correctness review 沒有可重現 P1／P2。live probe 尚未部署／量測，完整 gate 仍待完成。
- Live probe 已執行，安全量測摘要見 [deploy/t02-entry-evidence.json](deploy/t02-entry-evidence.json)：Chrome→Worker→VPC→named Tunnel→API 的兩段 snapshot 在 614／2,608 ms 到達；約 62 秒只讀重連保留 v2／researching，page errors 0。兩頁持有連線時第三頁 429；停止第一頁後第三頁按退避重試成功 200。Google callback／reload／logout 均實測；跨帳號、live token expiry／slow consumer 仍待驗，不以本機測試代替。`4209109` CI run `36405523219` 的 backend／web jobs 各自 success。
- VM 小樣本 API 69.32 MiB／0.30% CPU、DB 33.45 MiB、Tunnel 15.2 MiB；inspection 時 DB idle 1＋查詢自身 active 1，命令與限制隨 artifact 保存。Wrangler tail 的整條 60 秒 observe 樣本 CPU 8 ms；`/account` SSR 樣本 13／43 ms。GraphQL 官方 API introspection 確認 `cpuTimeP50/P99` 單位為 microseconds，最近一小時樣本亦超過 Free 10 ms；不能宣稱 Free gate 通過。參照 [官方 metrics 說明](https://developers.cloudflare.com/workers/observability/metrics-and-analytics/)，成功 outcome 不代表每次 CPU 在門檻內。
- 原生 prerender 實驗：產物 gate 先 RED（缺 static shell），啟用 `vinext({prerender:true})` 後 build 在 bare Node 載入 `cloudflare:workers` 失敗，與 [上游 #2911](https://github.com/cloudflare/vinext/issues/2911) 相符。此相容性失敗不冒充 TDD RED；實驗設定已撤回，未 patch framework／改換綁定機制。依既定架構評估 OpenNext 替代，或由使用者選擇付費路線；T02 不標已驗收，T03 尚未開工。

### T02 Oracle Web 移轉 — 2026-09-28 已驗收

- 使用者改選 Oracle VM 部署 Web。原生 Next.js／Node standalone 容器負責頁面與固定 API proxy；保留 `workers.dev` 公開網址，薄 Worker 只經 VPC 轉送至 Web，Auth0／AG-UI／FastAPI／Temporal 契約不變。不採 OpenNext 或付費升級。
- 先完成：原 live probe API 已回復 normal command 且 healthy；臨時 Auth0 callback 已移除，正常 Web Worker version `542be883-e061-411f-9ac9-010dcc992ff2` 已移除合成 assets，GET `/__entry_probe` 真回 404。
- 固定 Node API adapter 的兩項測試先 RED（沒有可用 adapter／非法設定未拒絕）；初版轉送又由 assertion 抓到 POST 被變 GET，改成明確傳遞 method／body／headers／signal／manual redirect，2 passed。這不是以既有 proxy 測試代替 Node 行為。移除 vinext 與 Cloudflare Vite runtime；原生 Next build 已產生 `/`、`/account` 靜態頁，兩個私有 routes 保持 dynamic。
- 薄 Worker 兩項測試先 RED（轉送回 503／缺 no-store），GREEN 後 Web `pnpm --filter @whisky/web test` 55 passed；`test:e2e` 5 passed，包含真正 edge→Node→FastAPI 的重連串流。typecheck、boundary、原生 production build 與 edge dry-run 通過；薄入口 bundle 1.52 KiB。
- ARM64 standalone image 在唯讀／non-root 容器通過頁面 200、JS asset 200、缺 API 設定 503/no-store。Oracle VM 的獨立 Web container 已 healthy、沒有 host port；新 VPC target 指向 `web:3417`，公開入口尚未切換。API 仍為 `4209109`。
- 架構文件已對帳；fresh design-review 無設計發現，文件提醒已修正。複核未修改檔案；主 agent 查核兩個 checkout 的 status/log，未見 reviewer 的越界提交。
- 下列增量依序完成 CI、公開薄入口切換／回復、真 Auth0／live SSE gate 與 VM 資源量測；過程中的待驗敘述保留為歷史證據，最終結論見本段末。
- 公開切換增量：`87a835d` 已推送；CI run `36409074156` 的 backend／web jobs 各自 success。VM Web 使用 `87a835d` image、healthy；內部首頁／account 200，私人 API 401/no-store，Web 閒置 48.45 MiB（`docker stats --no-stream` 小樣本）。薄 Worker version `60275f37-3fe9-412b-8b6f-11855ba87879` 已上線，curl 正式首頁 200、私人 API 401；Chrome 新路徑 Google callback 已顯示「帳號已連線」。部署命令須為 `pnpm --filter @whisky/edge run deploy`，避免撞到 pnpm built-in deploy。完整新路徑 SSE／CPU、跨帳號及回復 gate 尚未完成。
- 新路徑 live 證據見 [deploy/t02-node-entry-evidence.json](deploy/t02-node-entry-evidence.json)：Chrome 兩段 snapshot 351／2,229 ms、約 62 秒只讀重連、第三頁四次 429 後在第一頁取消釋放名額時成功 200；page errors 空。薄 Worker tail CPU 小樣本回報 0 ms（整數精度，非零工作量）；不把 proxy wallTime 当完整串流時長。
- 真 token expiry：此專案 Auth0 API 暫設 90 秒 lifetime，harness 在記憶體固定 token，跨重連取得 200→200→401，UI AUTH_REQUIRED／disconnected 且 task 仍 researching；重新取 token 恢復 200。API lifetime 已 CLI read-back 恢復 900 秒。尚待第二個真身份與 live slow-consumer；首次嘗試核對仍為原 actor，沒有冒稱跨帳號成功，已新增明確 Google account chooser。
- 最終驗收：第二個真 Google 身份確認不同 actor，自身資料 200、原帳號資料與 task 404/no-store，沒有 snapshot。兩條真瀏覽器未讀 response 為 200／200、第三條 429，未取消前在 66,136 ms 新連線成功 200；這是目前 compact snapshot 的有界期限驗證，搭配本機 stalled-send 測試，不外推高流量 TCP 壓力。Probe URL 恢復 404、臨時 callback 移除、正常 API／Web healthy；舊 SSR rollback 與 thin Worker restore 各實測首頁 200／私人 API 401。
- `3e012f4` CI run `36410967590` 的 backend／web jobs 各自 success；Web 55 tests、typecheck 與 probe build 通過。獨立唯讀 T00–T02 requirement/evidence audit 無阻擋 gate 缺口，兩項紀錄對帳已補齊。T00–T02 已驗收，容量／持久研究／模型／還原仍依 T03–T12，不把入口驗收當產品完成。
- PR #1 的 GitGuardian incident 37686918 命中 `4209109` 中 Compose 的 `POSTGRES_PASSWORD: ${WHISKY_DB_PASSWORD:?...}` 必填變數宣告；該行沒有字面憑證。2026-09-28 使用者已在 GitGuardian 處理誤判；保存此查核紀錄並觸發新 head 檢查，不改寫歷史或跳過 security gate。

### T03 價格純規則 — 2026-09-28 進行中

- 前提沿用 PRODUCT_SPEC 的 TW／TWD 單瓶可比版本、每來源最新觀察、合格報價上緣與集中配置 30 日政策；不把來源撤價當作沒有新資料。Domain 採 Python dataclass／Decimal，沒有 ORM／Agent framework 依賴。
- `test_catalog_prices.py`：精確價格先 RED（None≠1500.50）→GREEN；draft 排除先 RED→GREEN；version／ABV／容量三個反例各 RED→GREEN；市場／幣別／條件價三個反例各 RED→GREEN；day 31／未來／缺日期各 RED→GREEN，day 0／30 保持可用；最新撤價及每來源最新→跨來源上緣各 RED→GREEN。
- `uv run --project backend pytest backend/tests/test_catalog_prices.py -q`：15 passed；affected ruff／mypy 與 Python boundary 通過。尚未建立 catalog persistence／migration／publication／真實資料，不把純規則視為 T03 完成；預算相等、台灣時區、缺資料與其他邊界、mutation、真 PostgreSQL 及人工覆核仍待依序完成。
- 後續預算邊界 RED（相等／關閉價格篩選被拒絕）→GREEN；台灣午夜與 naive timestamp RED→GREEN。現為 21 passed，ruff／mypy 通過。T01–T02 PR #1 的 GitGuardian 命中舊 commit `4209109` 的 Compose `POSTGRES_PASSWORD` 必填環境變數宣告，查核為非字面密碼；GitGuardian 登入／false-positive 處理尚待使用者完成瀏覽器登入，不改歷史或略過檢查，亦不阻擋獨立 T03 開發。


### T03 不可變 publication 增量 — 2026-09-28 進行中

- 價格資料驗證取得逐項 RED→GREEN：非法 amount／ABV／volume、未知 ABV／容量、同來源同時戳衝突；35 個價格案例通過。Publication 的 draft、缺來源／錯版本、缺展示欄位來源、重複識別與不合法日期各取得 assertion RED→GREEN；19 個案例通過。來源 facts 與 derived flavor tags 保持不同 domain 型別。
- 真 PostgreSQL：migration 缺表 assertion RED→GREEN；publish/read stub 的 None assertion RED→GREEN；直接更新五類 sealed component 與刪除 citation 的六個 assertion RED→GREEN。追加新 fact、後續 release 保留舊 item／evidence 引用、DB 中途錯誤完整 rollback 為既有防線驗證，沒有冒稱新 RED。`uv run --project backend pytest backend/tests/integration/test_catalog_store.py -q`：11 passed。
- 同 transaction 發布並 seal；component trigger 鎖定 parent release 後拒絕 sealed 寫入，複合 FK 綁定 release／item／evidence／bottle version。沿用 UUID、SQLAlchemy Core、Alembic 的理由是既定 PostgreSQL 與不可變引用契約；domain 不依賴 ORM，未新增 queue／cache／extension。
- Mutation：暫將 `<= policy.maximum_age_days` 改成 `<`，以及移除 price reviewed filter，各取得 1 failed／34 passed；還原後價格＋publication unit 54 passed。日界線與 draft 排除不是僅跑正常輸入的綠燈。
- 完整 `uv run --project backend pytest backend/tests -q`：122 passed；ruff check／format、mypy 21 source files、Python boundary 通過；`python3 scripts/test_wheel.py` repo 外安裝與 Temporal tests 4 passed，migration head 驗為 `0002_catalog`。本增量未套用到 VM。
- 獨立 design-review：覆蓋 ID／snapshot／transaction／seal trigger／FK／fact-tag／型別／錯誤／migration，共 0 findings（改 0、記 0、提 0、駁回 0）。T03 仍待價格 persistence、查詢用例、真實樣本人工覆核及資料隔離，不宣稱已驗收。
- GitGuardian：使用者已處理 Compose 變數宣告誤判；新 head `c63fb9c` 的 GitGuardian 與 backend／web checks 全部成功，PR #1 已合併為 `8b5c888`。先前「等待 false-positive 處理」為當時紀錄，現已解除。
- 獨立 correctness review 找到兩項 P2，均修正：非法 URL port／本機 literal host 可發布、等值 ABV decimal 字串被誤拒。7 個回歸 assertion 先 RED→GREEN，publication unit 現 26 passed；URL 僅做靜態格式／literal host 檢查，不宣稱完成 T08 的 DNS／redirect SSRF 防線。Domain／migration／store 的既有主鍵與 FK 路徑保持不變。
- 修正後完整後端驗證：`uv run --project backend pytest backend/tests -q` 129 passed（87.47s）；ruff check／format、mypy 21 source files、Python boundary 再驗通過。


### T03 價格持久化、查詢與人工覆核 — 2026-09-28

- `PublishedPrice` 綁定 immutable release／item／evidence；新增 migration `0003_catalog_prices`，以既有 seal trigger 保護價格 snapshot，精確 Numeric 保存金額。查詢固定最新 sealed release，再共用純 `qualified_prices()`，不在 SQL／prompt 重寫資格規則；保留來源引用，不把舊 release 價格回填到新版。
- TDD：price citation 的 item／evidence／source／bottle／draft／capture／duplicate 7 個 assertion RED→GREEN；真 PostgreSQL round-trip stub 與候選查詢 empty stub 各取得 assertion RED→GREEN。日期 30／31、關閉預算、跨 release 撤價、不可變價格為既有規則的 DB 整合驗證；外部 SQL 將 price 指向其他 bottle evidence 被真正 FK 23503 拒絕。
- Manifest 明確宣告 schema version／real／reviewed／reviewer／aware review time。載入 stub RED→GREEN；10 個 draft／synthetic／缺 reviewer／非法時間／未覆核條目的 assertion RED→GREEN。CLI `whisky-catalog-publish` 先驗 manifest 再連 DB，不在 API startup 或 Agent 自動發布；重送同 release ID 明確拒絕，更新另建 snapshot。
- 三款真實資料與 fixtures 分離於 `data/catalog`；原 draft 保留，reviewed 檔包含來源、版本、40%／700ml、台灣參考價及整理標籤。使用者明確回覆「已核對，同意三款資料與 30 日政策」，時間與來源見 `data/catalog/REVIEW.md`；格蘭菲迪 15 因條件不明保持 unconditional=false，不進嚴格預算候選。
- 真 PostgreSQL 匯入 reviewed 檔，TWD 1000 候選為格蘭菲迪 12（978）與格蘭利威 12（816），關閉預算有三款，每個 fact／tag evidence 可解析。這是人工覆核後 snapshot 的查詢證據，不宣稱即時庫存或售價。
- 獨立 design-review 0 findings，覆蓋 UUID／seal／FK／transaction／manifest／CLI／讀一致性與 query 規模。correctness review 找到 P1 缺欄位套合格預設與 P2 價格日期不符來源，6 assertion RED→GREEN；移除 domain 的市場／幣別／條件預設，非空 price.checked_on 須與 evidence.checked_on 相同。consumer 盤點 `rg -n 'PriceObservation\(' backend` 為 store 與兩個 fixture constructors，均已確認明確傳值。
- 第一輪完整後端 155 passed；新增直接 FK 反例另 1 passed，review 修正後 affected unit 85 passed；最終完整結果接續記錄。ruff／mypy 23 source files／Python boundary 通過，repo 外 wheel 4 tests 通過、migration head `0003_catalog_prices`。未套用到 VM；T03 收口仍以最終驗證與 CI 為準。
- 最終完整後端 `uv run --project backend pytest backend/tests -q`：162 passed（42.45s）。抽出共用規則後再執行日期／reviewed mutations，各 1 failed／34 passed；還原後 35 passed。ruff format 49 files、diff whitespace 檢查通過。
- 完成前對照 PRODUCT_SPEC「最小資料契約」發現仍需補：來源 publisher、風味整理 method/version，以及真實酒款的 brand／正式名稱／適用市場與明確版本欄位；現有 URL、name、ABV、容量、年分與 tag citation 不等於完整 metadata。T03 保持進行中，先補此契約差集再進入 T04。PR #2 保存目前增量，不以價格測試通過取代上述剩餘要求。


### T03 metadata 差集收口 — 2026-09-28

- 發布契約補齊 publisher、風味整理 method/version、item reviewed_on；brand／official_name／market／version_label 是有來源引用的必要 facts，未提供 alias 仍為未知，年分未知不當成 NAS。9 個缺值／未來日期 assertions 先 RED→GREEN；metadata DB 讀回遺失 assertion RED→GREEN。
- Migration `0004_catalog_provenance` 以 nullable 擴充保留舊 snapshot 的未知值，新發布強制欄位完整。新 metadata 不改写原 release：`first-journey.v1.reviewed.json` 與 `git show 2aa306a:data/catalog/first-journey.reviewed.json` byte-identical；current 檔使用新 release ID／published_at。既有人工覆核內容僅結構化為欄位，未新增品飲或價格結論。
- `uv run --project backend pytest backend/tests -q`：171 passed（23.82s）；真 DB catalog tests 20 passed，另補 legacy-null metadata 可解析但不可重新發布的 test，1 passed。`python3 scripts/test_wheel.py`：4 passed，打包 migration head 為 `0004_catalog_provenance`；ruff／mypy 23 source files 通過。
- 原 T03 兩次 fresh design-review 無設計發現；本次欄位補全由未參與實作的既有 reviewer 追加獨立 correctness／SSOT 對帳，無新增缺陷與阻擋出口缺口。嘗試新 reviewer 遇 host thread limit，沒有冒稱此次另啟 fresh agent，也沒有由作者扮演獨立 reviewer。
- 人工覆核、30 日政策、真 DB／mutation／不可變引用／draft 隔離出口已有證據；本次提交 CI 成功後可驗收 T03，接續 T04，不把 T03 當作完整產品或 live deployment 驗收。

- T03 最終 CI：head `84c7bb3` 的 push run `36434196560` 與 PR run `36434203958`，各 backend／web job 均 SUCCESS，GitGuardian SUCCESS。PR #2 已合併為 `ec3ff9b`。T03 已驗收；開始 T04。T03 migration／資料尚未部署到 VM，該工作隨後續持久研究部署驗證進行，沒有宣稱 live catalog 已上線。

### T04 前提盤點 — 2026-09-28

- 沿用 ARCHITECTURE 的 DB receipt＋穩定 workflow ID、Temporal 接受確認與明確 running/closed ID 政策；這是跨 DB／Temporal 的非原子邊界，不自建 queue 或 scheduler。完成後重送仍由既有 receipt 返回，不依賴 Temporal retention 永遠保留 history。
- 已核對 [Temporal workflow ID／run ID](https://docs.temporal.io/workflow-execution/workflowid-runid) 與 [Python Client.start_workflow](https://python.temporal.io/temporalio.client.Client.html#start_workflow)；實際 policy 與 start response loss 將用已固定 SDK 和真 Temporal 驗證，不以文件或 mock 當通過。

### T04 第一段 — identity generation 與 Temporal start adapter

- 真 PostgreSQL RED：將既有 actor generation 更新為 7，同一已驗證 token 再登入仍未取得 generation（`None != 7`）；`/tmp/whisky-t04-generation-red.log`。補上內部 Actor／AccessSession 的 persisted generation，公開 `/me` JSON 不變；登入／停用／跨帳號與 observation 整合 `13 passed`，`/tmp/whisky-t04-generation-green.log`。
- 真 Temporal RED：SDK 預設 conflict policy 導致並行／回應遺失後重送衝突，預設 reuse policy 讓已關閉工作重開，`3 failed`，`/tmp/whisky-t04-start-red.log`。adapter 依 persisted task UUID 組成固定 workflow ID；workflow type 固定、queue 由 server composition 提供，running 採 USE_EXISTING、closed 採 REJECT_DUPLICATE 並查回既有 run。
- GREEN：`uv run pytest tests/integration/test_research_start.py -q` → `4 passed`，包含並行受理、terminated 後重送、真 worker 完成後重送、真 server 接受後由 client interceptor 注入回應遺失；`/tmp/whisky-t04-start-green.log`。完成 fixture 僅驗受理，不執行研究、不代表 T05 通過。
- Mutation：將 REJECT_DUPLICATE 暫改為 ALLOW_DUPLICATE，completed retry 測試因不同 run ID 失敗；`/tmp/whisky-t04-start-mutation.log`。已恢復原 policy。Temporal retention 外的防重仍必須由後續持久 receipt 保證。
- 本段尚未接入 HTTP／DB task receipt，未部署；T04 仍進行中。接續 discovery typed 條件與 plan、owner／revision／generation 的交易檢查、唯一 receipt 及 acceptance_pending→queued 對帳；目前 adapter 的 server acceptance 不等於完整 T04 出口。
- 還原 mutation 後，`uv run pytest tests/integration/test_identity.py tests/integration/test_observation_http.py tests/integration/test_research_start.py -q` → `17 passed`（`/tmp/whisky-t04-increment-green.log`）；ruff／format、mypy（24 source files）與 `scripts/check_python_boundaries.py backend/src` 通過。

### T04 第二段 — typed 條件與 plan 建立 receipt

- 條件 RED：推測／未知可誤成硬限制、空白欄位、缺版本起點、等值金額 hash 不一致與 mutable snapshot，`10 failed, 5 passed`（`/tmp/whisky-t04-conditions-red.log`）。GREEN：frozen typed schema 保存 entry／goal／版本化起點、prefer／keep／change／avoid、certainty／strength，未知與推測不提升為硬限制；TWD 預算為正有限 Decimal、最多 18 位數／2 位小數，None 表示關閉預算。另有極端 exponent／不足一分金額 `2 failed` 的 RED（`/tmp/whisky-t04-budget-bounds-red.log`），防止 canonical fixed-point 輸出無界膨脹。
- plan 真 DB RED：初建、同 key／payload、不同 payload、跨 owner、停用／generation、並行去重 `6 failed`（`/tmp/whisky-t04-plans-red.log`）。GREEN：0005 migration 建立 plans 與 discovery 所有的 discovery_commands；後者是垂直流程 logical command_receipts 的模組內實作，scope 固定 plans.create，owner／scope／key 唯一，完成結果與 target 同 transaction 保存。未建立共享可寫 receipt service 或自建 queue。
- 交易按 identity→command→plan 次序；identity 公開契約用 caller connection 鎖定並驗當前 generation，catalog 公開契約查 reviewed／sealed 起點，discovery 不操作他模組 ORM／表。receipt→plan 使用 deferred 複合 FK 保證 owner 一致；真 DB 直接篡改 owner 回 23503，receipt 寫入後注入中斷會整筆回滾，重送可成功。
- 起點不存在原先誤受理的 RED `1 failed`（`/tmp/whisky-t04-plan-reference-red.log`）已修復；published fixture 引用可 round-trip。plan 改版後 create 重送原先回 revision 2 的 RED `1 failed`（`/tmp/whisky-t04-plan-receipt-result-red.log`）已修復：receipt 保存初建結果，不從可變 plan 重建當時回應。
- 最終受影響測試 `uv run pytest tests/integration/test_plans.py tests/test_research_conditions.py -q` → `27 passed`（`/tmp/whisky-t04-plans-final.log`）；ruff／format、mypy 28 source files、模組邊界檢查通過。wheel 以獨立環境驗 migration head 0005 與 executable/Temporal `4 passed`（`/tmp/whisky-t04-plans-wheel.log`）；後续 receipt 欄位變更仍須以最終完整測試核對。
- fresh t04_plan_design 對 ID／schema／跨模組公開契約／鎖定順序／receipt／條件／索引／migration 的設計審查回 NO DESIGN FINDINGS。T04 尚未完成：下一段接研究 task／receipt、舊 revision 拒絕、DB commit→Temporal start 中斷恢復與 HTTP／AG-UI command 接線；本段沒有部署或宣稱完整受理出口通過。
- 最終 `uv run --project backend pytest backend/tests -q` → `204 passed`（`/tmp/whisky-t04-plans-final-full.log`），涵蓋 receipt result 的最後變更。同一未參與實作 reviewer 複核最後差集及 correctness，未發現缺陷；主 agent 核對 repo／second-brain status 與 log，沒有 reviewer 寫入。

### T04 第三段 — 持久研究 receipt 與 Temporal 對帳

- 前一增量 head `191391b` 的 push run `36436948716`、PR run `36436997269` 各 backend／web job 均 SUCCESS，GitGuardian SUCCESS；PR #3 保持 draft。
- 真 DB RED `6 failed`（`/tmp/whisky-t04-receipts-red.log`）：reserve 尚未保存 receipt／task、owner／revision／key 未保護。0006 建立 research_tasks 與 research 所有的 research_commands；identity→plan 的公開交易契約保留鎖到提交，保存起始条件／generation／revision、獨立 thread ID、固定 task-derived workflow ID、write fence 與 view version。task→plan、receipt→task 複合 FK 綁 owner。
- 初次 migration 測試因 DDL 少一個結尾括號失敗，屬實作錯誤而非行為 RED；修正後重跑真 DB。受理確認與 receipt result 同 transaction 保存；pending→queued 才推進 view version，worker 已進入 researching 時不倒退。
- 聯合真 PostgreSQL／Temporal RED `4 failed`（`/tmp/whisky-t04-acceptance-red.log`）；GREEN `4 passed`（`/tmp/whisky-t04-acceptance-green.log`）：DB commit 後、start 前中斷沿同 key 恢復；真 server 接受後由 interceptor 丟棄回應，DB 保持 acceptance_pending，重送找回原 run；並行同 command 只留一個 task／workflow；完成後 accepted receipt 直接回原結果，故意不可用的 starter 不會被呼叫，不依賴 history 永久保留。完成 workflow 是明示 fixture，只驗受理，沒有宣稱 Agent／報告已驗收。
- RPC timeout／暫時性 UNAVAILABLE、DEADLINE_EXCEEDED、UNKNOWN、RESOURCE_EXHAUSTED 保留 pending；其他 RPC error 仍傳出，async cancellation 不吞掉。不啟用 background task／scheduler，不把 DB 有一列當 Temporal 已接受。DB 同步 I/O 經 asyncio.to_thread，network start 在 transaction 外。
- 追加真 DB 案例驗 generation／停用後不得讀寫、pending 舊 revision 不可重啟但 accepted receipt 可回歷史結果、receipt 與 task 中斷整筆 rollback、跨 owner FK 拒絕。write fence 在 receipt SELECT 後才關閉的 RED `1 failed`（`/tmp/whisky-t04-confirm-fence-red.log`）已以 UPDATE predicate＋RETURNING 修復，不能只信先前讀到的 fence。
- 最終 core suite `uv run pytest tests/integration/test_research_receipts.py tests/integration/test_research_acceptance.py tests/integration/test_research_start.py -q` → `20 passed`（`/tmp/whisky-t04-research-core-green.log`）。全後端 `220 passed`（`/tmp/whisky-t04-acceptance-full.log`）；wheel head 0006／安裝執行 `4 passed`（`/tmp/whisky-t04-acceptance-wheel.log`）；ruff／format、mypy 32 source files 與模組邊界通過。
- 未部署；HTTP／AG-UI start mapping、command 查詢及 production observation source 仍待接線，T04 不提前驗收。
- fresh t04_acceptance_design 設計審查提出 1 項沿用機制簡化：research 已先在 identity lock 下完成查詢去重，不需複製 plan 的 receipt-first／deferred FK。採納為「改」：task 先 INSERT、receipt 後 INSERT，使用 immediate 複合 FK。第二筆失敗整筆回滾測試先取得 RED `1 failed`（`/tmp/whisky-t04-task-first-red.log`），修改後隨下述最終 core suite 重驗。
- 同一獨立 reviewer 的 correctness review 提出 P2：pending receipt 遇到已完成 task，不能因 Temporal history 超過 retention 而再次 start。補上真 server 接受後丟回應、workflow 完成、明示 fixture 代替 T05 原子 report commit、ForbiddenStarter 的 regression；write fence true／false 均先 RED `2 failed`（`/tmp/whisky-t04-pending-completed-red.log`）。現在 reserve 在 owner／generation／hash 驗證後，由產品 completed snapshot 補齊 receipt acceptance，不修改 task／view version／fence、不再碰 Temporal。core 最終 `22 passed`（`/tmp/whisky-t04-research-core-final.log`）。這證明重送不依賴 retained history，未宣稱已跑過真 Agent 發布報告。
- reviewer 複核確認兩項均收口，最後差集無新增 correctness finding；設計發現 1 改、correctness 發現 1 修復，無駁回或待決。
- 最後完整驗證（含審查修正）：`uv run --project backend pytest backend/tests -q` → `222 passed`（`/tmp/whisky-t04-acceptance-final-full.log`）；獨立 wheel → `4 passed`（`/tmp/whisky-t04-acceptance-final-wheel.log`），ruff／format、mypy／boundary 再次通過。主 agent 已核對 shared repo 的 status／log，未發現 reviewer 寫入。

### T04 第四段 — plan HTTP／Web proxy 與公開錯誤

- head `206c417` 的 push run `36439236076` 與 PR run `36439242980` 各 backend／web job 均 SUCCESS，GitGuardian SUCCESS。
- plan HTTP RED `8 failed`（`/tmp/whisky-t04-plan-http-red.log`）：端點尚不存在。新增 `POST /api/v1/plans`／`GET /api/v1/plans/{id}`，由 verified actor 建立與恢復 plan，client owner／額外欄位拒絕；同 key 回初建結果、異 payload 409、跨 owner 與 missing 同 404，私人回應 no-store。GREEN `8 passed`（`/tmp/whisky-t04-plan-http-green.log`）；正式 configured_app 與無外部連線的 schema app 都已組裝端點，生成 OpenAPI／TypeScript。
- Web plan proxy RED `3 failed`（`/tmp/whisky-t04-plan-proxy-red.log`）；新增 feature allowlist、POST JSON body 轉送與 GET UUID resource。identity／discovery 共用一般 private transport，固定 origin、10 秒 deadline、client cancellation、manual redirect、header allowlist／no-store；SSE 保留獨立生命週期。相關 proxy／upstream `14 passed`（`/tmp/whisky-t04-plan-proxy-green.log`），Web 全套 `62 passed`，typecheck／boundary／Next build 通過。
- fresh t04_plan_http_design 發現 1 項 B：adapter 與 bootstrap 重複維護公開錯誤 code/status。採「改」：adapter 將已知 domain failure 轉 PublicAPIError，bootstrap 僅統一格式化；普通 HTTPException 仍不公開任意 detail。新測試先 RED `2 failed, 1 passed`（`/tmp/whisky-t04-public-error-red.log`），包含普通 exception 冒用已知 code 仍須 fallback；修後 public errors＋plan HTTP `11 passed`（`/tmp/whisky-t04-public-error-green.log`）。獨立 reviewer 已確認設計收口，並完成 correctness 複核，無新增缺陷。
- 本機第一次 E2E `4 passed, 1 failed` 是 build 讀入 ignored `.env.local` 的公開 Auth0 設定，但 unconfigured fixture 預期未設定。依既有規約以 `NEXT_PUBLIC_AUTH0_DOMAIN= NEXT_PUBLIC_AUTH0_CLIENT_ID= NEXT_PUBLIC_AUTH0_AUDIENCE= pnpm --filter @whisky/web build` 重建，不修改正式設定；`pnpm --filter @whisky/web test:e2e` → `5 passed`（`/tmp/whisky-t04-plan-http-e2e-green.log`）。這是既有入口／SSE 回歸，不宣稱完整新 plan UI 旅程。
- 最終 `uv run --project backend pytest backend/tests -q` → `233 passed`（`/tmp/whisky-t04-plan-http-final-full.log`），獨立 wheel `4 passed`（`/tmp/whisky-t04-plan-http-final-wheel.log`）；ruff／format、mypy 35 source files、Python boundary 通過。shared repo status／log 已核對，未見 reviewer 寫入。
- T04 仍進行中，未部署本增量：計畫 bounded cursor 列表、研究 task／command 查詢、production observation source 與 AG-UI start mapping 尚待接線，不以本段 plan CRUD 代替完整研究受理驗收。

### T04 第五段 — 有界計畫列表

- 真 DB RED：`test_plans.py -k 'page'` 缺少 page 行為 6 failed；HTTP RED：`test_plan_http.py -k 'list or pagination'` 的 GET collection 為 405，10 failed。Web RED：`vitest run tests/plan-proxy.test.ts tests/upstream.test.ts` 有 9 failed，涵蓋 query 被拒絕或被兩層 transport 丟棄。
- GREEN：PlanStore 以 owner／當前 active generation 限定資料，使用 `(updated_at, id)` keyset、預設 20／最多 50 筆及 limit+1；同時間以 ID 穩定排序。HTTP 使用 versioned JSON／base64 cursor，拒絕未知及重複 query、無效 limit／cursor；跨 owner 即使沿用 cursor 仍無法讀他人資料。cursor 只表示位置，不作授權，也不承諾跨頁固定 snapshot。
- Web feature allowlist 開放 GET collection 的 limit／cursor，兩層固定 origin transport 保留已驗 query；identity／observe 仍拒絕 query。OpenAPI／TypeScript 重新生成，沒有手寫第二份 schema。
- 驗證命令：`uv run --project backend pytest backend/tests -q` → 249 passed（63.24 秒）；`pnpm --filter @whisky/web test` → 71 passed；`pnpm --filter @whisky/web test:e2e` → 5 passed（13.8 秒）。ruff／format、mypy、Python／Web 邊界、Web typecheck、Next build 通過；build 按既有 fixture 指令清空三個公開 Auth0 build vars。
- fresh t04_pagination_design：NO DESIGN FINDINGS；覆蓋 ID／索引、keyset、cursor encoding、generation、唯讀交易、query 驗證、shared transport、其他 consumer 與生成契約；改／記／提／駁回均 0。主 agent 核對最終 diff 與兩個共享 tree 的 status／log，無 reviewer 越界修改。
- 前段 head `2f63910` 的 push／PR runs `36441049266`、`36441057207`，backend／web jobs 均 SUCCESS。本段尚未部署；T04 繼續研究 task／command 查詢、production observation source 與 AG-UI start mapping。
