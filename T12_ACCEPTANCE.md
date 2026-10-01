# T12 驗收對照

此表追蹤 `PRODUCT_SPEC.md`「驗收情境」，不取代 `IMPLEMENTATION_PLAN.md` 的進度權威。列出的 test ID 是既有自動化入口，不表示所有正式部署出口已通過。正式 T10–T12 release 尚未驗收；部署 SHA、live model artifact、真人操作證據目前均待補。

測試 ID 以 `backend/tests/` 為根；`integration/` 使用隔離 PostgreSQL／Temporal，合成來源與模型不得當作真人或真模型證據。單列代表測試只覆盖其中一項必要保障，需連同相關完整 suite 與右欄出口核對。

| ID | 產品情境 | 代表 test ID | 尚待正式出口 |
|---|---|---|---|
| A01 | 新手不知道風格 | `integration/test_research_proposal_workflow_v4.py::test_model_proposal_becomes_a_durable_question_without_changing_conditions` | 固定 T10 corpus 完整新版 eval、繁中 rubric、新手真登入旅程 |
| A02 | 從喜歡的酒找相似選擇 | `integration/test_research_selection_v4.py::test_similar_strategy_returns_positive_common_evidence` | 真實起點／版本選擇、共同點與引用可理解性 |
| A03 | 保留特徵、改變另一個 | `integration/test_research_selection_v4.py::test_small_step_requires_retained_feature_and_cited_direction` | 熟手真模型與 UI 條件同步旅程 |
| A04 | 中途修改限制 | `integration/test_control_commands.py::test_condition_change_supersedes_open_work_but_preserves_completed_report` | 未指定欄位保留、舊理由不混入新結果的完整旅程 |
| A05 | 同名或庫外酒款 | `integration/test_research_selection_v4.py::test_unconfirmed_origin_requires_version_selection`；`test_unlisted_liked_origin_is_not_replaced_by_catalog_bottle` | 同名消歧／庫外轉向的真模型與人工操作 |
| A06 | 缺資料或條件無解 | `integration/test_research_selection_v4.py::test_unsupported_hard_requirement_has_no_candidates` | 不造價格／強度、不湊三支的真模型與無結果出口 |
| A07 | 收藏與品飲回饋 | `integration/test_library_preference_store.py::test_feedback_provenance_is_owned_revision_fenced_and_never_infers_tags` | 真登入收藏／喝過／明確偏好與跨瀏覽器回訪 |
| A08 | 來源與展示一致 | `integration/test_comparison_reports_v4.py::test_comparison_read_keeps_snapshot_and_scoped_sources` | 七款來源覆核、正式資料發布及展示內容逐項核對 |
| A09 | 小幅探索與風格對照 | `integration/test_research_selection_v4.py::test_contrast_identifies_axis_and_two_positive_sourced_descriptors` | 來源支持探索方向、無強度量測時明示限制 |
| A10 | 台灣預算篩選 | `test_catalog_prices.py::test_budget_equality_and_explicitly_disabled_price_filter` | 正式七款 release 的預算／關閉價格篩選旅程 |
| A11 | 價格資格邊界 | `test_catalog_prices.py::test_calendar_day_freshness_includes_day_30_but_rejects_missing_or_future_dates` | 最新正式資料查核日期、容量、來源與政策核對 |
| A12 | 保存並再次開啟 | `integration/test_library_revisit.py::test_revisit_resolves_current_prices_without_replacing_historical_choice`；`test_new_release_removal_never_substitutes_a_different_bottle_version` | 真登入跨瀏覽器、移除版本出口、跨帳號負例 |
| A13 | 串流中斷或晚到 | `integration/test_research_source_observation.py::test_source_observation_retry_keeps_first_content_and_cancel_fences_late_write` | 公開 Worker／VPC 路徑的中斷、重連、錯誤終態及 UI 保存負例 |
| A14 | 保存、匯出與刪除 | `integration/test_library_conclusions.py::test_receipt_failure_rolls_back_the_conclusion_and_never_acknowledges_saved`；`integration/test_account_export_store.py::test_deleted_plan_does_not_reappear_inside_account_export` | 大型匯出負載、完整 DB／history／traces／保留清除與真帳號旅程 |
| A15 | 備份與恢復 | `integration/test_control_restore.py::test_completed_plan_delete_reapplies_after_pitr_and_is_idempotent` | 新 schema 與 library 資料的空庫／WAL PITR、原文重清、到期政策與實際最舊還原點 |
| A16 | 背景研究與等待補充 | `integration/test_research_clarification_workflow.py::test_answer_after_worker_restart_searches_the_new_catalog_release` | 真登入關頁／換瀏覽器／補答／重送完整旅程 |
| A17 | 等待期間修改研究條件 | `integration/test_control_commands.py::test_condition_change_supersedes_open_work_but_preserves_completed_report` | 正式等待任務被取代、關閉問題、明確另開與歷史展示 |
| A18 | Worker crash 與重播 | `integration/test_research_crash_recovery.py::test_killed_worker_resumes_saved_question_once`；`test_research_replay.py::test_frozen_waiting_history_replays_with_current_v2` | 新 release 上的正式 worker crash／resume 與版本相容證據 |
| A19 | 研究與正式資料 | `integration/test_preference_proposal_publication.py::test_proposal_and_question_commit_together_without_changing_confirmed_conditions` | 研究與 sealed catalog 分離、外部指令／人工補充不獲發布權限的完整負例 |
| A20 | 部署後接續 | `test_research_replay.py::test_frozen_waiting_history_rejects_changed_commands`；`test_frozen_waiting_history_replays_with_current_v2` | 部署前已等待的舊任務在新 executor 接續，不能只測新建 workflow |

## 真實資料覆核

- 初始三款與新增四款共七款，新增四款已獲 Will 人工接受；版本、來源、風味與價格處理見 [`data/catalog/T12_REVIEW.md`](data/catalog/T12_REVIEW.md)。正式產品 DB 尚未發布此 release。
- 官方／零售來源查核與 review timestamp 以 [`data/catalog/t12-expansion.reviewed.json`](data/catalog/t12-expansion.reviewed.json) 每筆值為準；draft 保持未覆核，原三款資料不改寫。
- 30 個台灣日曆日政策沿用既有覆核。格蘭菲迪15／格蘭昆奇12保持無合格價格，預算啟用時不得用模糊區間或舊價補足。
- [`data/catalog/t12-expanded-coverage-20261001.json`](data/catalog/t12-expanded-coverage-20261001.json) 是來源標籤的離線 coverage，不是強度量測，也不等於全部 selector 路徑通過。
- 真 DB／selector 的四項回歸入口為 `integration/test_t12_reviewed_coverage.py`：預算排除、明確關閉價格篩選後花香比較、煙燻方向雙邊來源。已通過的結果見 IMPLEMENTATION_PLAN；尚無完整模型／正式瀏覽器出口。

## 人工與部署證據填寫

每個實際 journey 保存：日期、部署 SHA、catalog release ID、使用的來源查核日、關聯 Axx、test actor 的不透明標記與結果。不保存 JWT、email、密碼或私人原文。新手、熟手、隔離邊界、持久研究四條展示旅程均需真登入操作證據；鍵盤可達、手機主要流程、錯誤提示與恢復出口須逐條核對。未完成的欄位保持待驗，不從其他版本結果推論通過。
