# T10 真 workflow 評估：2026-10-01（未通過驗收）

Workers Free 前提由使用者確認。固定 corpus v1 與 controls v1 不變，13 題各執行兩次，結果完整保存在 `t10_qwen_20261001.json`。所有 26 次 workflow 共用一份隔離 DB 的 quota ledger，上限 6,000 Neurons，provider attempts 40，保守保留 4,052 Neurons；不將 unknown charges 當作零。

- corpus SHA256：`9f7dd1e012b3caa415fcc6dae8df126290975f82e1ef5ca4f29a74a066759e34`
- controls SHA256：`6bb4bb40b0e37abdd3db9353539a546e0495bbe6813a31138e33e04d10843179`
- 模型：`@cf/qwen/qwen3-30b-a3b-fp8`
- 26 次中 17 次全部硬規則通過，8 次 proposal workflow 的模型上游錯誤，1 次來源 fallback 的真替代來源讀取失敗。
- `beginner_daily_food_clues`、`beginner_unknown`、`patch_budget_only`、`patch_one_preference` 各兩次 `MODEL_UPSTREAM_ERROR`；需要定位 provider 回應，不推定為偶發容量或直接增加重試。
- `source_failure_fallback` 每次第一個來源為明示 fault injection；第一次真替代來源成功，第二次回 `SOURCE_TOO_LARGE`。完整已覆核報告仍可保存，但嚴格的 bounded failure→real alternative gate 未通過。
- 其他版本／候選資格、owner、模型不改 conditions、comparison 原子保存、來源 unreviewed 邊界負例均保留於每筆 hard gates。

這是正式模型＋本機真 DB／Temporal／真外部來源驗證，不是 Oracle、Auth0 或真瀏覽器旅程驗收。失敗結果不得改題、刪除或以成功子集取代。人工 rubric 尚未覆核；先修復模型錯誤並驗證來源 fallback，再提供可接受樣本覆核。

初次啟動使用 `/postgres` 而非 runner 明定的 `/whisky_test`，在模型呼叫前被 fixture gate 擋下；修正後才開始此輪，不計為行為 RED。

## 定位與修正回歸

相同 `beginner_unknown` 再跑兩次、共六個 provider attempts，捕獲 HTTP500／Cloudflare8005 Internal server error；診斷結果為 `t10_qwen_diagnostic_20261001.json`，保守保留702 Neurons。只記 provider status/code，不將 token 或 headers 寫入證據。

保持原 model、prompt、Pydantic schema、原文與 reviewed mapping validators，先以 PydanticAI `PromptedOutput` 限額實驗：`t10_qwen_prompted_unknown_20261001.json` 兩次 completed、全部 hard gates通過，3 attempts／281 Neurons。這是將故障縮小到 proposal 的工具輸出路徑的證據，未定位 provider 內部根因。

正式 proposal factory 改用 `PromptedOutput(PreferenceProposal)`，prompt fingerprint 納入輸出模式。研究來源 Agent 的 Tool Output 與舊 V1–V3 workflow 不改。資料仍由 Pydantic 驗 schema，原文引用與已覆核映射 validators 保留、最多一次 validation retry，不解析寬鬆自由文字。官方模式說明：[PydanticAI Output](https://pydantic.dev/docs/ai/core-concepts/output/)。

- 行為 RED：provider output tools 不應送往 proposal request → 1 failed；修正後 proposal／source quote／mapping／真 Temporal durable question 共11 passed，凍結舊 V2 history replay正負例2 passed。
- 正式修正後 `t10_qwen_prompted_food_20261001.json`：兩次飲食線索 needs_input、全部 hard gates通過，2 attempts／202 Neurons。
- `t10_qwen_prompted_patches_20261001.json`：預算／偏好修改各两次 needs_input、全部 hard gates通過，4 attempts／402 Neurons。
- 各後續隔離 ledger 的 allowance 僅為總6,000 cap扣掉先前完整 retained reservation 的剩餘值（1,948→1,246→965→763），不因換 DB 重置預算；全日累計保守保留 **5,639 Neurons**，未從 unknown charge 取回額度。

原先8次失敗的四類輸入均有修正後兩次回歸。完整26次新版本 eval／source fallback第二次／人工 rubric／真部署旅程仍未驗收；不將分批回歸改稱新的完整26次成功結果。

## 有界來源大小修正後回歸

實測原既定官網頁為1,151,728 bytes；固定下載界線由512 KiB改2 MiB，模型文字仍限2,000 chars，來源安全規則保持原值。合成同大小可讀頁取得行為 RED→GREEN，超界負例仍通過。

`t10_qwen_source_limit_20261001.json` 保留兩次原 source_failure_fallback、fault injection 與全部 hard gates。兩次均通過：第一次阻斷官網後真零售來源成功，第二次阻斷零售頁後真官網成功。共4 attempts／316 Neurons，執行時間9,043／9,113 ms；來源仍是 unreviewed observation，不能自行發布 catalog。

當日累计 **5,955／6,000 retained Neurons**，剩45；不再呼叫模型，也不重置隔離 ledger。原26次結果與分批修正證據均保留。來源兩次回歸已通過，但完整26次同一最終版本、人工 rubric及正式部署旅程仍未驗收。
