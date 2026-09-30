# 第一個持久研究流程設計

更新：2026-09-28。狀態：待實作與驗證。本文件細化 [ARCHITECTURE.md](ARCHITECTURE.md) 的第一個交付，不取代既有主待辦或宣稱應用已完成。既有平台、預算、資料權威與刪除契約維持不變；新增數值均為驗證預設，量測後才成為正式營運政策。

## 範圍與實作取捨

實作順序與每一步的 RED／GREEN／完成證據見 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)；本文件維持設計契約，不重複記進度。

交付旅程：登入 → 建立探索計畫 → 委託研究 → 查 reviewed catalog 與指定真實來源 → 提出版本問題 → 關頁 → 登入補充 → 同一 Temporal workflow 繼續 → 保存有引用的報告。另驗取消、重送、worker crash、舊 history replay 與還原防復活。

| 設計面向 | 可行方式與取捨 | 本流程預設 |
|---|---|---|
| Web 狀態 | 區域 state 簡單；集中 store 適合跨頁編輯；server cache 適合大量查詢但需整合事件更新 | 任務頁使用一份型別化 reducer 管 TaskView，REST 初載與 AG-UI snapshot 共用版本檢查；表單草稿用區域 state。先不加入全域 store。 |
| 進度通知 | DB 輪詢容易對帳；LISTEN/NOTIFY 延遲較低但需重連／專用連線；訊息服務增加營運元件 | API 對 DB 作短查詢輪詢，再輸出 AG-UI SSE；不在兩次查詢間占用 DB transaction 或 connection。量測後才判斷是否需要通知優化。 |
| 元件組織 | 依技術分資料夾容易起步；依功能分組方便讓畫面、契約與互動共同演進 | Web 依 plans、research、catalog 分組；共用元件只抽已有重複需求，第一段先用語意化 HTML 與 CSS，不在此階段綁定大型 UI 平台。 |
| VM 程序管理 | systemd 管 native service 開銷低；Compose 容器配置較一致；Kubernetes 增加調度與維運 | Docker Compose 作為第一個驗證候選，固定 ARM64 images／digest，API 與 worker 共用 image、不同 command。既有主機配置先盤點，不直接改動共用服務。 |

