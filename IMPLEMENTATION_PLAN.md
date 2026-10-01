# TDD 實作計畫

更新：2026-10-01。狀態：T00–T09 已驗收，T10 進行中。Oracle 原生 Next.js／Node、薄 Worker→VPC→Web→API 已通過真 Google callback／跨帳號隔離、SSE／重連／取消／token 到期／未讀 consumer 期限與入口回退；T03 catalog／人工覆核、T04 可靠受理、T05 durable Agent、T06 等待補充／跨程序恢復、T07 控制命令與 T08 真來源／模型／配額已通過各自出口。T09 空庫／WAL 還原、正式登入／跨帳號／控制／重啟恢復、告警收件與首次 default-branch schedule 均已通過，正式 control 開關已放行。T10 的新 input／proposal schema、V4 executor 與 Web slice 尚未部署或整體驗收。依 [產品規格](PRODUCT_SPEC.md)、[架構](ARCHITECTURE.md) 與 [垂直流程設計](VERTICAL_SLICE.md) 實作，保留 AG-UI／PydanticAI／Temporal、業務模組及 `backend/src/whisky/`。本文件保存細項證據，不另立 roadmap。

## 開工前對帳與狀態規則

每次接續先執行 `git status --short`、`git log -5 --oneline`，核對上述三份設計及本表；命令須在實際 repo 根目錄執行。若版本、前提或其他人的變更影響下一項，先讀差異，不重跑已完成工作或覆蓋未提交內容。各階段按照相依順序執行；發現設計矛盾先修契約，不用測試固定矛盾行為。

| 主待辦對應 | 細項 | 進度 |
|---|---|---|
| 技術入口 | T00–T02 | 已驗收；自動化、真 Auth0／Node／VPC 及隔離／串流 gate 證據見文末及 deploy/t02-node-entry-evidence.json |
| 持久研究骨架與樣本 | T03–T09 | 已驗收；首次實際 schedule 與正式 control 放行證據見 T09 文末 |
| 雙入口與探索計畫 | T10 | 進行中；公開 catalog／可靠 patch／plan與history UI／proposal slice 已本機 GREEN；完整雙入口與模型／部署出口仍待完成 |
| 比較、回訪與資料管理 | T11 | 保存結論／私人回訪的本機增量實作中；T10 未驗收，完整 T11 出口仍待完成 |
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

### T10 執行契約與前提核對（2026-09-30）

- T09 PR #8 已合併至 `c209f8d`；`availability.yml` 的 workflow state 為 active，首次 default-branch schedule 尚未出現。此期間先做獨立契約／RED 與不依賴私人資料放行的公開 catalog adapter，不提前標 T09 或 T10 驗收。
- 從目前限制重新設計：UUID 只作穩定實體識別，owner／generation／revision 才是授權與寫入門檻；immutable release／item 保持精確版本與历史引用；Temporal 保持唯一持久 executor。既有三項機制與本案需求一致，保留。
- V1 `ResearchConditions` 已能表達 entry、精確 starting bottle、喜好／保留／改變／排斥、certainty／strength 與本次 budget。T10 不改其 frozen codec／digest；typed patch 只改指定欄位，最後由既有 `plan.change_conditions` receipt／外部紀錄套用整份正規化條件。自然語言草稿與點選都產生同一 patch，確認才提交，預算仍只在本次 plan。
- 模型偏好草稿分開保存於 discovery，保留原描述、推測與目前 revision。日常食物描述不能自動升為 user_stated；硬限制要由使用者明確啟用。新行為以新 workflow／activity schema 執行，保留 V1–V3 executor／prompt／payload，重跑舊 history replay。
- 公開 `GET /api/v1/catalog` 只回目前 sealed reviewed release、精確版本、sourced facts、編輯標籤方法與引用、政策合格價格；匿名可讀，private plan／task／report 仍驗身份。資格不明的價格要明示，不能從參考報價推論嚴格預算資格。
- 新手描述先展示待確認偏好卡；熟手搜尋名稱先確認明確版本，庫外名稱明示未收錄。候選最多三款，保留／差異連到已覆核 evidence；「少煙燻」缺一致比較尺度時提供未知與可改條件的出口，不用缺標籤當作較少。
- plan 畫面保留上一輪 report 與 revision 標示，修正後明確由使用者另建 research task；重送同 receipt，舊 SSE 不能改新 task／revision，未完成結果不能存成新條件結論。讀取失败不得被呈現為空清單或已保存。
- 2026-09-30 RED：`uv run --project backend pytest backend/tests/integration/test_public_catalog_http.py -q` 在真隔離 PostgreSQL／migrations／三款 reviewed release 上 2 failed；匿名 catalog 期望200實際404，缺設定期望503實際404。這是入口缺失的行為 RED，venv／依賴準備不算 RED。
- 公開 adapter GREEN：同一真 DB 測試 3 passed；新增過期資格投影補證沿用已受測 domain 規則，舊參考價格仍有查核日但 qualified=false／upper bound=null。Web route 最初匿名200與POST405期望各收到404（2 RED），加入無 credentials 的固定 upstream 後2 GREEN。UI 最小介面先無卡片／錯誤（3 RED），完成讀取與錯誤出口後3 GREEN；非HTTP來源仍顯示卡片的反例先RED，再從 Pydantic pattern→JSON Schema→AJV validator 生成後 GREEN。Vitest 檔名未被收集、錯誤 envelope 名稱誤用與 Next route-announcer selector 歧義只算測試準備修正，不算產品 RED。
- 已驗 backend `pytest backend/tests -q` →459 passed（303.34秒）、wheel4、ruff check／format、mypy73 files、Python boundaries（root=backend/src）。Web 完整Vitest111，新增URL反例後catalog相關6 passed；typecheck／boundaries／Next build通過。原 TaskView schema／validator 生成物 `git diff --numstat -- contracts/task-view.*` 無差異。Node/workerd 原7條E2E通過，新增鍵盤catalog案例修正selector後單獨重跑1 passed；完整T10新手／熟手／修正旅程仍未完成，catalog尚未部署。
- design-review：新鮮唯讀 reviewer 對 base `c209f8d` 核對 ID／sealed release、transaction、價格、匿名 transport、cache、schema generator、client lifecycle，0 findings（改／記／提／駁回均0）；AGENTS.md 路徑與現行規則對帳0處修正。review未檢查尚未實作的私人T10草稿，也不拿設計結論代替正確性測試。
- `b2f1c54` 的 push run `36667581648`／PR run `36667672605`：backend jobs各success（3m34／4m14）、web各success（1m22／1m35）、GitGuardian pass；draft PR #9 尚未合併。T09 main push run `36665005129` 的 public-readiness job success，但 event=push，不取代 first schedule。已啟动有界背景觀察，只有實際 schedule run 的 job結論才作出口。
- `backend/evals/t10_cases.v1.json` 在首次T10真模型呼叫前保存13條語料與定性rubric；JSON解析及case ID唯一性通過（`python3`讀JSON並印`len(cases)`／`runs_per_case`，13／2）。來源為產品契約與T08／T09已知負例，沒有從T10模型輸出改題；尚無runner／執行结果／人工評分。對照T08原始corpus與兩份result各12筆，T08是六題×兩次×兩模型的24次研究流程對照，不能稱為24次模型呼叫。
- 條件 patch 的獨立 domain 契約：先用最小介面取得10個行為RED，再以 `model_fields_set` 區分省略／明確null、偏好exact-description upsert／explicit remove，最後交回既有V1條件驗證，10 GREEN。重複修改與舊資料同description多intent的歧義再取得2個RED；現明示 `DUPLICATE_PREFERENCE_EDIT`／`AMBIGUOUS_PREFERENCE`，明確移除該description後才可替換，不默默選第一／最後一筆。V1 codec、外部hash與舊history未改；此helper尚未接command或UI，不冒充條件修正旅程完成。
- `pytest backend/tests/test_condition_patch.py backend/tests/test_research_conditions.py -q` →29 passed；完整 `pytest backend/tests -q` →471 passed（265.96秒），wheel4、mypy74 files、ruff與Python邊界通過。以記憶體載入mutant將未指定偏好全部移除，原baseline偏好保留assertion確實不再成立；未更動實際source／DB／API。只有這輪獨立規則已GREEN，owner／receipt／revision的整合仍須接既有可靠command後驗證。
- `da656ae` push run `36672457600`／PR run `36672461396` 的 backend、web jobs 各自 success；PR backend 4m28、web 1m20。T09 首次 main schedule 仍未出現；有界觀察首次終止後重新直接查 API 得空清單，新的觀察固定個人 GitHub token 於單次 process，不改全機 active account。
- V4 選取規則尚未接 workflow／UI：最初六項真 DB 行為 RED→GREEN；keyword 原型另取得英文品牌反例 RED，版本／hard／inferred／起點衝突與 V3 回歸22項GREEN。design-review 找到 raw goal 解析與單一加減分策略兩項問題，已捨棄該原型：最終政策只接受 `ExplorationIntent` 明確 query／mode／探索特徵，不直接解讀 `conditions.goal`，來源為 reviewed 名稱与有 evidence 的正向 claim。
- 策略重構先取得四項RED（typed search、similar 正向共同證據、small-step 保留／探索、缺探索證據不替換）；其後16項政策＋4項 configured agent 測試共20 GREEN。後續追加起點 keep evidence 缺失、文字不同不足以支持contrast、明確雙端descriptor／axis三項RED；已改成兩端保留證據與 `FlavorContrast`／`ContrastEvidence`，最新定向GREEN尚在執行，不能拿上一版結果宣稱最終版通過。
- 累積design-review ledger：B raw goal解析 fixed；A 單一score取代探索策略 fixed；第二輪B 品飲文字不等代理contrast fixed。第三輪review `NO DESIGN FINDINGS`，三項皆已核對、不只看最後一項；不把readonly設計結論代替測試。cross-module `CatalogReference` 由 discovery.public 公開；V1 codec、V1–V3 policy／workflow／prompt未更改。mypy75 files與Python邊界通過；AGENTS.md現行路徑／進度指向對帳0處修正。
- 重構前完整回歸482 passed／1 failed（547.43秒）：configured agent 的 Temporal ephemeral server 五秒未啟動，屬環境錯誤，不列行為RED；其定向4項重跑已通過。同期wheel驗證失敗，原始完整trace未保存，不能推定是同一原因；最終序列重跑已通過，見下列log。環境失敗不算行為RED，最終回歸也不代替尚未接線的T10旅程驗收。
- 最終政策定向 `pytest .../test_research_selection_v4.py .../test_research_selection_policy.py .../test_configured_agent.py -q` →33 passed（243.68秒，`/tmp/whisky-t10-selection-final.log`）；ruff check／format、mypy75 files、Python邊界通過。明確標示的synthetic in-memory fixture中，baseline拒絕無comparison relation的contrast，移除gate的mutant錯誤列候選而被同一assertion偵測；不寫正式catalog／source／DB。完整最終pytest →490 passed（339.22秒，log `/tmp/whisky-t10-backend-final.log`）；完成後序列重跑wheel →4 passed（19.02秒，log `/tmp/whisky-t10-wheel-final.log`），避免同時啟動多組Temporal測試server。
- 政策 commit `69445f9` 的 push／PR runs `36675964874`／`36675969088`，backend jobs各success（4m12／4m23）、web各success（1m27／1m25）、GitGuardian pass。尚未接正式workflow，不把規則GREEN當完整T10結果。
- typed patch HTTP 接線：原缺路由使「固定body重送／只改預算」與「偽造base不得改未指定欄位」兩項行為RED（404≠202／409）；現新增 `POST /api/v1/plans/{id}/conditions/patch`，帶key、expectedRevision、baseConditions及patch，從固定base正規化成整份V1 command，首次受理在owner／plan lock內核對base／revision；已有receipt先按原digest重播。不是重讀最新DB後重新解讀patch，也未新增patch ledger／DB schema／外部codec。前端與自然語言草稿的確認都將使用此入口，UI／NL仍待接線。
- patch／既有控制HTTP／commands定向19 passed（14.03秒，`/tmp/whisky-t10-patch-final.log`），其中登入401、跨owner404、revision409沿用舊保護、無須另改fence。另patch與舊restore定向18 passed（26.21秒，`/tmp/whisky-t10-patch-restore.log`）：明示isolated DB rewind，以V1全紀錄重建同receipt後，原base／patch重送200、同ID、revision保持2；不冒充live pgBackRest還原。
- Web private proxy 的新增路由／method兩項RED（404≠202／405）→2 GREEN；完整Vitest114、typecheck、Web邊界、原生Next build、Node/workerd Playwright8（10.8秒）通過。OpenAPI→TypeScript已生成，TaskView／CatalogView schema與validators `git diff --numstat -- contracts/task-view.* contracts/catalog-view.*` 無diff。記憶體mutation略過base equality，真DB HTTP負例202≠409確實失敗；driver核對該call assertion，而非只看pytest非零exit，source／正式資料未變動。
- patch intake fresh design-review檢查ID、snapshot、receipt／V1 codec、鎖序、跨模組、Pydantic各邊界、Temporal執行權威、錯誤、proxy／cache與生成契約，`NO DESIGN FINDINGS`（改／記／提／駁回均0）。共享樹status／log核對未見reviewer寫入；second-brain同期其他專案commit與修改保留。mypy75、ruff與Python邊界通過。
- 首輪完整後端493 passed／1 failed（373.80秒，`/tmp/whisky-t10-patch-backend-full.log`）：既有resume綁定案例503≠200，單獨模組4 passed（21.45秒）。沒有只凭重跑GREEN判定環境問題：記憶體注入首筆read延遲60ms，原50ms ObservationPolicy確實重現同一503斷言（`/tmp/whisky-t10-first-read-delay.log`）；該案例目的為resume原task綁定，改採與start案例相同2秒policy後，相同60ms注入1 passed（10.96秒，`/tmp/whisky-t10-first-read-delay-green.log`）。正式Observer／服務時限未改；完整後端與wheel仍須以修改後版本序列驗證。
- 研究入口未完成task清單的503原被catch成空清單，違反T10讀取失敗不得呈現為空清單的契約。元件測試先取得missing alert RED（`/tmp/whisky-t10-open-tasks-red.log`），現顯示獨立錯誤與「重新讀取探索」，成功重讀後清除錯誤並恢復既有task link；重試不建立plan／task，登出清除私人清單與錯誤，既有live／abort fence保留。研究元件8 passed（`/tmp/whisky-t10-open-tasks-green.log`）；完整Web驗證仍待最終結果。
- 本輪最終驗證：完整後端494 passed（242.72秒，`/tmp/whisky-t10-patch-backend-final.log`）、repo外installed wheel4 passed（14.74秒，`/tmp/whisky-t10-patch-wheel-final.log`）。Web完整Vitest115 passed／19 files（6.58秒）、typecheck／Web boundary／原生Next build及Node／workerd Playwright8 passed均通過。patch command／proxy與任務清單錯誤修正可提交；NL proposal、V4正式executor、plan UI與新手／熟手真瀏覽器旅程仍待完成，未部署、不提前標T10驗收。
- `2043e20` 已提交／推送；push run `36680036782`、PR run `36680039378` 的backend／web job各自success。此版本完成partial command／proxy，不把後續尚未提交的plan畫面當成該CI已覆蓋。
- plan management UI：plan client四項stub行為RED（`/tmp/whisky-t10-plan-client-red.log`）；詳細頁的讀取錯誤重試、固定patch body／key、只改預算及確認新revision後另開研究兩項RED（`/tmp/whisky-t10-plan-ui-red.log`）；清單分頁與opaque cursor再取得兩項RED（`/tmp/whisky-t10-plan-pages-red.log`）。現 `/plans`／`/plans/{id}` 為薄routes，研究入口有計畫連結；首次讀取／翻頁失敗不冒充空清單，已讀頁保留；change command pending不顯示保存成功或自動另開研究，未確認回應重送固定指令，completed後讀回authoritative revision。新研究仍由使用者明確啟動，遺失回應重送同thread／run／key；subject／route／登出生命週期fence清除舊回應。client6＋UI5定向11 passed（`/tmp/whisky-t10-plan-races.log`）；生命週期與研究重送為保護性回歸，不冒充另外兩次最初RED。
- 生成schema驗出Decimal validation pattern可接受non-money；改採response serialization schema後，又驗出V1 serializer回傳str只產生無格式string。wire格式測試先missing-pattern RED（`/tmp/whisky-t10-budget-wire-red.log`）；現只在原serializer回傳型別補schema metadata，正文／runtime／normalization未改，Pydantic生成PlanView／PlanListView／ControlView→standalone AJV，納入CI drift；沒有保留custom exporter workaround或browser手寫domain規則。conditions／patch／wire定向30 passed；四種V1canonical payload與control hash同`2043e20`逐byte一致，科學記號輸入仍正規化1000、0.01與大額小數維持原輸出。記憶體schema mutation只移除budget pattern，使同一invalid-money rejection assertion失敗；未變更source／DB。
- 本輪後端完整495 passed（299.44秒，`/tmp/whisky-t10-plan-backend-full.log`）、installed wheel4 passed（15.04秒，`/tmp/whisky-t10-plan-wheel.log`）；ruff／format、mypy75 files與Python邊界通過。Web完整126 passed／21 files（7.17秒，`/tmp/whisky-t10-plan-web-final.log`）、typecheck／boundary／Next build通過。boundary曾擋住cross-feature內部import，已經research public index修正，保留原gate。Node／workerd Playwright9 passed（11.5秒，`/tmp/whisky-t10-plan-browser.log`），新增合成API browser旅程驗重開plan、改預算、固定body重送與revision2另開研究；不是T10真Auth0／真Temporal／真模型出口。
- plan UI／response metadata fresh design-review最終`NO DESIGN FINDINGS`，核對ID／receipt／V1 codec、precision、schema generation、Auth0／no-store、lifecycle、pagination、typed patch與Temporal權威、public feature入口／薄routes及pending scope；共享樹status／log核對未見reviewer写入，second-brain同期其他專案commit與變更保留。指令檔對帳0處變更。
- 獨立correctness review累積ledger：public feature boundary已fixed（boundary gate）；P2「pending receipt只GET，無法補啟動未建立workflow」已fixed（pending／無receipt重送固定POST，其餘已知啟動階段GET）；P2「確定409永遠重送舊revision」已fixed（typed409／422 rejection在尚無receipt時提供最新plan重讀出口，transport維持同key，有receipt時不假稱未受理）。三個review行為先RED（pending、409、422，`/tmp/whisky-t10-plan-review-red.log`），修正後client8＋UI8定向16 GREEN（`/tmp/whisky-t10-plan-ledger-green.log`）；reviewer複核前三項fixed且未見產品新defect。另SSE fixture雙backslash疑點駁回：原檔double-backslash+n數為0、single數4，尾端ASCII `[125,41,125,92,110,92,110,96,32,43]`，是合法TS newline escape而非literal反斜線；工具JSON／repr雙重顯示造成誤判，無改程式。此scope correctness改2／駁回1／open0；既有public boundary不得退化。
- 最終review修正後Web完整131 passed／21 files（9.23秒，`/tmp/whisky-t10-plan-web-reviewed.log`）；Next build、typecheck、Web boundary均成功，Node／workerd Playwright9 passed（8.9秒，`/tmp/whisky-t10-plan-browser-reviewed.log`）。最新plan browser fixture明示三次同body POST，第三次completed／revision2才允許另開研究，包含在此9項。NL proposal、V4 durable executor、歷史report／revision呈現、新手／熟手真模型與真瀏覽器驗收仍待完成，未部署、不提前標T10驗收。

