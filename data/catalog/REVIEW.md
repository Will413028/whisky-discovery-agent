# 第一段探索資料覆核稿

狀態：draft，尚未人工覆核／發布。資料為真實來源整理，與 backend/tests 的 Synthetic fixtures 分離。機器檔為 `first-journey.draft.json`；所有 reviewed 目前為 false，發布驗證必須拒絕它。

查閱日：2026-09-28。來源為本日透過網頁工具讀取的頁面內容；部分零售頁由搜尋快取提供（橡木桶 12 年頁約兩週／五日前、MY9 約兩日前），不能把取得日冒充直接向零售商確認售價日。人工覆核時須開啟原頁確認價格；未確認前，不作有效價格發布。

| 版本 | ABV／容量 | 品牌描述的整理摘要（不是客觀量測） | 台灣參考價草稿 |
|---|---|---|---|
| 格蘭菲迪 12 年常規版 | 40%／700ml | 梨子果香、奶油糖、麥芽、輕微橡木 | TWD 978；橡木桶公開建議售價。929／880 為會員或多瓶條件，排除。 |
| 格蘭利威 12 年常規雙橡木桶版 | 40%／700ml | 香蕉、鳳梨、蜜桃、梨子，伴香草及太妃糖 | TWD 816；橡木桶公開建議售價。775／734 為會員或多瓶條件，排除。不是 43% 首席三桶、200 周年或其他特別版。 |
| 格蘭菲迪 15 年 Solera 常規版 | 40%／700ml | 蜂蜜、香草糖、深色水果，帶肉桂及薑等香料描述 | MY9 顯示 1,180／1,400；價格條件未清楚辨識，`unconditional=false`，不列嚴格預算候選。不是 Distillery Edition／VAT 03。 |

來源：

- 格蘭菲迪 12：[品牌](https://shop.us.glenfiddich.com/products/glenfiddich-12-year-old)、[台灣規格／價格](https://www.drinks.com.tw/product.aspx?Id=1753)。品牌頁為美國市場，僅引用同名 40% 常規版的品飲描述；700ml 依台灣頁，不混入美國容量或美元價格。
- 格蘭利威 12：[台灣品牌](https://www.theglenlivet.com/zh-tw/whisky/格蘭利威-12-年/)、[台灣價格](https://www.drinks.com.tw/product.aspx?Id=1764)。品牌頁明示 40%／70cl。
- 格蘭菲迪 15：[品牌](https://shop.us.glenfiddich.com/products/glenfiddich-15-year-old)、[台灣規格／價格](https://www.my9.com.tw/products/格蘭菲迪15年-glenfiddich-15y)。同樣只引用品牌 40% Solera 常規版描述，容量與台灣觀察取零售頁。

探索範圍：以格蘭菲迪 12 的果香為起點，格蘭利威 12 提供熱帶水果／香草方向，格蘭菲迪 15 提供深色水果／香料方向。這是依來源描述安排的可比較路徑，不推定個人喜好、煙燻強度或順口分數；未知特徵仍未知。

覆核項目：版本／容量是否一致、每個 fact／tag 的來源是否支持、公開單瓶價格是否仍如此、30 個台灣日曆日是否採為展示政策。覆核完成後記錄 reviewer／日期，另建 reviewed 發布檔；不由 Agent 自動將本稿改為 reviewed。

資料契約補全：source `publisher` 使用品牌網站／零售商名稱；酒款 `reviewed_on` 使用本次人工覆核日期，與來源 `checked_on` 分開。`brand`、`official_name`、`market`、`version_label` 將上表既有版本判讀轉成有引用的 facts；未提供的別名仍未知，不代表沒有別名。年分 12／15 為明示年份，不能把缺少 `age_years` 的未來條目當成 NAS。

風味整理方式 `editorial_source_summary`／版本 `1`：把同一常規版品牌品飲描述整理為簡短中文文字標籤；果實種類可歸入「果香」，香草明述可歸入「香草甜香」，肉桂／薑明述可歸入「辛香」。保留較具體的奶油糖／太妃糖標籤，不從未提及推論不存在，也不導出強度、喜好或順口分數。`producer_tasting_notes` 是來源方感官描述的中文摘要；tags 是編輯整理，兩者型別分開。

新增 metadata 採新的 release ID／publication timestamp；先前提交的 snapshot 原樣保存於 `first-journey.v1.reviewed.json`。新發布必須具備 publisher／method／method_version／reviewed_on；舊 snapshot 的未知 metadata 不補造，歷史讀取仍可解析，但舊版檔案不符合新版發布驗證，不應重新匯入。

人工覆核已完成（2026-09-28T13:52:09.802747+00:00）：專案維護者回覆「已核對，同意三款資料與 30 日政策」。reviewed 發布檔為 `first-journey.reviewed.json`，原 draft 保留供拒絕路徑驗證；格蘭菲迪 15 的條件價仍不合格。這筆覆核不代表有即時庫存或保證售價。