以上是本案工程預設，不是要求使用者逐一選套件；若入口測試證明不成立，再帶量測與替代提案重評。[Docker 單機 Compose 部署指引](https://docs.docker.com/compose/how-tos/production/)

## 模組與依賴

採用架構文件的功能／業務模組骨架，不另建服務 repo，並保留 `backend/src/whisky/` 的 Python src layout：

- `apps/web/src/app/`：路由、頁面組合與 Auth0 provider；`features/research/` 管進度、補充表單、報告與 AG-UI adapter；`features/plans/` 管計畫；`shared/api/` 封裝生成 client，`shared/ui/` 放無業務語意的共用元件。
- `backend/src/whisky/modules/`：catalog 管酒款與證據資格，discovery 管計畫／偏好／候選規則，research 管持久研究，library 管個人紀錄，identity 管使用者與外部身分對應。
- 模組內按需設 `domain/` 與 `application/`。create plan 歸 discovery；start research、answer clarification、read task、save report 歸 research。API、activities 呼叫同一套用例；跨模組 control command 經公開用例協調，不直接修改別的模組資料表。
- `modules/research/api/`：HTTP／AG-UI 轉接與串流生命週期；同模組的 `workflows/` 只協調 durable 工作，`agents/` 保存 prompts、工具定義與 typed output，`activities/` 是可重試 I/O 執行邊界，`adapters/` 放該模組的持久化與外部接合。
- `bootstrap/` 組裝依賴與 API／worker 入口；`platform/` 管 DB engine、logging、設定等技術能力。共用認證 adapter 提供已驗證 actor，各模組用例仍驗 owner／fence；domain 不 import framework 或 ORM。
- `contracts/`：生成 OpenAPI 與 Web types；AG-UI 使用協定 SDK schema，產品 snapshot 使用有版本的 Pydantic schema。不能另寫第二份手工 TypeScript domain。
- `deploy/`：Compose、release／restore 作業與非秘密設定樣板；只在實作需要時建立目錄與檔案。

Web 不根據模型文字解析價格或修改資料；Agent 輸出先轉成 typed proposal，經 domain 規則與交易驗證才保存。

Web feature 與後端模組各有公開介面，不跨界引用內部檔案；測試加入 import 邊界檢查。只建立當前功能需要的檔案，不為每個模組複製 research 的完整層次。Python 開發使用 editable install；另以建置後 wheel 在乾淨環境、非 repo 工作目錄驗證 import 與 API／worker 入口，避免測試只靠本機原始碼路徑通過。

## 資料模型與不可破壞的約束

第一段使用 PostgreSQL 原生 UUID 欄位，以應用產生 UUIDv4；UTC `timestamptz` 保存時間，台灣價格日期另用 `date`。不以 UUID 排序代表工作先後，使用明確時間與 revision。金額採精確 decimal，不用浮點數。可查詢／約束的關係用欄位與 FK；條件快照與證據內容可用有 schema version 的 JSONB，不把整個產品塞進一份 JSON。

| 資料 | 核心欄位與約束 |
|---|---|
| `users`／`identities` | 內部 user ID、active／disabled、identity generation；`(issuer, subject)` 唯一，email 不作主鍵。 |
| `plans` | owner、條件 JSON、schema version、`conditions_revision`、identity generation、建立／修改時間；revision 只因研究條件變更而增加。 |
| `research_tasks` | owner、plan、條件 revision／snapshot、workflow ID、狀態、`view_version`、`write_allowed`、錯誤分類；workflow ID 唯一。以複合 FK 或等效 DB 約束確保 task 與 plan 的 owner 一致。 |
| `command_receipts` | owner、操作 scope、idempotency key、正規化 payload hash、target、處理狀態與結果；`(owner, scope, key)` 唯一，同 key 不同內容拒絕。涉及撤銷者仍依 VM 外控制紀錄契約，不以此表取代。 |
| `agent_turns` | owner、task、AG-UI thread／run ID、命令關聯、turn outcome；`(owner, thread_id, run_id)` 唯一。保存回合對應，不保存每個 token。 |
| `clarifications` | task、question ID、等待版本、問題與 typed answer schema、pending／answered／expired／closed、deadline、答覆 receipt；每 task 同時至多一個 pending 問題。 |
| `catalog_releases`／`catalog_items` | 不可變發布版本、酒款版本 ID、來源與 reviewed 狀態；報告保留引用的 release／item，不能因更新 catalog 讓歷史引用指向不同內容。 |
| `evidence`／`price_observations` | 來源 ID／URL、酒款版本、擷取／查核時間、欄位值、覆核狀態；價格保存 TW／TWD、容量、ABV 與條件。Agent 觀察不直接變成 reviewed。 |
| `reports` | task、artifact key、條件／catalog／policy／prompt／model 版本、內容與 evidence IDs；`(task_id, artifact_key)` 唯一。第一段每 task 一份 final report。 |
| `library_conclusions`／`library_commands` | owner／generation、plan／task／report 關聯、當輪條件、選中或無適合、歷史選中名稱、替代版本、理由與取捨；一般保存與 receipt 同交易。plan-scoped 分頁索引含 owner／generation／plan／時間／ID，排除 hidden rows。收藏與喝過回饋獨立於結論。 |

API 用 owner scope 查詢；外部傳入的 owner、workflow 名稱、queue、工具設定一律不可信。計畫列表以 `(owner_id, updated_at, id)` 為索引候選；單一 task snapshot 依主鍵查詢，不為 view version 重複加索引。問題用 task／question 定位，pending 唯一性以 partial unique index 保護；實際索引依 migration 與 query plan 驗證。

保存 report、task completed 與 view version 推進在同一 transaction；先鎖定或以條件更新檢查 owner、plan revision、generation、write fence。取消與完成競爭必須共用同一鎖定順序，測試取消先勝時不能保存晚到結果。每次進度 activity 帶穩定 operation key，重試不重複推進公開版本。

## HTTP 與 command 契約

以下為規劃路徑，已實作項目與證據見 IMPLEMENTATION_PLAN。薄 Worker 僅轉送至固定 VM Web binding；Node Web API proxy 限定路徑與方法，FastAPI 提供版本化產品 API，AG-UI 保留 `/agent` 入口。

| 路徑 | 用途與結果 |
|---|---|
| `POST /api/v1/plans` | 建立計畫；驗 typed 條件與 idempotency key；回 `201` 與 plan／revision。 |
| `GET /api/v1/plans`、`GET /api/v1/plans/{id}` | owner 範圍內的列表與恢復入口；列表使用有上限的 cursor pagination。 |
| `POST /agent` | AG-UI `RunAgentInput`；start、resume 經下述 mapping 呼叫同一 application command；不直接執行普通 Agent。 |
| `POST /agent/observe` | 應用定義的唯讀重新訂閱入口，回傳 AG-UI 事件；不接受新研究或答覆命令。 |
| `GET /api/v1/tasks/{id}` | 讀 TaskView，顯示當前狀態、問題、report reference、版本與觀察時間；不依賴 worker Query 一定在線。 |
| `POST /api/v1/tasks/{id}/clarifications/{questionId}/answer` | typed 非串流答覆入口，與 AG-UI resume 共用驗證及 Update ID；重送不重複提交。 |
| `POST /api/v1/tasks/{id}/cancel` | 啟動既有 control command；返回 receipt，嚴格區分待確認／已提出／已完成。 |
| `GET /api/v1/commands/{id}` | 回應遺失後查 command outcome；仍驗 owner。 |
| `GET /api/v1/reports/{id}` | 已保存報告及引用；不重新呼叫模型。 |
| `GET /api/v1/library/reports/{id}/conclusion-context` | owner 範圍的報告 parent 與歷史／目前條件 revision；只作 UI 提示，保存仍須交易驗證。 |
| `POST /api/v1/library/conclusions` | 保存目前條件的 completed report 選擇或無適合；一般 DB CRUD，回 `201` 與歷史快照；同 key 同內容回原 receipt，先重驗資料可見性。 |
| `GET /api/v1/library/conclusions`、`GET /api/v1/library/conclusions/{id}` | 私人歷史結論；列表必填 planId，以有上限的 cursor 分頁；歷史名稱／理由／條件不代表目前 catalog／價格資格。 |

所有 mutation 都有 command key；payload hash 由後端對驗證後的正規化內容計算，不接受 client 自報 hash。revision mismatch 回 `409`；格式錯誤 `422`；未登入 `401`；不存在或非 owner 統一 `404`；容量拒絕 `429`。錯誤格式包含 `code`、安全的 message、request ID、retryable 與需要時的 command ID。

`202` 只表示 command 尚未完成，body 必須有 acceptance 狀態，不能等同研究已被 Temporal 接受。串流尚未開啟時使用 HTTP 錯誤；開啟後用 AG-UI `RUN_ERROR` 與最新合法 snapshot，斷線本身不能把 task 改成 failed。等待 receipt 可由同 key 重送或 command 查詢對帳；不用 HTTP background task 承擔必須完成的操作。

## AG-UI、研究工作與重連

三種 ID 分開：`planId` 是探索計畫；每個 research task 對應一個 AG-UI `threadId`；`runId` 是一次 AG-UI 互動回合，與 Temporal runtime run ID 不同。新補充回合有新 AG-UI run ID，但仍指向同一 research task／Temporal workflow。重送原回合沿用原 run ID 與 command key，不重新建立任務。

`RunAgentInput` 的 messages／state／forwarded properties 都是 client input。後端只讀 allowlist 內的 typed command envelope，載入 DB 權威條件；不允許 client 改 owner、工具權限或既有報告。首輪建立 task/thread mapping，收到 runId 重送時先驗 mapping 與 hash。

第一版的 Web／API 應用契約使用 UUID 格式的 AG-UI threadId／runId；client 提供關聯鍵，server 驗證並綁定 owner／task／command，不把 ID 當授權。這是本專案的輸入限制，並非 AG-UI 規格要求所有 ID 都是 UUID。若新增會產生其他 ID 格式的外部 client，整合前須一起重評儲存、ObserveInput、TaskView 與生成 validator，不只放寬 start parser。

研究模組的 command receipts 以 `research_commands` 承接 start 與後續 answer；T04 只啟用已實作的 research.start scope，T06 以 migration 擴充該 scope 約束及 typed result。agent_turns 保留指向同一研究 command 表的 owner／task 複合 FK，無須為 resume 拆除 owner 約束或建立另一套回合 receipt。

TaskView 至少包含 `schemaVersion`、`taskId`、`threadId`、`conditionsRevision`、`viewVersion`、`status`、`stage`、`question`、`reportId`、`error`、`observedAt`。前端只接受相同 task 與期望 revision，且 `viewVersion` 更新的 snapshot；相同版本冪等，舊連線不得覆蓋新頁面。修改條件後重讀 plan，不把舊 task 的 revision 更新成本輪。

### 互動回合

1. 開始／接回時驗身份，輸出 `RUN_STARTED` 與 DB 的 `STATE_SNAPSHOT`。首輪尚未確認 Temporal 接受時，snapshot 必須顯示 acceptance pending。
2. 階段更新由 activities 交易保存後才可輸出。第一段只要求完整 snapshot；可選 step events 僅代表目前連線觀察到的進度，不捏造錯過的歷史步驟。
3. 等待補充時先保存 question 與等待版本，再輸出 snapshot／公開 messages snapshot，最後以 `RUN_FINISHED` 的 interrupt outcome 結束該 AG-UI 回合。研究 task 保持 `needs_input`，Temporal 持續等待。
4. 使用者用新 run 的 `resume` 回應 question ID，API 轉為同一 typed answer use case／Temporal Update；REST answer 入口使用相同 command receipt，不能各注入一次。第一段同 task 只容許一個 pending 問題。
5. completed 回傳已保存 report snapshot，再以 success outcome 結束回合；task failed 輸出安全的 `RUN_ERROR`。cancelled／superseded 先送產品終態 snapshot，再以 `TASK_CANCELLED`／`TASK_SUPERSEDED` 的 `RUN_ERROR` 結束尚未終結的回合；UI 顯示取消／已被取代，不能顯示研究成功。已結束的回合不再改寫 outcome。UI 的工作徽章始終依 TaskView。

此 mapping 依 [AG-UI events](https://docs.ag-ui.com/concepts/events) 與 [interrupts](https://docs.ag-ui.com/concepts/interrupts) 設計；必須以選定 Python／TypeScript SDK 版本驗證 interrupt／resume schema。若 SDK 尚不支援，不悄悄用普通 completion 代替等待，而是停止此 gate 並提出相容選擇。

### 串流與重新訂閱

- 每次 GET task 可獨立恢復畫面；觀察既有回合使用明確的 `POST /agent/observe` 應用入口，帶 task/run ID 且只讀，不冒充新使用者輸入或重送 resume。輸出仍採 AG-UI events；此路徑與標準 client 的 transport 接合需 contract test。
- API 先讀 snapshot，再每 2 秒短查詢一次；只在 view version 改變時推送。以輪詢避免「先讀再訂閱」漏訊息，DB 不可用則回可識別暫不可用，不造新狀態。
- 首個量測配置每 15 秒 SSE comment heartbeat，每條連線最多 60 秒；時間到關閉 transport，client 以 jitter 重新 observe。連線 timeout 不製造假的 run completion，也不取消 workflow。
- 每次重新 observe 都重驗 token／owner；定期輪詢亦檢查 actor、task 存取資格，token 到期關閉連線。登出清除畫面與本機 cache，abort 連線，不取消工作。
- 每使用者先限制兩條串流連線；多 tab／重新整理與慢 consumer 都須測試。送出佇列有上限，背壓過大關閉並讓 client 取最新 snapshot，不累積無界 RAM。
- observe 可能重送 run 邊界與 snapshot；前端 adapter 依已知 run／view version 去重。不得把觀察流的 EOF 當成成功或自動呼叫 start。
- observe 開啟後暫不可用以 `RUN_ERROR` code `OBSERVATION_UNAVAILABLE` 結束這次觀察串流，client 以 jitter 重連；資格失效用 `OBSERVATION_ACCESS_LOST` 並停止重連。兩者不寫入持久 task／run outcome，不把 task 改為 failed；UI 保留最新合法 TaskView。未開啟時仍用 HTTP 錯誤，401 要求重新取得有效身份，403／404 停止觀察，429／5xx 可退避重試。

## Workflow 狀態與等待

`acceptance_pending → queued → researching → needs_input → researching → completed`；研究中可再進 needs_input。未終結工作可進 failed／cancelled／superseded。這些是產品投影，Temporal 仍是執行權威。HTTP 不得自行把 queued 改 researching，進度 activities 才更新投影。

ResearchWorkflow 載入已保存條件 → durable agent 查 catalog／reader → typed 結果判斷待補或可結案 → 保存 question 並持久等待 → answer Update → 新 activities 重新核對 catalog／價格 → 保存 report。工具和模型 I/O 由 PydanticAI Temporal 整合與 activities 執行，不把整個 Agent 包成一個可重試的大 activity。

Update validator 做不含 I/O 的格式／等待版本檢查；handler 經冪等 activity 重驗 owner／fence 並保存 answer，才解除等待。成功 receipt 必須能在 DB commit 後、activity completion 前中斷時重取；不可提前清除 question。Workflow 在等待邊界重新檢查已接受的答覆，避免問題剛發布、尚未進 wait 時漏掉答案。[Temporal message passing](https://docs.temporal.io/develop/python/workflows/message-passing)

同一問題的並行 Update handler 要序列化；DB 以 question 狀態與答覆 receipt 作條件更新。同答案重送回原結果，不同答案競爭只能有一個被接受；workflow 完結前等已進入的 handler 完成，避免答覆已保存卻沒有回應結果。

失敗重試分成兩種：transport retry／activity retry 接回同一工作；已終結 task 的「重新研究」建立新 task 與新 command key，連回原 task 作來源，不嘗試讓已完成 workflow 因 HTTP 重送重啟。

## 用量、來源與資料政策的驗證預設

下列為首輪測試設定，不宣稱已符合帳戶配額或 SLA：

| 項目 | 預設與檢查方式 |
|---|---|
| 並行 | 全站最多 2 個主動模型／reader 執行名額；每帳號最多 1 個主動研究、3 個未終結 task；等待補充不占執行名額。名額由後端交易式配額管理，不能只靠前端 disable 或單 worker semaphore。 |
| 每 task | 最多 8 次模型 request、12 次 reader/tool I/O、累計 24,000 input tokens／4,000 output tokens；重試同樣計費並納入計量。這些是待 eval 調整的上限，不是模型能力敘述。 |
| 等待與期限 | 等待補充起點 7 天，到期 task failed，code `INPUT_EXPIRED`，允許另開研究；主動研究累計時間預算先 10 分鐘，與等待人類的 timer 分離。 |
| timeout／retry | reader 每次總期限 20 秒；模型每次 90 秒；可重試 I/O 起點最多 3 次，含首次。授權、schema、版本與政策失敗不盲重試；429 尊重 retry hint 及總預算。 |
| 每日額度 | 全站每日模型硬額度須從實際帳戶剩餘額度設定；沒有配置或無法確認可用量就拒絕啟動 live model。token 不直接等同 provider 計費單位；活動前保守預留、完成後結算，結果未知的呼叫不能退回全額。 |
| 來源 | 先人工選一小批能支援同一旅程的官方與台灣價格頁；reader 接受 source ID，由服務端 registry 解析 URL，不接受任意 model URL。每跳 redirect／DNS 解析都驗 HTTPS 與目的地；限制本文大小，失敗保存原因。 |
| 價格 | 沿用 PRODUCT_SPEC 的 30 天與合格報價上緣作驗證預設，集中 `PricePolicy` 版本，測到期、撤價、不同容量與邊界等價；仍標示為產品預設待收口。 |

配額預留以 task／activity attempt key 去重，程序重啟後不能清空；需要過期回收者要有 lease／fence，未確認外部呼叫已結束時不得提早釋放造成超額。此為業務用量控制，不另建任務派送 queue。

## 部署、測試與回退順序

開發環境先用本機隔離 PostgreSQL／Temporal；CI 執行離線 model／source fixtures，live eval 需獨立啟用且記錄模型版本、來源日期與用量。preview 必須使用獨立資料、namespace、Auth0 設定與 VPC target；若現有 VM 無容量，不硬建常駐 staging，先用本機 workerd 與限時隔離入口驗證。

| 階段 | 可審查產物與出口 |
|---|---|
| 入口驗證 | 鎖定相容 runtime／SDK，建立登入、private API 與兩段以上 AG-UI snapshot；真瀏覽器通過 hydration、token 到期、跨帳號、VPC flush／斷線重連。包含 interrupt／resume 與 observe 的協定測試。 |
| 資料與契約 | migration、生成 client、TaskView／command schemas、小批 reviewed 樣本；真 PostgreSQL 驗唯一約束、owner、revision、同 key 衝突及交易競爭。 |
| 持久研究 | 同一 workflow 完成查資料、等待與答覆；注入 DB commit 後中止、worker crash、重送／取消，產物不重複；跑舊 history replay。 |
| 發布與恢復 | ARM image、資源／連線池量測、VM 外備份與撤銷紀錄、空 VM 還原；完成既有架構的完整 restore gate 後才讓私人紀錄進正式環境。 |

每次 release 保存 commit、image digest、Web version、schema revision、workflow code／policy version。CI 驗 lint／typecheck、schema 生成差異、domain／DB／workflow／replay 與瀏覽器旅程；正常 PR 使用 fixtures，不偷用正式帳戶資料。

部署先做相容擴充 migration，再部署可重播舊 history 的 worker／API，最後 Web。若引入不相容 workflow，必須先通過版本路由與舊 worker 持續處理等待工作的演練；不得直接把全部任務轉到新 worker。Temporal schema 升級獨立排程與驗證，不混入一般 app release。

回退用上一版相容的 API／worker image 與 Web artifact；不自動 downgrade schema，不以整庫 PITR 當一般程式 rollback。破壞性 schema 清理等舊讀寫者退場後獨立執行。新版本故障時先停止新任務接收，保留可用舊 worker；無相容 executor 時明示暫停處理，不刪除 history 或重建工作。

第一段 log 使用 JSON，含 request／task／workflow／revision／error code，預設不記模型原文。健康檢查區分 process 存活、API 依賴可用、worker 可處理任務與備份新鮮度；本機 log 輪替設容量上限。外部停機告警的服務與通知目的地尚待選定，不把 VM 內自查當成能發現 VM 全毀；不因此先增加付費 observability 平台。

## 開發前仍須取得的證據

- OCI 帳戶、OS／磁碟／現有程序與剩餘容量；驗證所需外部帳號設定與 secrets 另按部署流程處理，本文件不授權存取憑證。
- AG-UI、PydanticAI／Temporal、原生 Next.js／Node 與薄 Worker 的相容版本及完整路徑驗證；模型 eval 與來源樣本可用性。
- 備份工具與 VM 外儲存配額、還原時間、最終保留政策；跨 VM 故障的實際告警方式。

這些證據依既有 Pending 的入口→垂直流程順序收集；本文件不另立一份平行進度清單。未通過入口測試前只建立必要骨架，不展開整個 MVP。

## T01 身份入口契約

`GET /api/v1/me` 驗證 access token 後，以 `(issuer, sub)` 原子建立或讀取內部 UUID actor，回 `{id}`。`GET /api/v1/actors/{actor_id}` 只讀取目前 actor 自己的身份視圖，以 SQL owner 條件限制；非本人與不存在都回 404。兩者均拒絕 inactive actor，私有回應均 `Cache-Control: no-store`。沒有修改或管理其他帳號的 endpoint。真 Auth0／VPC 各項證據及尚未完成的 gate 以 IMPLEMENTATION_PLAN 為準。

401／403／404／422／503 使用 `{code, message, request_id, retryable}`；不回傳 token、claim、DB exception 或身份是否存在的細節。此身份視圖只供登入與 ownership 入口驗證，不代表探索計畫／任務資源已建立。產生的 schema 見 `contracts/openapi.json`。