- 研究歷史 slice：新增 owner-only `GET /api/v1/plans/{plan_id}/tasks`，沿既有 created_at＋UUID keyset，limit 1–50／opaque versioned cursor，拒絕未知／重複 query。deleted／foreign／missing／generation 不符 plan 為404；原 TaskView、V1 codec與既有 report保持不變。新 `TaskHistoryView` wrapper 獨立提供建立時間，不把 observedAt 的重讀時間當研究日期；Pydantic→OpenAPI→TypeScript／standalone AJV與CI drift均已接線。
- 真 PostgreSQL RED→GREEN：history未實作時第一案例404≠200（`/tmp/whisky-t10-history-red.log`）；8項通過（`/tmp/whisky-t10-history-green.log`），驗 revision1完成報告在plan revision2後保留、同時戳UUID分頁、invalid cursor／limit／duplicate query、匿名401／foreign及刪除404。連同既有research讀取18 passed（26.92秒）。記憶體移除plan可見性檢查的mutation，foreign history200≠404被同一整合測試抓到（`/tmp/whisky-t10-history-mutation.log`）；不修改產品檔或正式資料。
- Web history：plan detail列原task revision／createdAt／report link；首次失敗不偽裝空清單、翻頁失敗保留已有項目、同cursor重讀，subject／plan／logout fence阻擋晚到回應。proxy、history UI、generated nested task validation、report revision文字分別取得RED，logs為`/tmp/whisky-t10-history-{proxy,ui,client,report}-red.log`。合成browser journey驗revision2 plan重開revision1 report，不是live Auth0／真模型出口。
- fresh history design-review：`NO DESIGN FINDINGS`；獨立correctness累積ledger唯一P2「同頁修改後保留needs_input旧狀態」已fixed：revision觸發首頁重讀與舊頁fence。新回歸原版1 failed（`/tmp/whisky-t10-history-review-red.log`），修正history4 passed（`/tmp/whisky-t10-history-review-green.log`），reviewer複核open0。跨三共享樹status/log確認reviewer未寫入；second-brain其他會話內容保留。適用指令檔路徑／現行規則對帳0處更改。
- 最終完整後端503 passed（280.79秒，`/tmp/whisky-t10-history-backend-full.log`）、installed wheel4 passed（12.24秒，`/tmp/whisky-t10-history-wheel.log`）；ruff／format、mypy75 files與Python boundaries通過。review修正後Web140 passed／23 files（`/tmp/whisky-t10-history-web-reviewed.log`）、typecheck／boundary／Next build及Node／workerd Playwright10 passed（10.6秒，`/tmp/whisky-t10-history-browser-reviewed.log`）。history本機完成、未部署；NL proposal、V4 durable executor、新手／熟手真模型與真瀏覽器出口仍待完成，不標T10驗收。首次default-branch schedule查詢仍為空（`gh run list --workflow availability.yml --event schedule --limit 3 --json databaseId,status,conclusion,headSha`），不以push CI替代T09 schedule gate。

- 研究頁帳號隔離修正：原元件只依 authenticated 狀態，subject 切換但仍登入時會保留舊報告／未完成清單／私人描述；late plan response 還可能接續舊帳號研究。三項行為回歸取得 RED（`/tmp/whisky-t10-research-owner-red.log`，3 failed）；現以 subject＋authenticated＋taskId 為 session key 重建私人畫面，非同步 submit 使用 lifetime generation fence。12 項 GREEN（`/tmp/whisky-t10-research-owner-green.log`），另加 task route 切換立即隱藏舊報告，定向13 passed。獨立 correctness review 無 findings，檢查 late token／plan／start／answer、StrictMode 與原 SSE／polling cleanup；Web完整144 passed（`/tmp/whisky-t10-owner-web-full.log`）、typecheck／boundary／Next build已通過，瀏覽器 gate仍執行中。未部署，不能取代真跨帳號驗收。
- V4 immutable input／偏好草稿 slice 尚在實作：task start digest 包含結構化 intent／phase／原描述，舊 start canonical digest不變；新 proposal 只能產生 inferred／soft 建議，明確選取才轉 ConditionPatch。真 DB 中 draft與question同transaction發布，question kind 區分版本與偏好，偏好 answer不得冒充報告的酒款版本。已取得各行為 RED→GREEN 與移除 input digest 的記憶體mutation反例；完整後端回歸／fresh design review尚在執行，正式V4 workflow、model與UI仍未接線，不標T10完成。
- 本轮完整後端回歸發現 public import 提前載入 proposal DB store，導致舊 Temporal sandbox 驗證失敗；已確認34 failed後以 SIGINT 結束本人測試程序保存trace（233 passed，226.07秒，`/tmp/whisky-t10-v4-contract-backend-full.log`），不是環境錯誤。改成與既有 public DB function 相同的延遲載入，舊 research workflow＋新proposal發布定向10 passed（34.34秒，`/tmp/whisky-t10-proposal-sandbox-green.log`），mypy79 files成功，完整回歸重跑中。fresh design review 此input／proposal／question kind slice 為 `NO DESIGN FINDINGS`，改／記／提／駁回均0；尚未覆蓋未實作executor。Web Node／workerd Playwright10 passed（15.1秒，`/tmp/whisky-t10-owner-browser.log`），仍是合成API旅程，不冒充live跨帳號。
- V4 slice 行為證據：input persistence stub RED（`/tmp/whisky-t10-v4-input-red.log`）；proposal source／selection methods 6 failed／1 passed RED→19 passed（`/tmp/whisky-t10-proposal-contract-{red,green}.log`）；原子發布 stub RED（`/tmp/whisky-t10-proposal-publication-red.log`）；proposal answer被當版本的 `CLARIFICATION_MISMATCH` RED→新舊發布／report／answer HTTP合計21 passed（`/tmp/whisky-t10-proposal-report-kind-red.log`、`/tmp/whisky-t10-proposal-publication-green.log`）。移除V4 digest內input的記憶體mutation被兩個conflict assertion抓到（`/tmp/whisky-t10-v4-input-mutation.log`）。DDL JSON literal缺空格造成SQLAlchemy bind解析錯誤、測試誤用accept方法，都屬實作／harness錯誤，沒有計為行為RED。
- 修正sandbox import後完整後端519 passed（306.99秒，`/tmp/whisky-t10-v4-contract-backend-final.log`）。correctness review唯一P2 summary上限未預留question說明空間：boundary先1 failed／7 passed（`/tmp/whisky-t10-proposal-summary-red.log`），max_length改1600後unit8 passed，連同真DB最大長度完整發布／重送合計12 passed（11.22秒，`/tmp/whisky-t10-proposal-review-green.log`）；review複核open0，沒有重解旧Temporal payload。此小型validator變更後採受影響定向測試，不把先前完整519宣稱為含新增兩項boundary的521。研究頁修正commit `b43bd16`，尚未部署；正式V4 execution與T10出口仍未完成。

- 最終installed wheel4 passed（18.05秒，`/tmp/whisky-t10-v4-contract-wheel-final.log`，head0014）、ruff check／format、mypy79 files與Python邊界通過。frozen conditions_v1／control v1_codec／TaskView生成物差異核對無變更；指令檔路徑及現行規則對帳0處修改。新input／proposal tables尚未部署，保留PR draft，后續正式接線仍須真Temporal等待／重啟／replay及真模型人工rubric。

- V4 durable executor 本機接線：新增獨立 workflow／proposal與source agents，begin與immutable input同transaction；proposal引用須精確來自原描述、一次修正仍失敗就拒絕，明確 use-intent／skip 才接續，不自動修改已確認偏好或預算。proposal agent stub取得3 failed RED→3 GREEN（`/tmp/whisky-t10-proposal-agent-{red,green}.log`）；begin_v4 stub兩項RED→新舊begin／workflow9 GREEN（`/tmp/whisky-t10-execution-v4-{red,green}.log`）；durable question stub 1 failed RED→1 GREEN（`/tmp/whisky-t10-proposal-workflow-v4-{red,green}.log`）。restart test初次的result_type harness錯誤與Temporal server啟動逾時不列行為RED。
- 真PostgreSQL＋Temporal驗proposal問題持久化、停止／重啟worker後同question與deadline、明確採用／略過intent、庫外起點空結果、plan未被推論修改、model／reader quota ledger及同一Task完成；實際完成history以禁止provider的Replayer重播。完整backend530 passed（572.05秒，`/tmp/whisky-t10-v4-executor-backend-full.log`）；其後design finding刪除未使用focus，V4自有source schema納入prompt hash，受影響V4 workflow／proposal unit／legacy V2 replay共9 passed（116.27秒，`/tmp/whisky-t10-v4-focus-review-green.log`）。installed wheel4 passed（29.49秒，`/tmp/whisky-t10-v4-executor-wheel.log`）、mypy83 files、ruff check／format與Python boundaries通過。未將小型schema修正後的定向測試冒充第二次完整530。
- fresh executor design review 1A（沿用V3 focus但renderer未使用）決定改，刪除focus與指示後複核fixed；V3不改。獨立有界correctness review `NO CONFIRMED DEFECTS`，涵蓋transaction／owner／revision／取消fence、durable waiting／restart／replay、quota、舊registration與payload相容性；指令檔對帳0處更改。source fallback兩次上限已寫入，專用failure→success案例仍未驗；比較metadata／API start_v4／proposal cards與完整雙入口、真模型人工rubric／真瀏覽器／部署出口尚待完成。此slice未部署，不標T10驗收。
- input／proposal commit `da5b11d` 的PR run `36698828206` 與push run `36698822944`，backend／web jobs各自success；不把該CI當成後續executor的驗證。

- V4 比較 artifact（2026-10-01，本機）：新增schema4附表與獨立view，不改V1 ReportView／舊Temporal payload。保存共同／探索／contrast的雙端claims、品牌描述與來源ID，讀取以saved release／evaluated date解析來源，不把未知強度或缺標籤當差異。新artifact stub取得3 RED→policy與artifact22 GREEN（`/tmp/whisky-t10-comparison-artifact-{red,green}.log`）；store stub兩項RED／baseline一項GREEN→新舊report13 GREEN（`/tmp/whisky-t10-comparison-store-{red,green}.log`）。read stub兩項RED→本scope5 GREEN（`/tmp/whisky-t10-comparison-read-{red,green}.log`），包含foreign／missing／generation隔離、plan revision變更後仍保留歷史與HTTPS來源。
- migration設計前真SSH查schema0012／reports3／tasks5；真隔離DB觀察0014／reports0／tasks0，未假設兩環境對稱。新0015為additive table，report/task/owner複合FK與JSON schema／候選上限；測試以合成前版schema0012報告shape升至head，舊報告讀回不變且不擅自補V4metadata。初次rehearsal以新版ReportStore在0012寫入，因不存在kind column失敗，改用明確前版wire fixture；這是harness版本前提修正，不計產品行為RED。
- workflow仍用Temporal單一權威；新whisky_save_report_v4將report／comparison／Task completed／turn success同transaction提交，依DB immutable input與明確proposal答覆重建intent，重算已覆核selection及引用，不信任傳入的comparison。實際workflow缺metadata先1 failed RED（`/tmp/whisky-t10-comparison-workflow-red.log`）→4 GREEN（63.60秒，`/tmp/whisky-t10-comparison-workflow-green.log`）；prompt hash其後納入artifact schema，V4 workflow／proposal unit／V2 replay最新9 passed（54.12秒，`/tmp/whisky-t10-comparison-execution-final.log`），同命令另有fixture選取setup error，已將該legacy等待案例單獨重跑1 passed（9.05秒，`/tmp/whisky-t10-comparison-wait-retry.log`），不把harness error當產品RED。
- 累積review ledger：design 1B「research直接讀discovery proposal表」已改成discovery公開typed query，同connection且owner／generation／revision範圍；primary 2P2「鎖前existed查詢讓並行legacy報告被補掛metadata」以真DB barrier先取得RED（未拋COMPARISON_MISSING，`/tmp/whisky-t10-comparison-race-red.log`），改由持鎖_save回傳created，拒絕舊artifact補掛。新舊report共16 GREEN（59.89秒，`/tmp/whisky-t10-comparison-race-green.log`），獨立review複核兩項fixed／open0，舊save仍只回SavedReport。共享樹核對保留其他會話變更；AGENTS現行規則對帳同步既有指令整理兩處，歷史仍由ARCHITECTURE／計畫持有。
- 本機全套兩次遇啟動期限：首輪3 failed／176 passed後SIGINT保存trace（827.33秒，`/tmp/whisky-t10-comparison-backend-full.log`；兩個Temporal server五秒、一個worker就緒20秒），三個失敗案例序列重跑3 passed（38.23秒，`/tmp/whisky-t10-comparison-environment-retry.log`）。第二輪-x為1 failed／157 passed（500.35秒，`/tmp/whisky-t10-comparison-backend-final.log`），仍為Temporal dev server五秒啟動；該案例後單獨GREEN如上。實查本機load約70、swap約23–26GB，未停止其他會話程序或放寬產品行為。ruff check／format、mypy86 files、Python boundaries、frozen V1 codec／contracts差異與diff check通過；完整驗證改採既有隔離CI runner，結果未出前不宣稱全套GREEN。installed wheel4 passed（16.23秒，`/tmp/whisky-t10-comparison-wheel.log`，head0015）；API／UI、reviewed-tag偏好映射、來源fallback專項、真模型／人工rubric／真瀏覽器與部署出口仍待完成。

