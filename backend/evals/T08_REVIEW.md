# T08 固定語料與模型選型覆核

2026-09-29。語料 [`t08_cases.v1.json`](t08_cases.v1.json) 的六個案例、每例重複兩次、可接受行為與 1–5 分 rubric，已在首次真模型呼叫前由 `55dbb1c`／`1ceafcd` 凍結；沒有依結果改題。這是三款已覆核酒款、目前單次來源選擇流程的驗證，不代表完整探索產品或多輪工具品質。測試以隔離 PostgreSQL、Temporal local server、真 Workers AI 與真公開來源依序執行；模型測試資料使用合成 actor，沒有正式私人紀錄。

可用相同環境變數執行 `uv run --project backend python backend/evals/run_t08.py --model <model-id> --output <file>`；runner 需要隔離資料庫的 `WHISKY_TEST_POSTGRES_URL`、Workers AI 帳戶與 token，以及明示的每日 Neurons 上限。秘密只在執行時環境提供，不進結果檔。兩份逐次原始結果是 [`t08_qwen_final.json`](t08_qwen_final.json)（SHA-256 `ce00aa4935ba74f15b6735f1ceb62540279d420934e58d5cd2d45d0d4c4af02d`）與 [`t08_glm_final.json`](t08_glm_final.json)（`008abab8b59d572074a64f03c3604839aaffc8f4875be194378184e89f834d8a`）。兩者同為 prompt `research-v3-21f7456fece1`、價格政策 `price-30d-v1`、catalog 規則 `catalog-selection-v3-3`，也都使用含 output schema 與 envelope 的保守配額預留、保存實際 redirect URL 的同版程式。語料原先列 GLM 為候選；欄位是凍結時的假設，並非測後選型。

| 模型 | 完成／硬門檻 | 全案例中位／最慢 | 有模型呼叫的中位 | 來源可讀 | 隔離測試計入 Neurons |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3-30B-A3B-FP8 | 12/12、12/12 | 5.84／11.77 秒 | 6.20 秒 | 6/8 | 632 |
| GLM-4.7-Flash | 11/12、11/12 | 8.19／39.89 秒 | 12.90 秒 | 4/7 | 752 |

每次硬門檻均查保存報告、他帳號 404、當前 sealed release 的候選／價格資格、逐 claim 引用與版本、reviewed 問題選項，以及報告連結的未覆核來源觀察；成功讀取的實際 URL 與原 reviewed 引用分別保存。來源失敗只能留下錯誤狀態，不可轉成正式 fact、價格或「不存在」結論。GLM 的 `glenlivet_source_failure` 第二次在單輪結構化呼叫得到 provider HTTP 400，依非重試政策 fail closed，沒有保存報告。先前同 prompt、同語料但尚未補齊 quota／redirect provenance 的對照曾 12/12 完成，也曾出現 115 秒長尾；最終結果的 11/12 說明此候選不穩定，不能用前次成功覆蓋失敗。

下表是逐案例、兩次重複的**助理定性預評**，不是 Will 的人工簽核。分數依凍結 rubric：繁中可理解性／工具選擇／追問品質，`—` 代表該案例無追問；每格的 `1、2` 對應結果檔 repetition。兩個模型的報告文字與追問由同一 reviewed-data 規則產生，模型只決定 `source_index` 和 `focus`，因此繁中與問題品質分數相近。

| 模型／案例 | 兩次耗時（秒） | 兩次讀取 | 繁中／工具／追問 | 逐案例判斷 |
| --- | --- | --- | --- | --- |
| Qwen／fruit_under_2000 | 11.32、7.32 | 商店頁成功、成功 | 3／4／— | 候選與預算合法，也明說桶型差異未證實；兩次選可讀的已覆核台灣來源。 |
| Qwen／strict_800 | 0.25、0.26 | 不讀來源 | 4／5／— | 清楚回答無合格預算候選，沒有湊滿。 |
| Qwen／ambiguous_glenfiddich | 5.94、11.77 | 官方頁成功、成功 | 3／4／4 | 只問真有歧義的 12／15 年版本；答覆後候選仍可追溯，差異解釋較公式化。 |
| Qwen／glenlivet_source_failure | 6.10、6.30 | 官網 403、403 | 3／2／— | 沒把 403 當作無酒款，但兩次皆未選可讀台灣商店頁，保留明示限制。 |
| Qwen／conditional_solera_price | 5.28、5.74 | 官方頁成功、成功 | 4／4／— | Solera 條件不明價格未列入嚴格預算；改列有合格價候選。 |
| Qwen／unlisted_ardbeg | 0.29、0.28 | 不讀來源 | 4／5／— | 明確說本 release 未收錄，未捏造煙燻強度。 |
| GLM／fruit_under_2000 | 8.37、8.01 | 官網 403、403 | 3／2／— | 候選仍合法、桶型未知明示，但兩次選到不可讀官網。 |
| GLM／strict_800 | 0.27、0.28 | 不讀來源 | 4／5／— | 無合格價直接回覆。 |
| GLM／ambiguous_glenfiddich | 14.81、24.01 | 官方頁成功、官網 403 | 3／3／4 | 版本追問正確，第二次來源選到另一候選的不可讀官網。 |
| GLM／glenlivet_source_failure | 18.48、39.89 | 商店頁成功、第二次 HTTP 400 未讀 | 2／2／— | 一次選可讀台灣來源，一次模型呼叫失敗且無報告；本案例不符合出口。 |
| GLM／conditional_solera_price | 8.00、10.99 | 官方頁成功、成功 | 4／4／— | Solera 條件價未取得預算資格。 |
| GLM／unlisted_ardbeg | 0.28、0.31 | 不讀來源 | 4／5／— | 未收錄即停，不虛構比較。 |

**選型建議：Qwen3-30B-A3B-FP8。** 最終同版 Qwen 12/12 過硬門檻，GLM 有一次 provider 400；Qwen 的延遲與 Neurons 也較低。兩個候選都會選到不可讀官網，Qwen 在格蘭利威情境連續發生；T10 完整探索必須加入來源失敗後的可審計補讀與較有用的比較說明，再用真模型 rubric 驗證。現階段讀取失敗會留下明示的未覆核觀察與限制，正式候選仍只由 reviewed catalog 產生。結構化 `avoid`／`change` 硬偏好在資料不足時 fail closed，不能把標籤缺席推論成符合；T10 要加入有證據的比較政策。最終模型選型仍須依本表完成人工覆核，不能把助理預評寫成已有人類驗收。
