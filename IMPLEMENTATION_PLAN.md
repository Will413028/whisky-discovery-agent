# TDD 實作計畫

更新：2026-09-28。狀態：規劃完成、尚未執行。依 [產品規格](PRODUCT_SPEC.md)、[架構](ARCHITECTURE.md) 與 [垂直流程設計](VERTICAL_SLICE.md) 實作；保留 Next.js／AG-UI／PydanticAI／Temporal、業務模組與 `backend/src/whisky/`。本文件管理細項執行證據，既有主待辦管理產品優先順序，不建立另一份 roadmap。

## 開工前對帳與狀態規則

每次接續先執行 `git status --short`、`git log -5 --oneline`，核對上述三份設計及本表；命令須在實際 repo 根目錄執行。若版本、前提或其他人的變更影響下一項，先讀差異，不重跑已完成工作或覆蓋未提交內容。各階段按照相依順序執行；發現設計矛盾先修契約，不用測試固定矛盾行為。

| 主待辦對應 | 細項 | 進度 |
|---|---|---|
| 技術入口 | T00–T02 | 未開始 |
| 持久研究骨架與樣本 | T03–T09 | 未開始 |
| 雙入口與探索計畫 | T10 | 未開始 |
| 比較、回訪與資料管理 | T11 | 未開始 |
| 展示資料與完整驗收 | T12 | 未開始 |

狀態可為未開始、RED、GREEN、REFACTOR、已驗收、受阻。只有本階段的必要自動化與外部 gate 均通過才標已驗收；blocked 的整合不得用 mock 結果代替。此輪只規劃，不建立應用目錄、下載依賴、開通服務或存取 secrets。

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

## T02 — AG-UI 與 Workers／VPC 最小入口

相依：T01。本階段只用明示的測試狀態來源，不建立完整研究流程。

- RED：兩段延遲 snapshot 被緩衝到最後才抵達；EOF 被顯示為完成；interrupt 被當 success；新 run 的 resume payload 不能通過兩端 SDK schema。
- GREEN：固定 TaskView 契約、AG-UI adapter、串流 proxy 與最小前端狀態處理；observe 僅訂閱，不執行 start／answer。
- RED→GREEN：重複／較舊 view version、不同 task／revision 被丟棄；斷線後 observe 恢復；過期 token、慢 consumer 與多 tab 連線有界。
- 出口：真 workerd／Workers → VPC → API 的瀏覽器 flush 時間證據、page errors、登入與重連；記錄 CPU、connection／memory 用量。SDK 相容或 VPC gate 不過就重評，不能繼續宣稱部署路線成立。

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

尚無。此文件僅完成計畫整理；第一個執行項為 T00，不能將文件連結／Markdown 檢查寫成應用的 RED 或 GREEN。