- 比較 core commit `a4c090f` 的 PR run [`36743201010`](https://github.com/Will413028/whisky-discovery-agent/actions/runs/36743201010) backend／web jobs 均 success；真 CI backend **539 passed（247.21秒）**、installed wheel4 passed（6.43秒），Web 包含原生 Next build 與 Node／workerd Playwright。這補齊前述本機負載下未完成的完整 core 驗證，不把環境逾時當產品 RED。
- comparison API／Web（2026-10-01，本機）：真 DB HTTP 兩項期望200／401卻404，先取得2 RED（`/tmp/whisky-t10-comparison-http-red.log`），新增 owner-scoped `GET /api/v1/reports/{id}/comparison` 後2 GREEN（23.76秒）；保持舊schema1報告與跨帳號404／no-store。固定 Web proxy 新路徑先404 RED→GREEN，client stub8 RED→8 GREEN，Pydantic serialization schema→OpenAPI／TypeScript／AJV standalone validator 統一生成，CI檢查新增schema drift；client核對reportId／taskId，401不冒充舊報告無artifact。
- comparison UI stub2 RED→2 GREEN；重開完成Task的接線先缺比較內容1 RED→GREEN。呈現起點／候選各自已覆核描述、引用與查核日期；庫外起點保留未收錄與待確認，未從缺標籤推導強弱。比較讀取與immutable V1摘要分開，錯誤可獨立重試；沿用actor／task keyed session、live fence與abort。定向31 GREEN，完整Web **156 passed（29.04秒）**、typecheck、boundaries、原生Next build、Node／workerd Playwright **10 passed（19.8秒）**；ruff check／format、mypy86 files、Python boundaries、diff check通過。
- fresh comparison API／UI design-review：`NO DESIGN FINDINGS`，檢查UUID／owner、獨立V4 view相容契約、固定private upstream／no-store、generated validation、錯誤分類、immutable双讀取與React生命週期；改／記／提／駁回均0，指令檔現行規則對帳0处修改，共享原checkout與second-brain其他會話變更保留。此slice仍未部署；正式V4 start、偏好卡／reviewed-tag映射、fallback專項、真模型人工rubric／瀏覽器／部署出口仍待完成，T10維持進行中。

- comparison API installed wheel **4 passed（26.35秒）**（`/tmp/whisky-t10-comparison-api-wheel.log`，head0015）；原TaskView生成物與frozen V1 codec差異核對無變更。API／UI slice完整backend由推送後的隔離CI核對，不把新增HTTP兩項與上一版539相加冒充一次完整執行。

- comparison API／UI commit `72123dc` 的 PR run [`36746849168`](https://github.com/Will413028/whisky-discovery-agent/actions/runs/36746849168) backend／web jobs均success；backend **541 passed（263.80秒）**、installed wheel4 passed（6.29秒）。這是該slice完整CI出口，仍未部署或標T10驗收。
- V4正式start接線（2026-10-01，本機）：`start_v4`先於真DB／JWT HTTP取得1 RED（合法命令回422）／invalid-input baseline1 GREEN（`/tmp/whisky-t10-agent-start-v4-red.log`）。加入獨立V4 parser與typed reserve後，immutable原文／intent、同receipt重送與變更原文409保留既有受理政策。起初20ms合成SSE lifetime未留下初始snapshot而IndexError，改回既有2秒policy，屬harness修正，不列產品RED。
- persisted executor dispatch先取得3 RED（缺typed lookup／adapter注入），以task的immutable V4 input決定V3／V4，bootstrap注入同模組lookup；重送request不指定任意workflow，沿用lazy Temporal client／同ID USE_EXISTING／closed history對帳。V4 start／dispatch／legacy HTTP定向9 GREEN（36.17秒，`/tmp/whisky-t10-start-v4-final-green.log`）；HTTP→真PostgreSQL→真Temporal V4 proposal workflow另3 GREEN（14.43秒，`/tmp/whisky-t10-http-v4-temporal-green.log`），原Plan不被模型推論改寫。最後V4 HTTP／dispatch／proposal等待重啟與frozen V2 replay共12 GREEN（71.20秒，`/tmp/whisky-t10-start-proposal-execution-green.log`）；使用合成provider，不當真模型品質證據。首個組合命令誤寫不存在的replay路徑、無測試收集，亦不列RED。
- 偏好草稿read投影stub取得8 RED／foreign-missing baseline1 GREEN（`/tmp/whisky-t10-proposal-read-v4-red.log`）；同一REPEATABLE READ snapshot經identity／discovery公開契約核對owner／generation／revision，只在仍可寫且needs_input的active pending、未過期preference question公開原文與草稿。API缺路由2 RED→真DB HTTP／read **11 GREEN（44.93秒）**（`/tmp/whisky-t10-proposal-api-final-green.log`）。初次把question pointer／answered欄位寫成非法測試狀態，既有DB constraints已保護；改用合法researching／cancelled轉換與真reserve_answer／accept_answer，未放寬constraints。
- Web proposal proxy缺新路徑1 RED→GREEN，proposal client stub10 RED→10 GREEN（`/tmp/whisky-t10-proposal-client-{red,green}.log`；連proxy共18 GREEN）；generated schema驗證並核對task／question／revision／waiting version，401與依賴錯誤不冒充無草稿。StartCommandV4公開typed component的validation defs用Input後綴，保留response serialization schema；未改TaskView或V1–V3 payload／workflow。此slice提供read client，卡片／條件套用仍在後續，不將helper驗過等同產品旅程。
- fresh start／dispatch與proposal read／HTTP／generator／client設計審查均0 findings，改／記／提／駁回均0；shared checkout與second-brain其他會話變更保留。此slice本機Web完整**167 passed（10.07秒）**、typecheck／boundaries／原生Next build通過；ruff check／format、mypy87 source files、Python boundaries、frozen生成物差異與diff check通過；installed wheel **4 passed（14.65秒）**（`/tmp/whisky-t10-start-proposal-wheel.log`，head0015）。完整backend與最新Node／workerd出口待CI／下述結果，不冒充T10真模型人工rubric／真瀏覽器／部署通過。

- 最新Node／workerd Playwright **10 passed（47.7秒）**（`/tmp/whisky-t10-start-proposal-e2e-green.log`）。前次8個browser案例在launch前因全機cache的executable不存在而失敗，未執行產品assertion；依本session既有下載授權，以 `PLAYWRIGHT_BROWSERS_PATH=/tmp/whisky-playwright-browsers pnpm --dir apps/web exec playwright install chromium` 安裝專案獨立暫存cache後重跑通過，未改產品或測試assertion，也不推論原cache消失根因。原start／dispatch審查追加StartCommandV4生成物，累積0 findings／open0。

- `e6f5565` PR CI run `36751734332` 的 backend／web jobs各自success；backend實際558 passed（267.60秒）、wheel4 passed（6.44秒）。這是V4受理與草稿讀取slice的CI，不取代T10完整旅程。
- 偏好映射新增 typed reviewed anchor：保留原描述與 source_quote，標籤引用含 release／item／evidence IDs，模型建議仍為 inferred／soft；使用者明確選取才以 canonical feature key 產生條件 patch，硬限制與預算另行確認。純規則7 RED→GREEN、context2 RED＋空庫baseline1 GREEN；Agent typed context缺失3 RED→3 GREEN，未提供／缺失映射重試一次後拒絕，不捏造來源。logs為 `/tmp/whisky-t10-{preference-mapping,proposal-context,proposal-mapping-agent}-{red,green}.log`。
- 真DB publication最初會接受偽造標籤／item／evidence（三項 DID NOT RAISE RED，合法引用baseline1 GREEN）；保存邊界現於原caller交易內独立驗證，拒絕後 task仍researching且草稿／問題皆0筆，4 GREEN（`/tmp/whisky-t10-mapping-publication-green.log`）。首次測試relative import與實作錯誤import只屬準備／實作修正，不計行為RED。
- mapping設計審查唯一B「借完整研究snapshot做純風味驗證」已改為catalog公開窄 `reviewed_flavor_references` 與專用V4 activity，V3 activity不動；複核 `NO DESIGN FINDINGS`，累積改1／記0／提0／駁回0／open0。窄query先空tuple1 RED＋空庫baseline1 GREEN，再驗 sealed／reviewed精確citation與不讀catalog_prices；沒有增加價格依賴或跨模組表操作。
- 真Temporal暴露sandbox model class身分使相同引用比對失敗；改按release ID／item ID與evidence集合比對，持久等待／重啟4 GREEN。窄query改後 publication／proposal workflow／真HTTP→Temporal 11 passed（24.28秒，`/tmp/whisky-t10-mapping-narrow-integration.log`）；偏好／Agent／context／frozen replay18 passed（1.44秒，`/tmp/whisky-t10-mapping-unit-replay-final.log`）。混排測試路徑曾出fixture scope收集錯誤，分開integration與unit後通過；不把收集錯誤當產品RED。
- 窄query改動前完整backend575 passed（315.51秒）、wheel4 passed（18.72秒）；改後mypy88 source files、ruff check／format與邊界通過，完整backend／wheel須由最新檢查覆蓋。生成契約只擴充V4 proposal mapping，舊TaskView／V1 conditions codec及V1–V3 executor不變；未部署，T10新手／熟手與偏好卡完整旅程、真模型rubric仍待驗收。
- 窄query最終2 passed（5.45秒，`/tmp/whisky-t10-flavor-query-green.log`），installed wheel4 passed（11.80秒，`/tmp/whisky-t10-mapping-narrow-wheel.log`）。獨立correctness唯一P2「合法17 citations被草稿16上限拒絕」先1 RED／3 baseline GREEN，移除無SSOT依據的上限後context／mapping／Agent14 GREEN（1.03秒），仍要求非空UUID、完整相符集合與模型配額；schema／OpenAPI／TS／validator同步，複核 `NO CORRECTNESS FINDINGS`，改1／駁回0／open0。
- 最終完整backend **578 passed（289.95秒）**（`/tmp/whisky-t10-mapping-backend-reviewed.log`）；ruff check／format177 files、mypy88 files、Python boundaries與diff check通過。這是映射slice本機出口；雙入口Web仍是後續未提交變更，不計入此後端版本或T10驗收。

- 映射 commit `dc74daf` 的 PR／push runs `36759753734`／`36759747585` backend、web jobs各success；PR backend實際 **578 passed（275.72秒）**、wheel **4 passed（6.75秒）**。這是已提交後端slice的CI證據，仍未部署。
- Web雙入口接線：新手保留原描述並使用typed V4 proposal；熟手明確填起點與similar／small_step／contrast／style_options，small_step要求explore_feature、contrast要求雙端descriptor，不以文字差異或缺少煙燻標籤推論強度。V4 transport兩項RED→GREEN；入口small_step／contrast各一項RED→GREEN，三個入口定向GREEN。草稿卡保留原文／推測／reviewed來源，偏好、硬限制與本次預算由使用者分別選取；沿用同一immutable patch command／receipt，不自動另開研究。
- Web草稿確認的初始整合測試因syntax及BudgetSuggestion fixture錯誤未取得有效RED；這些僅列準備錯誤，不宣稱整合TDD。純editor／card先前取得有效RED。後續review回歸先取得預算還原1 RED與跨分頁草稿關閉1 RED（`/tmp/whisky-t10-budget-authority-red.log`、`/tmp/whisky-t10-closed-proposal-red.log`），再改為單一parent預算draft／source，editor只發選取事件，並追蹤active question／deadline、清除草稿來源修改、保留手動預算、提交前重新核對identity。定向15 GREEN（`/tmp/whisky-t10-proposal-validity-green.log`），最新全Web **183 passed（6.84秒）**（`/tmp/whisky-t10-proposal-ui-reviewed-full.log`）。
- 本輪fresh design-review B「預算雙重權威」改1／open0，correctness P2「改回原金額仍提交草稿」及「關閉草稿仍可保存」改2／open0；複核均無新增發現。原生Next build、typecheck與Web boundaries通過；Node／workerd Playwright **11 passed（8.9秒）**（`/tmp/whisky-t10-proposal-ui-reviewed-e2e.log`），新增草稿重開→選取偏好→intent_confirmed等待→completed新revision→明確start_v4旅程。首次synthetic harness未轉送proposalTaskId而未出現editor，修正測試入口query傳遞後通過；正式Next route已傳遞，不列產品RED。不以synthetic browser替代T10真登入旅程或真模型人工rubric。

- 熟手入口追加契約核對：先前synthetic fixture接受不存在的V1 `entry="expert"`，實際後端會422。新回歸1 RED後，以generated `CreatePlanInput` 型別固定尚未消歧的合法中間conditions（beginner／starting_bottle=null），熟手名稱與方向仍保存於immutable V4 input，由既有workflow的origin_query→版本問題→精確答覆執行；不修改frozen V1 enum。18項入口／研究UI GREEN；獨立correctness核對V1 validator、generated type、V4 workflow／selection，0新增發現。最新完整Web183 passed（9.13秒）、typecheck、Web boundary、Next build通過，Node／workerd browser 11 passed（10.0秒，`/tmp/whisky-t10-entry-contract-e2e.log`）。

- Web確認 commit `9e31d3a` 的 PR run `36767560944` backend／web jobs各success；熟手契約修正 `cc69dfe` 的 PR run `36768383959` backend／web各success。未部署或將T10標為驗收。
- 計畫偏好卡新增用途、硬限制、新增／移除；parent單一preferenceDraft保留saved／manual／proposal來源與明確移除marker，patch只產生指定upsert/remove，草稿失效保留手動修改。UI「只改一項、保留預算與其他偏好」先1 RED→GREEN；legacy部分移除、失效保留同名兄弟、proposal不能覆蓋未消歧組分別取得行為RED。最初pure helper測試副檔名未收集時已試寫初版，因此不把其事後stub RED當整體TDD證據；只採後續實際先失敗的回歸。定向26 GREEN，最新完整Web **193 passed（7.07秒）**（`/tmp/whisky-t10-preference-final-full.log`），typecheck／boundaries／原生Next build通過。
- correctness新增P2「只改一筆同名偏好卻刪其他」含手動及proposal兩條路徑已修正：未消歧組禁止用途／hard修改與同名proposal套用，必須明確移除到唯一項目；純沿用舊資料不強迫遷移。新domain＋UI2 RED、proposal繞路另1 RED後GREEN，既有backend ambiguous upsert仍已保護。累積correctness四項fixed／open0，design唯一budget B fixed／open0，最後複核均無新增發現；不把design review當correctness證據。
- Node／workerd Playwright **12 passed（9.6秒）**（`/tmp/whisky-t10-preference-final-e2e.log`）：新增瀏覽器刪除一項／明確hard確認／同receipt保存／預算保持／新revision重開，草稿確認與串流舊回歸通過。這是synthetic UI旅程，不取代真登入、T10 live model人工rubric或部署。

- T10 eval 接線：保持凍結的 `backend/evals/t10_cases.v1.json` 不變，另存 typed controls `t10_inputs.v1.json`；13 題各兩次是 26 個 workflow samples，provider attempts 另計，不冒充 26 次模型呼叫。`--dry-run` 不讀 credentials 或呼叫模型；live runner 使用專用 loopback DB、真 migrations／reviewed release／Temporal worker／配額，逐筆保存輸出並拒絕覆寫。來源失敗測試必須明示 `--inject-source-failure`，只對指定 workflow 首次來源讀取注入 unavailable；替代來源仍由真 SourceReader 讀取，兩次 provenance 與 unreviewed 狀態分開保存。
- controls／answer 回歸取得實際 RED 後 GREEN；版本 ID 原依 label 比對的設計 A finding 已改為精確 reviewed UUID，改寫 label 的回歸 1 RED→GREEN。來源 guard 在 fault 前檢查 URL，避免測試繞過正式允許來源；獨立 eval 設計審查 A fixed／open0。初次 runner integration 取得真 DB／Temporal 的缺 `release_id` 行為 RED，修正 public catalog 查詢後通過；credential-free dry run 不作執行證據。
- eval correctness P1「generic RESEARCH_FAILED 遮蔽配額原因，無法停止」已用 sanitized nested failure chain 停止（3 RED→GREEN；暫時容量3040不冒充日額度3036）；P2「通用完成 gate 容許錯誤空結果／違反 hard 比較」新增 case-specific 精確／禁止 version IDs、必要空結果、版本確認與完整 generic 選項（6 RED→GREEN）。兩項 fixed／open0；人工語言、來源品質與確認可用性仍須 rubric，不把此 runner 的 deterministic gates 稱完整 T10 出口。
- 真精確版本 workflow 暴露 V4 沿用 V3 min2 choices 的缺口：`test_t10_eval_runner.py` 的 hard smoke case 1 RED，任務因單一 reviewed match 的 `Invalid clarification question` 失敗；新增 `whisky_publish_question_v4`／store 入口允許明示確認單一版本，V1–V3 預設仍 min2。真 DB 又捕捉舊 choices constraint，forward migration `0016_single_version_confirmation` 只放寬 version 基數至1–5，preference proposal 保持2–5，wheel head 同步。12項 runner／真 Temporal 測試 GREEN（8.48秒，`/tmp/whisky-t10-eval-single-version-migration-green.log`），含 proposal 等待、預算空結果與精確版本確認後 hard 比較空結果；模型為明示 FunctionModel fixture，未作真模型證據。獨立此修正 design-review 0 findings；尚未部署0013–0016或完成 live model／人工 rubric。

- 此 eval／單一版本 slice 完整 backend **601 passed（288.58秒）**（`/tmp/whisky-t10-eval-full-backend.log`）；追加真 quota error 回歸後 runner 定向 **13 passed（17.47秒）**，實際 generic RESEARCH_FAILED 仍可辨識 DAILY_BUDGET_UNCONFIGURED，provider attempts=0。wheel **4 passed（12.08秒）**、scripts unittest11、ruff check／format、mypy88 source files與Python boundaries通過。原 corpus `git diff -- backend/evals/t10_cases.v1.json` 無差異。此輪未改Web，沿最新193／12browser證據；live模型／人工rubric／ARM與部署未驗，不把fixture結果當模型品質。

- eval／單一確認 commit `7133bed` 的 push run `36776707397`／PR run `36776713237` backend與Web jobs各success；PR backend **602 passed（236.98秒）**／wheel4（5.25秒），包含追加真quota負例。來源context檢查再捕捉V4 source prompt未送入本次goal：FunctionModel檢查實際prompt取得1 RED（goal=None），補入goal並更新V4 prompt hash；只供來源選擇，候選／版本／價格資格仍由reviewed規則決定。定向runner14 GREEN（12.90秒），完整backend **603 passed（275.52秒）**（`/tmp/whisky-t10-source-goal-full.log`），ruff／mypy通過；來源／模型fixture明示隔離，不作Qwen真品質證據。T10 live模型仍待帳戶免費配額核對，瀏覽器工具目前沒有可控制的browser，尚未部署。

- source goal 修正 `b506f3c` 的 PR run `36778494885` backend／web jobs均success，installed wheel4也通過；固定語料仍未改題或進行真模型呼叫。
- 歷史方向明確沿用：completed history 顯示入口，私有 restart-context 只讀已保存 intent／消歧後版本與來源 revision，不重建整份展示投影。使用者明確選取後以目前 plan conditions／revision 建立新 task，重新查核 catalog／價格；起點不一致禁止默默沿用，原 report 不改寫。Web history／client／proxy／UI 分別取得有效行為 RED（缺入口、stub、固定路徑404、缺選取卡），缺 intent response 另1 RED後在generated validator後拒絕；serialization input於client補齊nullable欄位，未改V1／V3 payload。
- 來源 provenance：新 start_v4 command 可帶 source_task_id，沒有來源時省略hash欄位，保留既有digest；同reservation transaction驗來源owner／generation／plan／completed並保存。未知來源原被忽略的1 RED→GREEN；migration `0017_restart_provenance` 為 research_v4_inputs 增nullable source欄位、owner複合FK與不可自指約束。真DB驗同key固定來源、新task仍用目前revision2／budget900、舊report仍revision1，foreign／other-plan／unfinished／old-generation拒絕且不留receipt；硬煙燻案例的真Temporal确认後，讀取方向保留smoke意圖與精確版本名稱／catalog item。
- Fresh design-review兩項B（完整展示依賴、缺來源關聯）均改完並複核fixed／open0；獨立correctness P2「退出沿用仍攜無效URL來源」先1 RED／18pass，再改為只有明確選取才帶source，退出使用無來源的新研究，複核fixed1／open0。指令檔現行路徑／規則核對0處修改。負例測試中欄位名稱誤用及違反現有report FK、item ID／version ID混淆僅列fixture修正，不冒充產品RED。
- 最終本機：完整backend **611 passed（323.74秒）**（`/tmp/whisky-t10-restart-backend-full.log`）、installed wheel **4 passed（12.23秒）**（`/tmp/whisky-t10-restart-wheel.log`）、完整Web **199 passed**（`/tmp/whisky-t10-restart-web-review-final.log`）、typecheck、Next build、ruff check／format、mypy89 source files、Python／Web boundaries與scripts unittest11通過。Node／workerd Playwright **13 passed（18.5秒）**（`/tmp/whisky-t10-restart-browser-final.log`），新synthetic旅程驗明確選取、目前revision／budget、遺失回應重送same key／thread／run／input／source；初次缺Chromium runtime屬環境錯誤，補依賴後重跑。原TaskView生成物無差異。此增量尚未部署，T10 live模型／人工rubric／真雙入口與ARM出口仍待完成。

### T10 真模型完整執行與輸出模式修正（2026-10-01，未驗收）

- 使用者確認 Workers Free。固定 corpus／controls SHA 不變，26 次 V4 workflow 共用一份隔離 DB quota ledger、cap6,000 Neurons；40 provider attempts，保守保留4,052 Neurons。原始完整結果 `backend/evals/t10_qwen_20261001.json` 與 [T10_REVIEW.md](backend/evals/T10_REVIEW.md) 保留全部成功／失敗：17 次所有 hard gates通過，8 次 proposal上游錯誤，1 次真來源 fallback 的替代來源 `SOURCE_TOO_LARGE`；不改題或以成功子集取代。
- 同輸入額外兩次診斷皆 HTTP500／Cloudflare8005，記錄 status/code而不輸出token／headers。官方 PydanticAI PromptedOutput 實驗仍用原model、prompt、schema及原文／reviewed mapping validators，未知口味兩次 completed、全部 hard gates通過；證據縮小到 proposal工具輸出路徑，不能宣稱已定位provider內部根因。
- 正式 proposal改 `PromptedOutput(PreferenceProposal)`，prompt fingerprint納入輸出模式；研究來源Agent Tool Output、V1–V3 worker不改。新增輸出路徑1 RED→GREEN，原文／映射與真Temporal question共11 GREEN、runner14 GREEN、凍結V2 history replay正負例2 GREEN。第一次完整回歸611 passed／1 failed為eval fixture仍讀output_tools[0]，更新為JSON text，沒有把fixture錯誤算成新行為RED。
- 正式修正後飲食線索／預算修改／偏好修改各兩次全部 hard gates通過，加上實驗未知口味兩次，原先四類失敗輸入都有兩次回歸。完整26次新版本eval／第二次來源fallback／人工rubric／正式部署仍待驗；保留各分批原始JSON，詳review稿。後續隔離ledger只允許6,000減既有保守reservation餘额，累計5,639 Neurons，不重置／退還unknown charge。
- 最終完整backend **612／377.64秒**（`/tmp/whisky-t10-output-backend-final.log`）、wheel **4／15.28秒**、mypy89、ruff／format、Python邊界通過。API契約、Web與frozen codecs未變。此為後端相容性修正，不關閉T10。

## T11 — 比較、探索結論、回訪與資料管理

相依：T10。範圍：library、相關 discovery 用例與 Web。

- RED→GREEN：兩至三支同維度比較，單支顯示詳情、未知保持未知；詞彙解釋可回到當前酒款證據，不虛構強度或量測。
- RED→GREEN：可保存選中或「沒有適合的」結論；收藏不等於喜歡，喝過喜歡不代表喜歡每個標籤；帳號跨瀏覽器恢復，移除的 catalog item 保留歷史解析出口。
- RED→GREEN：重開用目前 catalog／價格判資格，歷史理由保持當時快照；偏好與回饋修改有 owner／revision 與重送保障。
- RED→GREEN：匯出僅包含自己的完整可匯出資料；刪除涵蓋 DB、相關 history、debug traces 與備份保存政策，重跑 T07／T09 對新增資料的防復活案例。
- 出口：比較→選擇→收藏／喝過→重開→匯出／刪除旅程及跨帳號負例通過；不拿匯出檔代替備份。

### T11 保存結論與私人回訪增量（2026-10-01，未驗收）

- 前提：T10 尚未通過真模型／人工 rubric／正式部署出口；本增量於獨立 `feat/t11-library` worktree 接續 `230dd12`，不將提前實作稱為依賴已驗收。唯讀核對 Oracle：schema `0012_recovery_gate`、5 plans／5 tasks／3 reports，沒有 library tables；正式資料與 runtime 未變更。
- 有效 RED：選擇 domain 8／取捨上限 1；結論 view 關聯 5；真 DB 保存與 receipt 7、刪除後 receipt 隱藏 1、重讀／移除可見性 2、分頁 1；signed JWT HTTP 2／分頁 query 5／報告 parent context 1。DDL JSON literal 被 SQLAlchemy 誤認 bind parameter 的 fixture error 不算 RED。交易故障回滾與 generation 變更負例是既有保障的回歸，沒有假稱 RED。
- `0018_library_conclusions` 增 library 自有結論與一般 CRUD receipt。identity→plan 鎖定後，交易內驗 owner／generation、目前 plan revision、completed report／task 關係及選中版本資格；結論與 receipt 原子保存。重送先重驗可見性，再回原結果；已刪除或舊 generation 不藉 receipt 重新暴露。無適合保留當輪替代版本；選擇、理由、取捨不暗推收藏、喜歡或長期偏好。
- 私人 POST／GET 結論、plan-scoped cursor 列表與 report conclusion-context 都接入 configured API／固定 Node proxy。context 由後端解析 plan，不以 URL 推測關聯；它只是 UI 提示，POST 仍交易重驗。原 `TaskView`、V1 conditions／control codec 與 workflow 未修改。
- Web client／proxy／保存表單／回訪／context／頁面接線依次取得 7／3／1／1／3／2／2／1 有效 RED。保存「無適合」是明確選擇；未知結果保留同 key／body 重送，已知 401／404／409／422 拒絕保留 code 並提供恢復出口。條件已變更的歷史報告不露出保存表單；切換 subject 立即卸載舊私人清單。既有 browser 合成研究旅程增加保存→關頁→再登入找回理由，不代替真 Auth0 驗收。
- 最後核對發現選中歷史結論缺酒名：真 DB／UI 各 1 RED→由 research 經 catalog public 解析原 sealed release／item／version，將選中名稱保存於結論與 receipt 快照。client 不可提交名稱；歷史頁明示「當時選擇」，不宣稱符合目前價格。
- fresh backend／Web design-review 各發現 1 項：plan-scoped 索引缺 `plan_id`、已知拒絕被混成結果不明。兩項皆改；累積 ledger fixed 2／open 0，追加 context 與歷史名稱複查均 `NO DESIGN FINDINGS`。拒絕分類與恢復出口另取得 3 RED→library 23 GREEN；補酒名後 library 24 GREEN。fresh correctness／security review 無 findings，既有 owner／generation／revision／rollback／subject 負例屬 already protected。指令檔現行路徑與規則對帳 0 處修改。
- 最終本機：backend **649 passed／345.61 秒**（`/tmp/whisky-t11-backend-release.log`）；installed wheel **4 passed／12.07 秒**、head0018（`/tmp/whisky-t11-wheel-release.log`）；ruff check／format、mypy95 source files、Python／Web boundaries、scripts unittest11、private startup gate 通過。Web **225 passed**（`/tmp/whisky-t11-web-release.log`）、typecheck、原生 Next build 通過；Node／workerd Playwright **13 passed／10.3 秒**（`/tmp/whisky-t11-browser-release.log`），包括明示合成的保存／關頁／再登入回訪。契約重生 hash 無 drift，frozen TaskView／V1 conditions／control codec 無 diff，whitespace 檢查通過。獨立空測試 DB 的 `EXPLAIN` 使用新增索引，Index Cond 含 owner／generation／plan（`/tmp/whisky-t11-query-plan.log`）；這不是實際負載效能驗收。
- 尚未完成：收藏／喝過／偏好修改、完整私人匯出、DB／Temporal history／trace／備份清除與防復活；T11 完整旅程及正式跨瀏覽器 gate 未驗收。下面的回訪價格增量尚未部署。

### T11 目前 catalog／價格回訪增量（2026-10-01，未驗收）

- 真 DB 回訪先取得 2 RED，獨立 current view 解析保存的選中／替代版本，依保存當時的 budget 與目前 sealed release／30 日政策重算價格資格；不覆寫歷史理由或條件，也不稱為新的完整推薦。新 release 移除版本、owner／刪除隔離與過期價格負例是回歸保障。測試合成 budget seed 的 900 上限不足以讓所有酒款超價、移除 release 未同步剔除價格引用，兩項 fixture 設定錯誤已修，不計 RED。
- signed JWT HTTP 的新回訪 GET 先 1 RED→GREEN，匿名 401／跨帳號 404／no-store 通過；日期由 server Asia/Taipei 計算，不接受 client 指定。client／固定 Node proxy 7 RED→GREEN；UI 超價／無法解析／暫時失敗重查 3 RED→GREEN，保存清單接線 1 RED→GREEN（另一測試因前例失敗留下 mock queue 的串連失敗不另計）。browser 合成旅程因缺回訪 fixture endpoint 得到 1 RED，再加入明示空候選 current view→13 GREEN。
- design-review 發現沿用研究 snapshot 載入全库與不用的來源（A1）。指定版本 public query 取得 1 RED，改為最多三個版本的公開解析，共用 CatalogStore 單酒款價格資格核心；回訪與研究不複製政策、不加 include_sources 旗標。39 項 library／catalog／研究 snapshot 回歸通過，複查 fixed 1／open 0、無新增設計 findings。
- Web 開啟歷史結論即重新查詢；價格區分未篩選／符合當時預算／超价／資料不足，展示查核日、TW／TWD／容量／來源。未解析版本保留歷史並給重新選方向與目前 catalog 出口；讀取失敗不把未知當符合，subject 切換或卸載 abort 並忽略晚到結果。新增生成 schema／TypeScript／AJV，原 TaskView／V1 codec 不變。
- 完整本機：backend **657 passed／349.04 秒**（`/tmp/whisky-t11-revisit-backend-release.log`）、installed wheel **4／12.99 秒**（`/tmp/whisky-t11-revisit-wheel-release.log`）；ruff／format、mypy95、Python／Web boundaries、scripts11、private startup gate 通過。Web **235**（`/tmp/whisky-t11-revisit-web-release.log`）、typecheck、原生 build、Node／workerd browser **13／10.0 秒**（`/tmp/whisky-t11-revisit-browser-green.log`）通過。重生前後 contracts SHA256 相同、無 drift；原 TaskView／V1 codec 無 diff，最終 diff／whitespace 已檢查。最初 scripts 檢查用了錯誤檔名／缺 root 或 unittest top-level，屬命令錯誤，改依 README／CI 正式命令通過，不計 RED。這是本機增量，尚未用正式 Auth0／Oracle 驗收，不關閉 T11。

### T11 收藏與品飲回饋增量（2026-10-01，未驗收）

- `0019_bottle_feedback` 保存 owner／generation／明確版本 ID、獨立收藏旗標、喝過喜歡／不喜歡與原因；每個版本有 revision，初次 expectedRevision=0。只保存酒款 ID 與使用者資料，不推導長期偏好。首次保存經 catalog public 檢查目前已覆核版本；已有回饋可在版本移除後修改，保留退出途徑。
- 普通同步 CRUD，actor 鎖內驗 generation／CAS，與 `library_commands` 的 `feedback.save` receipt 原子提交。相同 key／body 回原收據，不同 body 拒絕；舊 generation 不藉 receipt 回讀。account-scoped keyset 列表用 owner／generation／updated_at／id 索引，排除取消收藏且未品飲的空狀態，但保留 revision 與收據。
- 有效 RED：domain 3、真 DB 初次／修改／資格 5、owner-scoped 讀取 1、分頁 1、signed JWT HTTP 1／無效 query 4；payload 去重、CAS 並行、交易 rollback 是已受保護的回歸。unit／integration test 同 basename 引發 collection error，改唯一檔名後才取得 RED，不把環境錯誤計為行為 RED。
- Web client／固定 proxy 10 RED、editor 3 RED、研究候選接線 1 RED、列表移除出口／切換帳號 2 RED；token 晚到不得送舊 session 寫入另 1 RED。只收到合法 receipt 才顯示已保存；unknown 結果凍結 key／body，已知拒絕先重讀。`/library` 重新解析目前 catalog，回饋獨立於歷史結論與預算，未解析版本可取消收藏或重選。
- fresh design-review 0 findings。獨立 correctness review 找到首頁更新失敗重試舊 next cursor：1 RED→記住失敗請求位置，複查 fixed1／open0。空白正規化假說由既有 `str_strip_whitespace=True` 保護，撤回，沒有多加補丁。指令檔現行規則對帳無需改動。
- backend **675／597.44 秒**（`/tmp/whisky-t11-feedback-backend-release.log`）、wheel **4／15.42 秒**、ruff／format、mypy96、Python／Web boundaries、scripts11、private startup gate 通過。Web review 後 **254**（`/tmp/whisky-t11-feedback-web-reviewed.log`）、typecheck、原生 build 通過。新增 browser 合成收藏保存→丟失回覆→同命令重送→關頁登入重開→未品飲／移除版本出口，缺 fixture 接線先 1 RED，修正後全部 **14／24.5 秒**（`/tmp/whisky-t11-feedback-browser-final.log`）；其後僅修列表首頁 retry，對應回歸已 GREEN。生成物 SHA256 重生前後一致；frozen TaskView／V1 codec 不改，最終 diff／whitespace 已檢查。
- 此增量未部署，不代替真 Auth0／Oracle／跨瀏覽器驗收。T11 長期明確偏好、完整匯出、實際清除及防復活仍待完成。

### T11 長期明確偏好增量（2026-10-01，未驗收）

- `0020_long_term_preferences` 保存 owner／generation 下的一份有界明確偏好集合，revision／CAS 與 `preferences.save` receipt 在 actor 鎖內原子提交。只接受 user_stated、明確陳述與喜歡／排斥、軟／硬限制；拒絕預算及 inferred 欄位。可連結自己的當代品飲回饋 ID／revision，但不由酒款全部標籤推論偏好。
- 有效 RED：domain 5、真 DB 保存／收據／空狀態／隔離 5、signed JWT HTTP 3；修改／清空、並行 CAS、交易 rollback、来源 ownership／revision 與 generation 負例是回歸保障，domain＋store 合計 15 GREEN。新 profile schema 與 standalone validator 由契約生成，CI 檢查 drift。
- Web client 3／proxy 2／editor 3／選擇套用 2／收藏列表接線 1／開始探索接線 1 RED。長期偏好預設不套用，本次預算獨立；熟手保留同特徵須保留原 hard 強度，與 avoid 衝突須先解決，兩項反例 RED→GREEN。
- fresh design-review 無 findings；獨立 correctness review 找到 ACTOR_DISABLED 的 403 被誤判 unknown，新增 1 RED 後改為已知拒絕。同類搜尋 `rg -n '\[401.*404|ACTOR_DISABLED' apps/web/src/features/library` 確認結論及回饋保存也有同一分類缺漏，另 2 RED 後修正。拒絕後重讀，不盲目重送。指令檔現行規則无需改動。
- Web **271 passed**（`/tmp/whisky-t11-library-disabled-green.log`）；此前原生 Next build／typecheck、Node／workerd browser **15／21.8 秒**（`/tmp/whisky-t11-preferences-browser-final.log`）、wheel **4／13.18 秒**、ruff／format、mypy98、Python／Web boundaries、scripts11 通過。browser 新案例是合成 API 的保存→重開→明確勾選套用，不取代真 Auth0。舊 saved 測試文字查詢會與非同步失敗訊息撞字、clearAllMocks 不清尚未消耗的 once queue，已改語意 heading 查詢及獨立清理；這是測試穩定性修正，不算新產品 RED。
- 完整 backend **694／403.22 秒**（`/tmp/whisky-t11-preferences-backend-release.log`）通過。最後 403 client 修正後 typecheck、原生 build 與 browser **15／12.1 秒**（`/tmp/whisky-t11-preferences-browser-reviewed.log`）再次通過。生成 contracts SHA256 前後相同、無 drift，frozen TaskView／V1 conditions／control codec 無 diff；最終 diff／whitespace 已檢查。此增量未部署，T11 完整匯出、實際清除、防復活與正式旅程仍未完成。

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

### T04 第六段 — task／command 恢復查詢

- HTTP 行為 RED：`uv run --project backend pytest backend/tests/integration/test_research_reads.py -q` → 4 failed／1 passed；缺少路由讓合法恢復、401 與停用 actor 的 403 失敗。最早 fixture 傳入尚未存在的 store 參數是接線錯誤，不算 RED，已改為既有 router 後取得上述行為證據。
- GREEN：GET task 讀既有 owner／generation 限定的 TaskView；GET command 讀 research.start receipt，驗 owner／當前 active generation，回公開 command ID、task ID、scope、acceptance。兩者不啟動／重試 Temporal，也不將 pending 改成 accepted；不存在與跨 owner 同為 404。configured_app 接上 ResearchStore，未配置 store 明確 503。
- Web RED：`vitest run tests/research-reads.test.ts` → 3 failed／3 passed；GREEN 6 passed。catch-all route 轉送受限的 UUID GET task／command；拒絕 query／額外路徑／mutation，沿用固定 origin、Bearer-only、安全 response header 與 no-store。OpenAPI／TypeScript 由 Pydantic 生成。
- 完整驗證：`uv run --project backend pytest backend/tests -q` → 254 passed（89.74 秒）；`pnpm --filter @whisky/web test` → 77 passed；`python3 scripts/test_wheel.py` → 4 passed（6.35 秒）；`pnpm --filter @whisky/web test:e2e` → 5 passed（11.5 秒）。ruff／format、mypy、Python／Web 邊界、typecheck 與清空公開 Auth0 fixture build vars 的 Next build 通過。
- t04_plan_http_design 唯讀 correctness review 未發現缺陷：覆蓋 owner／generation、真實 pending／accepted、HTTP authentication、固定 origin Web forwarding。此段僅沿用已審查的 read-store／HTTP／proxy 結構，沒有新 transaction、schema migration 或執行機制。主 agent 已核對 diff 與 repo／second-brain status／log，未見 reviewer 越界修改。
- 前段 `7a72622` 的 push／PR runs `36442509642`、`36442517530`，backend／web jobs 均 SUCCESS。T04 仍未驗收、未部署；接續 agent_turns mapping、AG-UI start 與 production observation source，再驗真 DB／Temporal／HTTP 接受出口。

### T04 第七段 — typed start envelope 與跨層恢復證據

- 前提差異已交由使用者決定：既有 store 由伺服器產生 thread UUID；標準 RunAgentInput 首輪必帶 threadId。選項為預先向伺服器配發、接受 client UUID 後綁定、另存雙 ID 映射；建議接受 client UUID 並驗 owner／永久 task 綁定，task／workflow ID 仍由伺服器產生。此決定尚未收到回覆，未修改 thread 建立與 DB mapping。
- 不依賴 ID 配發選擇的 typed envelope 已實作：只解析 forwardedProps 中 type=start、key、planId、conditionsRevision；拒絕額外 owner／workflowId／taskQueue／conditions、空白或過長 key、無效 UUID／revision，並拒絕 start 搭配 resume／parentRunId。messages／state 不作權威條件或工具指令，parse 不啟動執行。
- RED→GREEN：`uv run --project backend pytest backend/tests/test_start_command.py -q`，15 failed（明確未實作的 parser）→15 passed。resume fixture 已依 installed AG-UI 0.1.22 的 ResumeEntry 必填 status 修正後才計算行為 RED，schema fixture 錯誤不算通過或 RED 證據。
- 追加既有恢復能力的跨層驗收：`uv run --project backend pytest backend/tests/integration/test_research_reads.py -k actual_temporal -q` → 2 passed。真 PostgreSQL／Temporal 建立研究，HTTP 查詢一般受理與遺失回應後的 pending；同 key 對帳後 command=accepted、task=queued，task ID／Temporal run 保持相同。這是既有受理能力追加驗證，不冒稱本次才取得該能力的行為 RED，也不代表正式 Agent／worker 執行完成。
- 前段 `72cabcb` 的 push／PR runs `36443243528`、`36443251228`，backend／web jobs 均 SUCCESS。
- 完整後端驗證：`uv run --project backend pytest backend/tests -q` → 271 passed（56.91 秒）；`python3 scripts/test_wheel.py` → 4 passed（5.81 秒）；ruff／format、mypy 與 Python 邊界通過。本段未改 Web 或公開 HTTP schema；parser 尚未接 `/agent`，T04 保持進行中。

### T04 第八段 — AG-UI turn 原子映射

- 前段 thread ID 問題尚未收到選項回答；它是尚未部署的可逆入口選擇，依使用者本 session「不需要再問」的既有授權採建議方案繼續，不把等待回覆當成授權缺口，也不記為使用者已明確選定 client UUID。client thread/run 只作關聯，task/workflow 仍由伺服器產生；不同 owner 可使用相同 client UUID。
- 0007 migration 將 task thread 唯一性改為 owner 範圍，增加 agent_turns 的 owner/thread/run 主鍵、command 唯一性與 task／command／owner／thread 複合 FK。outcome 初始 null；終結回合的寫入仍由後續執行接線完成。
- reserve_turn 在 identity lock 的同一 transaction 內驗既有綁定、共用 reserve 邏輯、保存 task／receipt／turn。相同回合回放原 receipt；變更 key、run、thread 或 payload 拒絕，不多建 task；插入 turn 失敗整筆回滾。
- 真 DB RED→GREEN：`uv run --project backend pytest backend/tests/integration/test_agent_turns.py -q` → 8 failed（6.54 秒）→8 passed（3.94 秒）；RED 前先建 schema，避免把缺表當行為 RED。測試涵蓋並行、owner 隔離、綁定衝突與第三筆插入失敗回滾。
- fresh design-review 嘗試 t04_turn_design 遭 host thread limit，尚未完成此 gate；不以作者自查或舊 reviewer 的 correctness 取代。現有 t04_plan_http_design 另做唯讀 correctness review；未提交／未推送／未部署本段。
- 完整驗證：`uv run --project backend pytest backend/tests -q` → 279 passed（94.58 秒）；`python3 scripts/test_wheel.py` → 4 passed（7.19 秒，migration head 0007）；ruff／format、mypy、Python 邊界通過。首次 full command 在 mypy 的 SQL scalar 型別註記被擋，補 UUID annotation 後才執行上述全套，不算行為 RED。
- t04_plan_http_design 的獨立 correctness review 未發現缺陷；核對 scope／generation、唯一性、identity lock 序列化、兩組複合 FK、交易與 migration/wheel。主 agent 核對 repo／second-brain status／log，無 reviewer 越界寫入。fresh design-review 仍受 host thread limit 阻擋，未聲稱此 gate 通過；接續 `/agent` 與 observe 接線可先在未提交工作區推進。

### T04 第九段 — AG-UI HTTP 與 DB 觀察接線

- HTTP RED `uv run --project backend pytest backend/tests/integration/test_agent_http.py -q` → 3 failed（5.47 秒，/agent 尚不存在）；GREEN → 3 passed（9.66 秒）。真 DB／Temporal 驗一般 queued、接受後回應遺失的 pending、同回合重送找回原 task／command、正確 run observe、跨 owner／錯 run／錯 revision 404，以及換 run 的 409。未確認執行完成時不發 RUN_FINISHED。
- AcceptResearch.execute_turn 與原 execute 共用同一受理邏輯；DBObservationSource 先驗持久 turn 關聯，再讀 owner／active generation 的 TaskView。configured_app 的 store 路徑已可使用 DB source，但 Temporal client／settings 尚未 wiring，正式 start 目前仍 fail closed 503，不宣稱已完成正式入口。
- Web RED `vitest run tests/research-proxy.test.ts` → 1 failed／5 passed（start 被拒絕）；GREEN 後全 Web 78 passed，typecheck／邊界／Next build 與 E2E 5 passed（45.6 秒）。共用 researchStreamProxy 只接受 /agent 與 /agent/observe 的 POST，保持有界 body、固定 origin、no-store／redirect 拒絕，加入公開 X-Command-Id；RunAgentInput／API 契約重新生成。
- 完整 backend 首輪出現 3 failed；在已確認失敗後以 SIGINT 結束該測試程序取得摘要（66 passed／349.03 秒），沒有因觀察逾時重啟。真 DB 當時沒有 lock wait。原因是 HTTP fixture 的 200 ms 與舊 observe fixture 的 80 ms lifetime 先到期，讓授權／回放測試拿到合法 503。調整整合 fixture 為 2 秒／1 秒；production 60 秒政策與專門的期限／取消測試未改。這是驗證前提修正，不冒稱產品 regression。
- fresh native reviewer 因 host thread limit 無法建立後，以 codex exec --sandbox read-only --ephemeral 啟動全新 CLI reviewer，未繼承作者對話；使用 design-review 原文提示與相同材料。其 session 01a0e8b2-7833-74e3-9e0c-8a61a6ba0fea 完成，提出 2 項；主 agent 核對 repo／second-brain status／log，無 reviewer 寫入。原先 fresh gate 的 host 阻擋已用此獨立程序解決。
- 分流：A（外部 ID 沿用 UUID）→「記」：現有 ObserveInput／TaskView／validator 已使用 UUID，第一版本專案 client 可控制 ID 生成，從零設計同一範圍仍採 UUID；不宣稱 AG-UI 普遍要求 UUID。改接任意外部 client 前重評所有 consumer。B（turn FK 指向 start-only scope 的 receipt）→「記」：採納定稿前決定 receipt 形狀的要求；research_commands 已有 scope／key／payload／task／result 欄位；T06 可 ALTER scope check 擴充 research.answer，owner／task FK 不需拆除。已明定同研究模組共用此 receipt 表，避免未來另建表後繞過 FK。兩項具體決定與重評條件已補 VERTICAL_SLICE；改 0／記 2／提 0／駁回 0。
- 既有 t04_plan_http_design 另做 correctness 複核，無確認缺陷；指出 server acceptance 本身尚未設定應用 deadline，70 秒僅是 Web transport，下一段正式 Temporal wiring 一併處理。真 HTTP client 中途斷線尚未新增跨層驗收，不以既有 cancellation unit gate 冒充此證據。
- 最終完整 backend：`uv run --project backend pytest backend/tests -q` → 282 passed（77.70 秒）；wheel → 4 passed（6.20 秒，head 0007）；ruff／format、mypy、Python 邊界通過。Web 78／E2E 5、typecheck／Web 邊界／Next build 已於本增量通過。fresh design-review gate 已完成並分流全部 finding；第八／九段可提交，但 T04 保持進行中、未部署，下一段處理正式 Temporal settings/client、受理 deadline 與真 client 斷線證據。

### T04 第十段 — 設定化 Temporal 入口與真 HTTP 斷線（2026-09-29）

- 設定 RED：`pytest backend/tests/test_settings.py -q` → 11 failed、6 passed，尚無 Temporal 設定群組。GREEN：可選 address／namespace／task queue 必須一起提供；address 僅 host:port、禁止 URL／credentials，沒有宣稱驗證 DNS 的網路私有性。
- Deadline RED：`pytest backend/tests/integration/test_research_acceptance.py -k deadline -q` → 1 failed，未限制 starter 時超過外層期限。GREEN：AcceptResearch 以 10 秒限制 Temporal 連線／start／describe，超時仍回 committed pending receipt；不涵蓋產品 DB transaction，也不新增 background task。
- 正式 app factory RED：`pytest backend/tests/integration/test_configured_agent.py -q` → 1 failed（503，缺少 acceptance wiring）。GREEN：bootstrap 組合共用 lazy Client adapter，真 PostgreSQL、Temporal local server、uvicorn TCP socket 與 HTTP client 驗到 queued；關閉 SSE socket 後重送找回相同 command／task／Temporal run，GET task 可恢復。僅 JWKS verifier 使用簽章 fixture；DB／Temporal／HTTP 不 mock。此案例斷線點在首份 snapshot 之後，不宣稱已驗到 Agent 完成（T05）。
- 設定與受理相關測試按目錄分組執行 → 25 passed（14.77 秒）；先前交錯指定 parent／child 目錄時 7 個 fixture lookup errors 不算行為 RED。完整 `uv run --project backend pytest backend/tests -q` → 295 passed（125.08 秒，`/tmp/whisky-t04-configured-full.log`）；wheel → 4 passed（9.75 秒）。ruff／format、mypy 37 source files、Python boundaries、diff whitespace 通過。
- fresh design-review `/root/t04_config_review` 檢查設定、composition、client lifetime、adapter、deadline、交易、ID／去重、錯誤與部署邊界，NO DESIGN FINDINGS（改 0／記 0／提 0／駁回 0）；核對兩個 shared trees status／log，無 reviewer 寫入。前段 0780428 的 runs 36447286553／36447282183，backend 與 web jobs 均 success。
- Compose 只新增可選設定，尚未部署專用 Temporal／ResearchWorkflow worker，也未部署 T03–T04 migrations。T05–T12 的 durable 執行與 live gates 仍待完成。
- T04 出口對帳（2026-09-29）：本機真 PostgreSQL＋Temporal 驗 committed pending、並行 start、遺失回應後同 ID／run 對帳、completed 重送不重啟，以及正式 API HTTP socket 斷線後重送；未確認接受仍 pending，已確認 queued。完整本機 295、wheel 4、Web 78、E2E 5 與必要 lint／types／boundaries／build 通過。commit `2304fd1` 的 Actions runs `36448719851`、`36448727900` 各自 backend／web jobs 均 success，`gh pr checks 3` 全綠。T04 因此標為**本機已驗收**；本項不要求正式 worker 完成報告或 live 部署，兩者分屬 T05／T09。未部署的 migration 與 worker 不冒充正式環境證據。
- 追加 CI 串流測試判別力：文件狀態 commit `6ffbe07` 的 run `36449093934` Web job 在 `stream.spec.ts` 失敗，兩份 snapshot 間隔實測 375.5ms，原門檻 `>400ms`；同 commit 另一 run `36449103397` Web job 通過。失敗 trace 中 HTTP 首次回應等待約 434ms，單靠間隔不能判定入口是否緩衝。改以測試專用 FastAPI barrier：第一份 snapshot 穿過 Node／workerd 抵達瀏覽器後，測試才呼叫 release endpoint 產生第二份；若緩衝到 EOF，第一份等待會逾時。這保留實際串流路徑且去掉猜測時間門檻。本機 `pnpm --filter @whisky/web test:e2e` → 5 passed（19.9 秒，`/tmp/whisky-t04-flush-handshake-e2e.log`），Web typecheck 與 fixture ruff 通過；本修正的 CI 結論另行記錄。

### T05 — Durable Agent、來源報告與終態（2026-09-29）

- 前提對帳：T04 僅有可靠受理、probe worker 與 DB 觀察，尚無研究執行或 report。使用既定 PydanticAI＋Temporal，而非在 HTTP endpoint 執行易中斷 Agent。`pydantic-ai-slim[openai,temporal]==2.51.0` 鎖版；Workers AI OpenAI 相容端點的 GLM-4.7-Flash 尚未呼叫，真模型品質屬 T08。
- `0008_research_reports` 保存 task fence、單一 final artifact、當輪 revision／catalog／政策／prompt／模型版本與評估日；候選、逐項 claim/evidence 與合格價格觀察用關聯 FK 綁定不可變 release。報告與 task completed/view version、AG-UI turn success outcome 同交易；相同 artifact key 在 DB commit 後 activity acknowledgement 遺失時只讀回原結果。`GET /api/v1/reports/{id}` 經 owner／generation 查舊 snapshot；catalog 細節只透過 `catalog.public` 解析，Web 只轉送固定 UUID GET。
- 受控 `FunctionModel` 真正透過 PydanticAI 發出 catalog tool call、Temporal model/tool activities、保存 typed report；模型沒查 catalog 而直接輸出空報告會被 workflow 拒絕。目錄超過 20 款的 21 款案例仍完整提供候選；worker 停在第二次模型呼叫時重啟，已完成的 catalog tool 沒有重跑。模型 response 的 `ThinkingPart` 在 activity 返回前移除；測試解碼 Temporal history 的 activity results，未見注入的私有推理字串。此測試不代表真模型品質或 provider 實際回應已驗收。
- RED→GREEN：report claim／price 表尚不存在時 2 failed／5 passed，增 schema／保存後通過；跨候選 citation FK、tag-only／假 fact、嚴格預算、錯誤價格 ID、政策版本不符皆由真 PostgreSQL 拒絕。跳過工具的受控模型先 RED（直接完成），加已完成 tool return 守門後 GREEN；無效 claim 原先讓 task 停 `researching` 的 RED，新增 fenced failure activity 後為 `failed`，取消／已完成 task 不被覆寫。
- 真 HTTP／Temporal／PostgreSQL 驗首份 snapshot 後 SSE socket 關閉仍完成報告；保持串流時完成送已保存 `whisky.report`、`RUN_FINISHED success`，無效模型結果送安全 `RUN_ERROR`，turn outcome 交易保存。舊 probe 測試揭示缺設定 worker 仍可在研究 queue 接任務的風險；正式 worker 缺設定 fail fast，probe 改 `--probe-only` 與 `whisky-probe-` 隔離 queue。
- fresh design-review 的五項初始發現已處理：claim／價格來源、政策／prompt 版本、fail-closed worker、完整 catalog 覆蓋；可變 process-local agent 註冊保留單 worker／process 前提，T06 長等待或正式升版前須補相容舊 history 的版本化 executor。複查新增「research 直接 JOIN catalog 表」已改為 `catalog.public` 查詢。獨立 correctness review 的失敗終態、跳過工具、AG-UI 完成終態三項均以可重現測試修復。兩名 reviewer 均唯讀；主 agent 核對 repo status/log 與 second-brain 專案路徑，未見 reviewer 越界寫入；second-brain HEAD 另由其他 session 前進，未改其內容。
- 本機最終驗證：`uv run --project backend pytest backend/tests -q` → 316 passed（126.25 秒）；修正 catalog 公開讀取邊界後相關整合測試 21 passed，另新增的取消／終態 fence 案例 1 passed；wheel 4 passed（migration head 0008）。ruff check／format、mypy 45 files、Python 邊界與腳本 unittest 5 passed；Web 79 passed、typecheck、邊界與 Next build 通過；staged diff whitespace check 通過。commit `dad8445` 的 push run `36458432254` 與 PR run `36458465361` 各自 backend／web jobs 均 success，`gh pr checks 4` 全綠；T05 因此標為**本機與 CI 已驗收**。T06 補充等待、T08 真模型品質及 T09 正式部署／還原各有獨立 gate。

### T06 — 補充版本、持久等待與跨瀏覽器恢復（2026-09-29）

- 前提對帳：T05 的 V1 history 仍須由同名 workflow／activity 執行；T06 新工作改走 V2。`0009_clarifications` 保存 owner／generation／revision、等待版本、期限與 answer receipt，問題發布和 task `needs_input`／AG-UI turn interrupt 同交易。V1／V2 工具各捕捉自己的 DB engine；worker 以固定 `ResearchActivities` 實例註冊舊 activity 名稱，避免 V2 借用 V1 的程序全域 DB。真 Temporal server／PostgreSQL 測同程序重啟及 `spawn` 新 worker process，補答後查最新 sealed release 並存報告。
- RED→GREEN：問題 publish stub、答覆 reserve／expire stub、V2 原 final-only workflow、Observer interrupt、REST answer、AG-UI resume、Web answer proxy／UI 均先驗到行為 RED；真資料的版本選項及 owner-scoped 未完成 task 清單亦先驗無綁定／404，再改到 GREEN。測試以 barrier 證明 publish commit 與 wait 之間的答覆不遺失，以 time-skipping 驗 7 日過期；同 key 重送、不同答案競爭、過期 receipt 拒絕、已保存問題跨 catalog release／期限重送由真 DB／Temporal 分層驗證。合成瀏覽器 fixture 只驗 UI／傳輸，不冒充真 Auth0／live 模型。
- 版本選項只能引用目前 reviewed catalog 的穩定 `bottle_version_id`，顯示名稱由資料庫產生；報告 commit 須匹配已接受的 clarification／版本，並重新解析當前 release。若版本已撤出，報告明示無法確認、候選為空，不讓模型以別款替代。Web 從 `GET /api/v1/tasks` 找回自己的未完成委託，對仍開啟的 run 使用 AG-UI observe 重連，REST GET 保留為 cold start／補答後恢復；關頁後重新登入、從清單進入、答覆與報告的 Playwright 旅程已通過。
- fresh design-review 的四項發現均「改」：V2 對 V1 全域 DB 的隱性依賴、版本文字未綁 reviewed ID、產品頁未接 AG-UI observe、跨瀏覽器只靠舊 deep link。版本消失與重試跨 catalog release 另加回歸；沒有留下待定項。設計審查者唯讀，主 agent 已核對本 worktree 與 second-brain 的 status／log，未見越界寫入。
- 本機驗證：`uv run --project backend pytest backend/tests -q` → 343 passed（177.72 秒）；後續問題 replay 期限加固的定向案例 1 passed。wheel 4 passed（migration head 0009），ruff check／format、mypy 50 files、Python 邊界、腳本 unittest 5 passed；Web Vitest 88 passed、typecheck、邊界、Next build，Playwright 6 passed；`git diff --cached --check` 通過。push／PR runs `36471600845`／`36471642801` 的 backend／web jobs 與 GitGuardian 均 SUCCESS；PR #5 已合併為 `4cb6817`，T06 已驗收。正式 VM／VPC 研究 worker、真模型品質與備份還原分屬 T08–T09。

### T07 — 控制命令、撤銷防線與晚到結果（2026-09-29，已驗收）

- 前提對帳：T06 的研究／報告已有 owner、generation、revision 與 `write_allowed`；Oracle Web、產品 DB 與 Temporal 仍採既定部署，整個 cluster 的 PITR 會一起倒退，故 T07 沿用 ARCHITECTURE 的 VM 外最小控制紀錄。T07 只用可控的不可變記憶體 adapter 驗流程；正式 OCI Object Storage 的新增／讀取／列舉權限、完整還原對帳與實際資料清除在 T09／T11 驗收。未接正式 adapter 時 configured app 的控制 POST 回 503，不把本機 fixture 稱為可用的正式刪除。
- 沿用盤點（供獨立設計審查驗證）：

  | 機制 | 原約束 | 今天是否成立 | 若從零設計與重評條件 |
  |---|---|---|---|
  | actor UUID＋generation、plan instance UUID＋revision | T01 身分隔離與 T04 重送／條件快照 | 成立；PRODUCT_SPEC 的跨帳號、重新收藏與修改條件仍要求區分實體與版本 | 保留不透明 instance ID、單調 generation／revision；若身份 provider 或資料模型改為多租戶，再重評 scope |
  | task `write_allowed`＋狀態和 report transaction guard | T05 late activity／重送可在取消後到達 | 成立；ARCHITECTURE 要求 DB fence 先於 Temporal cancel | 同一 DB transaction 鎖 identity→plan→task，最後 UPDATE 再驗 guard；若執行權威或 DB 拆分，重評鎖序與原子性 |
  | Temporal workflow＋產品 DB receipt＋VM 外 append-only intent/result | T04 持久受理及同 cluster PITR 無法保住取消證據 | 成立；ARCHITECTURE 第 248–260 行明定跨 cluster 還原 | 仍採 durable workflow 協調、產品 DB 當日常狀態、獨立保存可重套的最小控制證據；條件變更的 intent/result 額外保存新條件快照，不保存被刪原文或 token。T09 換真 adapter 並驗權限、加密、保留期與還原 |
  | deterministic workflow ID、UUIDv4 command key／payload hash | T04 重送與 Temporal 回應遺失 | 同 key 同 payload 去重仍成立；審查發現「同 target／revision 只能提出一次」不是舊約束 | workflow ID 加 receipt ID，保留同 key 重送與 DB revision 比對；不同 key 可競爭，同 revision 最多一次 effect 成功，已拒絕者可修正再提 |
  | plan `deleted_at` tombstone | T07 先撤銷 child 寫入並隱藏計畫；T11 才涵蓋完整清除 | 成立，但不是正式資料刪除 | 保留短期 tombstone 作 fence；T11 必須定義 DB／history／trace／備份清除與保存期後才能提供正式刪除承諾 |

- TDD RED→GREEN：控制 store／journal／workflow／HTTP 與 Web allowlist 的新行為在尚無模組或接線時先失敗；新增 older-generation、舊 AG-UI interrupt 與取消通知案例曾驗到具體行為失敗，再加 fence／終態收斂。actor 刪除最後一步注入 `IDENTITY_CHANGED` 時，原本沒有回滾整筆子項變更的 RED（`test_actor_delete_rolls_back_all_descendants_if_identity_final_step_fails`），現改為交易異常回滾；停用 actor 後仍可 GET 舊控制收據的 RED（`test_deleted_actor_can_reconcile_only_its_delete_command`），現只允許原刪除收據對帳。條件變更另驗 pending clarification 轉 closed、task superseded、完成報告保持歷史。
- 真 PostgreSQL 的兩條獨立連線與 barrier 逼出取消先取得 identity／plan／task 鎖、晚到 report 才嘗試 commit，後者因 `TASK_NOT_WRITABLE` 失敗，報告數為 0；Temporal local server 的控制 workflow 在結果物件寫入被 barrier 阻住時 DB 仍為 `effect_applied`，放行後才是 `completed`。結果寫入前失敗與寫入後遺失 ack 均由同 command／物件 key 重試，不新增 effect；revision 不符保存 `rejected` 外部結果而非顯示成功。暫時移除 report 的 `write_allowed`／status 兩道 guard 後，`test_cancel_requires_confirmed_external_intent_and_fences_late_report` 實際 1 failed（晚到報告不再被拒）；已還原原 guard 並重跑驗證。
- `0010_control_commands` 增 typed receipt、唯一 scope 與 plan tombstone；跨模組 effect 只走 `identity.public`、`discovery.public`、`research.public`。HTTP 提供 cancel／conditions／plan delete／actor delete 與 owner-scoped receipt，Web 只允許固定路徑與 Bearer／no-store。此階段的 plan／actor delete 是寫入防線與隱藏，不是 T11 的完整資料清除；取消通知晚於 DB fence，Temporal 停止屬協作式。
- fresh design-review 3 項發現均**改**：外部 intent/result 原缺 command key 與可重套的條件內容，現用 UUIDv4 key 並讓兩份物件各自含新條件快照；單 target／revision 唯一鍵原會讓被拒絕的條件變更無法修正，現只以同 key 去重並靠 revision transaction 決定勝者；跨模組原以 `str(ValueError)` 判 durable rejection，現改用帶穩定 code 的 `DomainRejection`，未預期例外使整筆 DB effect 回滾。這三項各有原行為 RED，修正後有 PostgreSQL／Temporal 與 journal 回歸測試。審查者唯讀，主 agent 已核對工作樹與 second-brain status／log，無審查者越界寫入；second-brain HEAD 由其他 session 前進。
- 另以故障注入證明 typed rejection 若發生在條件 revision 已更新、子任務尚未關閉之間，原實作會提交半筆 effect；`ControlStore.apply` 現以 savepoint 回滾局部寫入後才記 `effect_rejected`。獨立 correctness/security review 檢查 owner／generation／revision、交易鎖序、外部紀錄／重試、Temporal 與 Web／API 權限，`NO CONFIRMED DEFECTS`；T09 的真 OCI／PITR 不冒充本次證據。審查者唯讀，主 agent 再核對兩個共享樹的 status／log，無越界寫入。
- 條件快照在 T09 正式 adapter 啟用後會進入 VM 外有限期控制紀錄，這是跨備份點重套條件變更所需的個人資料；啟用前必須完成 OCI 存取／加密／retention 與 T11 刪除說明驗證，不能把本機記憶體 adapter 當成隱私或還原證據。
- 本機最終驗證：於 `/tmp/whisky-t07-controls` 使用獨立 loopback PostgreSQL fixture 執行 `uv run --project backend pytest backend/tests -q` → **364 passed**（201.11 秒，`/tmp/whisky-t07-backend-savepoint.log`）；真 Temporal local server、兩 DB connection barrier 及 mutation 各有上述反例。`python3 scripts/test_wheel.py` → 4 passed（migration head 0010）；ruff check／format、mypy 60 source files、Python 邊界與 scripts unittest 5 passed。Web Vitest 99 passed、typecheck／邊界／Next build、Playwright 6 passed，edge `wrangler deploy --dry-run` 通過；OpenAPI／TypeScript 契約重生後無 drift，staged diff whitespace 檢查通過。Docker 初次建立新 PostgreSQL 容器在本機負載下超過原 30 秒，屬環境錯誤，改用專用測試 DB 並把 fixture readiness 上限設 90 秒，沒有計為行為 RED。commit `2b20401` 的 push run `36481975339` 與 PR run `36482037118` 各自 backend／web jobs 及 GitGuardian 均 success；PR #6 合併為 `dee2333`。正式 OCI 權限、PITR 還原及資料清除留 T09／T11 驗收。

### T08 — 真來源、受限模型選擇與用量防線（2026-09-29，已驗收）

- 前提重查：`PRODUCT_SPEC.md` 指定規則負責版本、資料資格、硬限制與候選選取；Agent 選研究來源／比對重點，Workflow 管等待與恢復。T07 的 owner／generation／revision／write fence 沿用。V1／V2 workflow 及其 tool schemas 不改，新增 V3，避免改寫已保存 history。T08 的來源頁面只作未覆核觀察，不能把頁面指令、價格或酒款寫進 sealed catalog。
- 真來源 reader 只接受當前 sealed release 的 reviewed evidence ID，服務端解析 URL；僅允許四個已覆核主機，逐跳驗 HTTPS／公網 DNS 與重導、限制 20 秒／512 KiB／2,000 可見字，不接代理、cookie 或任意 URL。注入頁面指令的真 PostgreSQL／Temporal regression 證明無發布工具，且頁面文字不進模型提示。來源 observation 保存原 evidence 與實際完成讀取的 URL；允許主機間 302 的報告回歸先 `1 failed`（只顯示原網址），後 `3 passed`，Web 另列實際 URL／原 reviewed 引用。實際來源抽查：飲酒網、格蘭菲迪官網、MY9 可讀；格蘭利威官網曾回 403，報告明示讀取失敗，不冒稱查無酒款。
- 用量 migration 0011 記錄 UTC 日、任務／帳號、每次模型或 reader activity 嘗試與實際／預留用量。以 prompt＋output schema／tool 定義的 UTF-8 bytes 加 1,024-byte envelope 作**保守** input 預留，provider output 上限 2,000 tokens；schema 漏算的真 Temporal 回歸先 `1 failed`、後同檔 `5 passed`。這不是供應商實際 token 的數學上界：若實際超過預留，差額仍記入 DB，後續 admission 會停止，但已發生的超額不能倒轉；設定值必須低於帳戶剩餘免費額度，Workers AI Free 本身超額拒絕，沒有付費 fallback。每日設定上限只能在 Workers AI Free 10,000 Neurons 內，未設定為 0 且 fail closed。單任務 8 次模型／12 次來源、全站同時 2 次 I/O、每帳號 1 個 active task；retry／未知結果不退費，取消或超時的殘留活動保留扣額但釋放 slot。真 DB 並行搶占、重試、崩潰與殘留測試中，殘留案例先 `1 failed`（`/tmp/whisky-t08-reap-red.log`），後 `1 passed`（`/tmp/whisky-t08-reap-green.log`）。
- 固定語料 `backend/evals/t08_cases.v1.json` 在第一次 live model 前由 `55dbb1c`／`1ceafcd` 凍結，六種真實樣本情境各重複兩次。初版 GLM／Qwen 讓模型選完整候選及自由文字，實測出現錯選空候選、重複版本追問、未讀來源卻聲稱 403，以及多輪工具訊息的 provider 400；不能把它們算成 TDD RED 或通過。依既有產品契約改為 reviewed catalog 規則先選版本／合格候選，Qwen 的單次 PydanticAI 結構化輸出只選 reviewed source index 與說明重點，Temporal activity 讀來源，正式理由由 exact claims／價格與標籤組成。選品政策的真 DB 案例先 `7 failed`（`/tmp/whisky-t08-selection-red.log`），後 `7 passed`（`/tmp/whisky-t08-selection-green-attempt.log`）；受限模型／來源整合先 RED（`/tmp/whisky-t08-source-choice-red.log`），後定向 22 passed（`/tmp/whisky-t08-source-choice-targeted.log`）。
- fresh design-review 指出來源頁成功內容只被讀取卻沒有報告出口、熟手結構化起點被 goal 關鍵字遮蔽、catalog 候選／來源跨 release 分段讀取、V3 追問帶不必要的舊 draft 與 release 漂移。逐項修正：來源觀察用 0011 migration 分離保存，報告關聯及 Web 專區明示未覆核，活動只回 ID／digest 而不把頁面原文放入 Temporal history；catalog 單一 REPEATABLE READ snapshot；V3 只傳 reviewed version IDs 加固定 release，由 DB 產生顯示名稱並拒絕切版。熟手入口依結構化起點排除原酒款，起點已不在 current release 時 fail closed。`test_research_selection_policy -k existing_bottle_entry_uses_reference_without_goal_keywords` 曾 `1 failed`（原酒款仍在候選），後該檔 `10 passed`；`test_research_reviewed_question_contract -k release_drift` 曾 `1 failed`（未拒絕切版），後連真 workflow `3 passed`。來源報告整合曾 `1 failed`（缺 `source_observations`），Web UI 曾 `1 failed`（缺未覆核摘錄），後相關整合 `15 passed`、UI `7 passed`。跨 owner 掛接來源觀察遭真 DB 報告驗證拒絕；來源頁惡意指令不進模型或 Temporal 活動結果。
- 最終同版 prompt `research-v3-21f7456fece1`、catalog 規則 `catalog-selection-v3-3` 的真模型逐次資料與人工 rubric 見 [`backend/evals/T08_REVIEW.md`](backend/evals/T08_REVIEW.md)。Qwen 12/12 completed／硬門檻，GLM 11/12；後者 `glenlivet_source_failure` 第二次單輪模型呼叫回 provider HTTP 400，依非重試政策安全失敗。兩者中位 5.84／8.19 秒、最慢 11.77／39.89 秒，計入 632／752 Neurons；來源可讀 Qwen 6/8、GLM 4/7。先前 GLM 曾在未補 schema 配額及 redirect provenance 的同 prompt 版本 12/12，但不能覆蓋最終失敗。故選定硬門檻全過且較快／省額度的 Qwen；Will 於 2026-09-29 同意選型並接受逐案例定性評分，T08 人工 gate 通過。一次性來源選擇仍會重複讀到 403，T10 將處理來源失敗後補讀與更完整比較。凍結語料沒有測後改題。
- 最終本機回歸：`uv run --project backend pytest backend/tests -q` → **415 passed**（182.86 秒）；`python3 scripts/test_wheel.py` → 4 passed、migration head 0011；ruff check／format、mypy 66 source files、Python 邊界、scripts unittest 5 passed；Web Vitest 100 passed、typecheck／邊界／Next build、Playwright 6 passed，edge `wrangler deploy --dry-run` 通過。OpenAPI 與 TypeScript 契約重生無 drift，staged diff whitespace 通過。fresh design-review 複查上述修正及沿用機制，結論 `NO DESIGN FINDINGS`，審查者僅唯讀；主 agent 核對 repo 與 second-brain clone 的 status／log，沒有審查者越界寫入。commit `b8f0049` 的 push run `36504668707` 與 PR run `36504698757` 各自 backend／web jobs 與 GitGuardian 均 success；人工 rubric 已覆核。正式 VM 部署、replay 與 PITR 仍屬 T09，不以隔離 eval 代替。

### T09 — Replay、外部對帳與還原（2026-09-29～30，進行中）

- 固定等待中的 V2 history 由隔離 Temporal 測試與合成 payload 產生；worker identity 已清除。`test_research_replay.py` 先以故意改變活動順序的 workflow 驗 `NondeterminismError`，再以原 V2 executor＋PydanticAI sandbox passthrough 正常 replay；沒有改寫 V1／V2 workflow 或 agent。獨立 `spawn` worker 程序在 `needs_input` 等待時以 SIGKILL 終止，第二個程序補答後只保存一份報告。第一次定向 `uv run --project backend pytest backend/tests/test_research_replay.py backend/tests/integration/test_research_crash_recovery.py -q` → 3 passed（18.2 秒）；測試檔與 fixture commit `7117fa6`。
- 完整外部控制紀錄讀取與 PITR 對帳：先讓尚未存在的模組出現 4 個明確 RED，再實作 `read_complete_control_log` 的全分頁、全物件讀取、schema／hash／配對驗證，未通過前不寫 DB。以真隔離 PostgreSQL 將刪除 effect 復原成可見計畫，再重套外部 completed 結果；45 天前的 pending intent 仍處理，rejected 不重套，漏頁／物件讀失敗先停止。追加「DB receipt 已標 completed 但資料可見」、「外部結果時間與已套用 receipt 不同」與「已刪除 tombstone 但 receipt 遺失」的行為 RED，修正後 `uv run --project backend pytest backend/tests/test_control_recovery.py backend/tests/integration/test_control_restore.py -q` → 16 passed；actor 停用、舊 generation、新計畫不受舊命令影響也通過。OCI adapter 的條件式新增、相同內容重試與 1,002 物件分頁先因模組缺失 RED，實作後定向合計 18 passed。這些仍是本機 DB＋fake OCI client，不冒充真權限或整機 PITR。
- `oci os ns get` 使用此 session 授權的本機 OCI 身份成功；2026-09-29 唯讀 SDK 盤點 root／active child compartment 均 0 bucket。Oracle VM `oci-a1` 當下 aarch64、Docker 29.5.2／Compose 5.1.4、root 117 GiB 可用、RAM 約 20 GiB available。已建立私人 Standard bucket `whisky-discovery-controls`，套用**未鎖定**的 30 天 retention rule；合成物件刪除實測 `403 RetentionRuleViolation`。此專案專用 runtime／recovery API-only IAM user、group、key 與 bucket 限縮 policy 已建立；key 保存在主 checkout 的 ignored `deploy/secrets/`，沒有匯入別案憑證。runtime 真 OCI 寫入／讀回、相同內容重送、不同內容拒絕、列舉及刪除遭 `404 BucketNotFound` 權限遮蔽；recovery 身份完整列舉／讀回成功。bucket 內保留一組無真 actor 的 `SYNTHETIC_PROBE` rejected intent/result，30 天後到期，不進正式控制資料。retention 下相同 `if_none_match=*` 重送實際先回 `403 RetentionRuleViolation` 而非 412，先以真 OCI RED 發現，再加入特定錯誤的讀回比對並由 fake adapter 回歸 GREEN，最後真 OCI 探針通過；不得把所有 403 一律當成功。帳戶 Object Storage limit API 回報 PAYG 上限極大，不等於 Always Free 的 20 GB 額度；仍須測實際備份容量與費用。
- 加密備份先在本機 ARM Docker 的**獨立 PostgreSQL 18 測試 cluster**驗 OCI S3 相容端點；專用 `whisky-backup-writer` S3 key／IAM 只限私人 `whisky-discovery-backups` bucket，客戶端 AES-256-CBC cipher pass 另存在 VM 外的 ignored secrets。pgBackRest 2.58.0 `stanza-create` 首次因 bucket read IAM 不足為真 403，限縮補權後成功；`check` 驗 WAL archive 成功。第一個 full backup 曾遇 Docker DNS 無法解析端點，屬環境錯誤，重試後成功：DB 31,476,868 bytes、repo full 4,148,160 bytes，連 WAL 於 OCI 實測 1,284 物件／7,602,528 bytes；重試命令 wall time 450.42 秒。從**空 volume**以 `2026-09-29 12:41:28+00` 作 PITR、還原命令 212.76 秒，啟動後查 `backup_probe` 只見 target 前 A、沒有 target 後 B。這證明單 DB 的真 S3／WAL／time target／讀回，不等於產品＋Temporal 三 DB 的整 cluster 還原或正式 RPO／RTO。
- 第一個 full backup 的 1,284 物件接近月免費 API 請求額度的成本邊界；以 pgBackRest `--repo1-bundle` 再做第二個 full，DB 31,509,636 bytes、repo full 4,139,232 bytes，該 backup prefix 僅 5 物件／4,689,952 bytes，命令 wall time 83.28 秒。第二次從空 volume 還原該 bundled full 命令 wall time 9.19 秒，啟動後 A／B 兩筆均讀回；正式容量政策仍在驗，不從單次空庫流量外推月費。
- 三庫隔離演練：同一 PostgreSQL 18 cluster 建產品 `whisky`（Alembic `0011_research_usage`）、Temporal persistence（schema 1.18）與 visibility（schema 1.9）；`deploy/temporal-schema.sh` 初始化、再跑皆成功。ARM `temporalio/server:1.29.7` 回 `SERVING`，30 日 namespace 內的 `BootstrapProbe` workflow 在沒有 worker 時保持 running。`pgbackrest --stanza=t09pilot --repo1-bundle backup --type=full` 產生 `20260929-132725F`，DB 59,495,091 bytes、加密 repo 7,556,720 bytes，命令 31.64 秒。從空 volume 以 `2026-09-29 13:28:23+00` 還原命令 12.02 秒：三庫均存在、產品 migration 與 Temporal schema 完整，目標後加入的第 3 筆資料不見；恢復的 Temporal Server 先顯示同 workflow running，再由重新啟動的 Python worker 取得 `ok`。這是本機隔離 cluster＋真 OCI S3，不代替 VM 停機與量測。
- 真 OCI 控制紀錄的全 cluster 演練：先建立合成 actor／plan，再以同一 cluster 的 bundled full `20260929-134009F` 備份（DB 59,593,395 bytes、加密 repo 7,565,520 bytes；37.06 秒）。選定 `2026-09-29 13:40:50+00` 後才以 runtime IAM 寫入 plan.delete intent／result 並刪除原 DB 計畫。從**另一空 volume** 還原命令 16.15 秒，PostgreSQL 啟動日誌 13:41:50→13:42:19.695 UTC（約 29.24 秒）；還原後 `control_commands=0`、未刪計畫 1、私人 API 合成身份讀取 200/no-store。`whisky-control-reconcile` 用 recovery IAM 完整列舉／讀取 2 組外部命令（含無 actor 的 rejected probe），重套 1 組真刪除，DB receipt completed、未刪計畫 0、同一 API 404/no-store；第二次 CLI 執行結果一致。這是隔離環境的真 OCI／DB／Temporal／API 演練，尚未建立正式 VM 的恢復時間或 RPO 目標。
- 本輪後端回歸在 worker secret-file 變更前為 `uv run --no-sync --project backend pytest backend/tests -q` → **442 passed**（213.21 秒）；新 secret-file 行為先 ImportError RED，實作後定向 2 passed。ARM API image 首次因 OCI SDK 下載逾時失敗（環境錯誤），加入 BuildKit uv cache 與 120 秒 timeout 後 `docker build -f deploy/Dockerfile -t whisky-discovery-api:t09 .` 通過，容器內 OCI 2.187.0 import 成功；`compose.yaml`＋`compose.research.yaml` 靜態 config 通過。完整回歸與 live stack 仍待重跑。
- 2026-09-30 完成雙 bucket witness：私人 `whisky-discovery-control-witness` 與 primary 各有 30 日未鎖定 retention，runtime 對兩邊僅 create/read，recovery 對兩邊可 list/read/create；一般寫入先 witness 後 primary 並逐物件讀回。缺整個 pair 的 primary／witness 差異、缺頁與 body 不同都拒絕對帳。witness-first crash 的部分寫入由隔離模式 `repair_witness_only` 先解析完整 witness，再只補 primary 缺的相同位元組；primary-only 或內容衝突不猜測。`uv run --no-sync --project backend python /tmp/whisky_t09_repair_live.py` 以**真 OCI recovery IAM**建立無 actor 的 witness-only 合成 intent，補 primary 並重讀兩邊全庫成功。兩 bucket 仍在同一 OCI tenancy／IAM 管理域，retention 未鎖定；不能宣稱抵抗管理員同時清空兩邊。保留期的操作控制與費用須依 T11 資料管理政策收斂。
- 角色與放行門檻：`db-roles` 把產品 DDL／runtime、Temporal schema／runtime 分開，撤銷三 DB 的 PUBLIC CONNECT；`0012_recovery_gate` 只給產品 runtime SELECT。還原 job 用 DDL 身份完成雙庫全量對帳後，才以啟動前讀得的 `pg_postmaster_start_time()` 條件式寫入 singleton；API／worker 每次 DB checkout 都重驗，API `/health/ready` 查 DB，Compose 覆寫健康檢查。真 PostgreSQL 定向 RED→GREEN：無 stamp、舊 epoch、兩庫讀取失敗均不放行；完整對帳才放行。`uv run --no-sync --project backend python /tmp/whisky_t09_restart_gate.py` 在獨立 PostgreSQL 18 容器真重啟後測得舊 stamp 拒絕、新 stamp 開放；`/tmp/whisky_t09_role_gate.py` 的獨立角色庫在 DDL migration 與角色重跑後確認 runtime 不能更新 gate、建表或連 Temporal DB。這是隔離環境；正式 VM 的 Compose job 與停機順序仍待實測。
- 第二輪獨立 review 發現若省略 overlay 或沿用舊 image／bootstrap admin URL，應用層 gate 可被繞過。以 PostgreSQL 18 的 superuser-only `ON login` event trigger 在 **DB 連線邊界**拒絕未對帳 epoch 的 `whisky_runtime`；登入函式只讀 gate，DDL／recovery 身份不被鎖死。`test_database_login_gate.py` 先確認舊程式不做 checkout 檢查時確可讀私人資料，再因 gate 安裝腳本未存在取得 RED，實作後驗無 stamp／過期 stamp 都拒絕，runtime 無權用 `event_triggers=off` 繞過，當前 stamp 才可登入。`scripts/tests/test_deploy_gate.py` 先因缺 base graph guard RED，之後 base Compose 改為 runtime／DDL 分帳、ready 健康、保留 WAL archive，完整 graph 加 `db-login-gate` 先於對帳；`python3 scripts/check_deploy_gate.py` 兩種 graph 通過。bootstrap admin 舊密碼的退場做成 maintenance one-shot，真 VM 旋轉及舊憑證負例仍待測。私人資料的 PITR 只接受登入 gate 與旋轉完成後的還原點；更早 T02 備份僅作尚未正式保存私人研究前的遷移回退。
- 舊控制格式獨立的 `conditions_v1`／`v1_codec` 保存 V1 解碼與 hash；控制 receipt、effect 與還原不再委託將來的 current conditions model。對 clock-skew 的 completed effect 改按 owner／generation／action／target／revision 因果排序，重複成功位置拒絕；跨模組還原查詢移至 discovery／research 公開契約。各以原失敗案例取得 RED，再以定向真 DB 案例 GREEN。新的計畫格式如需 V2，T10 必須明確處理 `PlanStore` 讀取兼容，不能更改 V1 外部紀錄語意。
- 最新完整後端 `uv run --no-sync --project backend pytest backend/tests -q > /tmp/whisky-t09-full-pytest.log 2>&1` → **455 passed（233.35 秒）**；`uv run --no-sync --project backend ruff check backend scripts`、`ruff format --check`（160 files）、`mypy backend/src`（72 source files）、Python 邊界、scripts unittest 7、`python3 scripts/check_deploy_gate.py` 與 OpenAPI 契約 drift 檢查均通過。wheel／ARM candidate 與 VM live 仍各有獨立出口。
- 登入 gate 追加後完整回歸 `uv run --no-sync --project backend pytest backend/tests -q > /tmp/whisky-t09-full-pytest-2.log 2>&1` → **456 passed（243.49 秒）**；ruff check／format（161 files）、mypy（72 source files）、Python 邊界、scripts unittest 8、base／full graph、OpenAPI drift 均通過；wheel 4 passed／migration head 0012。ARM API `whisky-discovery-api:t09-gate2` build 成功（image `sha256:319ac71fd32bfa08752a7228d18909ec2b53ebf447942df8dfe39395afc66155`）。專案專用 Workers AI Read token 經使用者在建立當下核准，僅存 ignored secrets；verify active、Qwen 真 inference HTTP 200，沒有沿用其他產品 token。

- VM cutover 已完成角色／0012 migration／登入 trigger／Temporal schema 與專用 namespace。bootstrap admin 輪替 job exit 0，舊密碼真 TCP 登入失敗；更新 final env 並重建 DB 後，control-reconcile exit 0／3 筆完整外部紀錄，API healthy。輪替後加密 bundled full `20260929-190627F`（DB 51,810,372 bytes、repo 6,524,224 bytes、7 秒）成功；空庫還原 gate 尚待驗，公開 tunnel 保持停用。真 VM 首次 stanza-create 因預設 postgres DB role 不存在失敗，明確加入 `pg1-user=whisky` 後 check／backup 通過。
- 公開 readiness 新行為：missing helper import 取得 RED，再實作固定 API URL／2 秒 timeout／manual redirect／no-store 的匿名 200 或 503，捨棄上游 body。`pnpm --dir apps/web test` → 106 passed，typecheck／Web boundaries／原生 Next build 通過；Node／workerd Playwright 7 passed，含未設定 API 時 `/health/ready` 真 Node 503。前一版 CI push `36608439778` 與 PR `36609451289` 的 backend／web job 各自 success，GitGuardian pass。

- VM 輪替後空庫 restore：full `20260929-190627F` 命令 8.19 秒／PG 可連線 9.53 秒，產品 head 0012、users 2／identities 2、login trigger ALWAYS、Temporal persistence 1.18／visibility 1.9。舊 admin 密碼失敗、無應用 gate 的 runtime 在對帳前登入被拒；recovery IAM 完整對帳 3 commands 後，合成 owner 的 private API 200/no-store。
- VM waiting infrastructure workflow 在 live Temporal 保存等待，再 bundled full `20260929-191909F`（DB 51,843,140 bytes、repo 6,536,160 bytes、8 秒）。從另一空 volume WAL PITR 至 `2026-09-29 19:23:49.300103+00`，保留 gate marker `19:23:49.146045`，未包含 `19:23:50.451639` 提交；PG 接受連線時仍在 recovery，必須另等 `pg_is_in_recovery=false`，觀測 promotion 上限 36.28 秒。隔離 Temporal server＋新 worker 恢復 waiting history 並完成（9 events），含人工編排總經過 75.88 秒；這不宣稱空 VM RTO 或一般 RPO SLA。兩份正式私人資料合法 full 的最早點目前為 `20260929-190627F`，較早 preliminary full 仍只限初始遷移回退。
- 外部匿名 readiness monitor 的缺模組 import RED→固定 public URL、HTTP 200／exact ok body／no-store、HTTP／network failure GREEN，scripts unittest 合計 10 passed；ruff pass。本機在 tunnel 停機時真 probe exit 1（HTTP 403）；GitHub runner 真 outage／復原 job 結論與通知收件仍待驗。

獨立 design review 的累積 finding 對帳（每輪修正均須保持前輪已修項）：

| Finding | 狀態／證據 |
|---|---|
| 單一控制庫可能整組遺失、保留期未證 | 雙 bucket 全庫比對與真 IAM 已修「單桶遺失」；共同管理域與最舊可還原點仍開放，須用 VM 備份／保留期實測界定。 |
| 舊 Compose job 在 DB 重啟後可能放行 | `0012_recovery_gate`、真 Docker restart／API ready 負例已修；VM canonical DB recreate 後重新對帳，公開 ready 由503恢復200。 |
| runtime／schema 共用管理權或 PUBLIC 跨庫存取 | 角色分離、PUBLIC 撤權、獨立真 PostgreSQL 角色負例通過。 |
| 還原直接讀其他業務模組資料表 | 改用 `discovery.public`／`research.public`，定向與完整 DB 回歸通過。 |
| 結果時間戳不是因果序 | clock-skew 真 DB RED→GREEN 與重複位置拒絕已修。 |
| V1 控制紀錄依賴可變 current model | V1 codec／effect 全路徑固定，未來模型變動的 RED→GREEN 通過；新 plan schema 屬 T10。 |
| witness-first 寫到一半無法恢復 | 本機故障注入及真 OCI recovery IAM 補寫通過。 |
| 省略 overlay／舊 image／舊管理員 URL 繞過應用 gate | PostgreSQL login trigger、舊程式連線負例、base／full Compose 靜態檢查已修；VM admin 已旋轉，空庫還原後舊密碼與未對帳 runtime 登入均真拒絕。 |
| 第一個 full 在 gate／admin 旋轉前，沒有合法私人資料還原點 | final設定／epoch對帳→旋轉後 bundled full `20260929-190627F`→空庫還原與舊憑證／舊程式負例均通過；合法私人還原點從此full開始，不使用 preliminary full。 |
| 外部 monitor 跟隨 redirect 可誤認其他端點健康 | 真 HTTP 302→另一 ok 端點先 RED，再用拒絕 redirect handler GREEN；目標端點未被請求。scripts 11 passed；schedule default branch／60 天 inactivity 的存活檢查已寫 runbook。 |

- 未完成：default branch 首次 schedule；現有同 VM 空庫演練不宣稱空 VM RTO。T09 未驗收；post-rotation restore 與基本真登入／研究／恢復通過後，control 為下述有界驗收暫時啟用，驗收頁移除後已恢復停用，等待最後 schedule gate。

- T09 VM 正式目錄 `/opt/whisky-discovery`：每日 Asia/Taipei 03:15（最多20分鐘 jitter）timer active，首次 systemd service Result=success；canonical DB secret mount 經 `docker inspect --format ...Mounts` 核實後強制 recreate，再 fresh control-reconcile，final full `20260929-193331F`（repo 6,540,672 bytes、7 秒）。Web 在切換期間 ready 503/no-store，完成對帳後 200/no-store。`pgbackrest --stanza=whisky --output=json repo-ls --recurse` → 229 files／47,749,376 bytes。三款人工覆核 manifest 真發布 release `e629c492-07a7-46e7-82f0-ef20c58202b4`，沒有發布合成酒款。
- Monitor 獨立複查 NO DESIGN FINDINGS；scripts 11 passed／ruff check與format通過。push run `36634413509` 的實際 public-readiness job failure，但 response 403／1010 為 Cloudflare 封鎖預設 Python User-Agent，不能算 VM 停機 gate。明確 `WhiskyDiscoveryAvailability/1.0` header 先測 RED（None），實作後 GREEN；真 Python 使用該識別取得200/ok，沒有冒充瀏覽器或降低WAF。將重做受控 outage→復原。

- 受控停機重新驗證：commit `4f07caa` 的外部 Actions run `36634780232` attempt 1，public-readiness 真 HTTP503／exit1；Tunnel復原後相同run attempt2 public-readiness success，本機固定probe200/ok。這才是停機→復原證據，前次403/1010不算。monitor schedule 尚需defaultbranch第一次實際執行，通知收件待核對。

- 真 artifact 回退：Oracle ARM Web `4f07caa`→先前相容 image `c87bcfa`→`4f07caa`，公開200/ok/no-store恢復各14.99／14.83／14.98秒；每步以固定 monitor識別完整公開路徑驗證，DB epoch `2026-09-29 19:33:15.575116+00`／schema0012 前後一致，未退schema或還原正式DB。兩版Web產品程式相同，這證明artifact切換與前版可服務，不外推未來所有程式版本相容。
- 最新commit `4f07caa` 的 runs `36634785243`／`36634780321`，backend／web jobs 各自 success，GitGuardian success；public-readiness run `36634780232`復原attempt2 success。AGENTS.md去掉過期T07/T08進度，改指向唯一計畫；README修正已部署狀態但不宣稱T09完成。
- 2026-09-30 真 Chrome／Google／Auth0 登入後，經公開 Worker→VPC→VM Web 建立果香、TWD 2,500 研究；完成報告只列兩款合格候選（978／816 TWD、700 ml、TW、查核日 2026-09-28），本次官網讀取保持未覆核區塊。Reload 保留同一任務與完成報告。固定 T08 版本不明語料進入「等待版本補充」；`ssh oci-a1 'sudo docker restart whisky-discovery-worker-1'` 後，inspect 顯示新程序起點 `2026-09-30T02:45:41.60716939Z`，返回任務清單可找回同一等待工作與原期限，選 12 年補答後同任務完成且起點明示 12 年。真外部來源讀取失敗保留 `SOURCE_HTTP_ERROR` 與未覆核觀察，未冒充新正式事實。一般「我喜歡格蘭菲迪」描述未觸發消歧，留作 T10 雙入口／明確版本契約的實測反例；不把固定語料通過推論成任意描述已支援。尚待跨帳號、控制旅程與告警收件／schedule，T09 仍未驗收。
- OCI Usage API以 `RequestSummarizedUsagesDetails(query_type=COST, granularity=DAILY, group_by=[currency])` 並完整pagination，查詢 `2026-09-01T00:00:00Z`–`2026-09-29T00:00:00Z` →28 rows／SGD／computed_amount 0；最新reported_end為9/29UTC。新部署與Object Storage之後費用尚未全部結算，不外推持續免費。
- 真 Chrome原生UI登入已完成；browser extension連線policy失敗，nativeChrome可操作，沒有繞過安全warning。真JWT研究／跨worker恢復見上；跨帳號／控制總驗收與通知收件繼續核對，不保留過期的 passkey 等待狀態。
- 暫時 T09 真 API 驗收頁沿用 `/account` callback，不新增 Auth0 callback／scope，memory-only token 不輸出；只有 Web public mount，正常 API／worker 未換成合成來源。等待任務取消首次202/pending，同key重送200/completed且command ID相同，task cancelled／問題關閉／report null。另一等待任務改條件首次202/pending，同key重送200/completed，plan revision1→2、舊task superseded／report null。獨立 recovery IAM 以 `read_complete_control_log(primary,witness)` **只讀**全庫驗5 commands，兩筆 live cancel／change各completed，雙庫全分頁與body比對通過；沒有對live DB跑還原job。原owner的plan／task／report讀取各200/no-store，第二身份隔離待驗。
- 告警收件已通過：真Chrome核對 Will413028 的 Actions通知現值為 Email／Failed workflows only，沒有修改設定；只搜尋本專案的 GitHub通知信，9/30 05:40收件、commit4f07caa，信中 `public-readiness Failed in 7 seconds`，安全解析的run連結為 `36634780232`，對應已驗HTTP503的停機attempt1。不是先前403/1010的run；通知連結中的email token不保存至repo。Web驗收工具變更後Vitest106、typecheck、boundaries、nativeNextbuild與Node/workerdPlaywright7均通過；不以工具編譯取代真API證據。
- 第二真 Google 身份核對 actor 與原owner不同；原owner已驗plan／task／report各200/no-store，同一組UUID在第二身份下各404/no-store。驗收後只重建本專案正常Web／API、取消暫時public mount，control flag恢復0，DB／Temporal／worker及其他專案未改；固定health probe通過，`curl --user-agent WhiskyDiscoveryAcceptance/1.0 .../__recovery_probe.html` 真404。`01d0f88` CI runs `36663207789`／`36663209945` 的backend jobs各success（4m22／4m19），web各success（1m30／1m32）、GitGuardian pass；first default-branch schedule仍須在合併後核對，不以push/PR取代。
- T09 最後出口已通過：Actions [`36699573571`](https://github.com/Will413028/whisky-discovery-agent/actions/runs/36699573571) 的 event=`schedule`、headBranch=`main`、headSha=`c209f8d3b9fe44f86789dddb7efcee1402c5cd0c`；`public-readiness` job 與真正 `check_public_health.py` step 各success（UTC 2026-09-30 09:59:08–09:59:14）。以 `gh run view ... --json event,headBranch,headSha,jobs` 直接核對，不以push／dispatch代替。未修改cron或重新啟用workflow，不能從這次成功推論先前延遲的根因。
- 最後 gate 後，先查真 API image仍為`aa3a5aa`、runtime control flag=0、Compose files僅本專案正常base＋research overlay；只將 ignored `/opt/whisky-discovery/deploy/.env` 的 `WHISKY_CONTROL_ENABLED` 改1，config --quiet通過，再先stop／後no-deps force-recreate本專案api。真runtime確認control_enabled=1、recovery_required=1；公開完整路徑 `/health/ready` 回200／ok，匿名POST cancel回401／UNAUTHENTICATED。未重建DB／Temporal／worker或其他專案；T10新程式沒有部署。T09據此標已驗收，空VM完整重建RTO仍不在本項承諾。
