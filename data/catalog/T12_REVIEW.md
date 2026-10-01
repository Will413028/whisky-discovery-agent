# T12 覆蓋擴充覆核稿

狀態：Will 已於2026-10-01回覆「同意四款資料與價格處理」。原草稿 `t12-expansion.draft.json` 保持新增四款 reviewed=false；獨立覆核檔為 `t12-expansion.reviewed.json`，尚未部署或發布至產品 DB。前三款資料保持原值。

2026-10-01 的既有三款盤點見 `t12-coverage-20261001.json`：缺花香、乾果與煙燻的 reviewed tags，格蘭菲迪15年條件價仍不合格。標籤未記載不代表沒有該風味；共同／新增標籤只表示品牌描述可比較，不能證明風味強度或個人喜好。20–30款為規劃參考，這次以可解釋路徑選四款。

| 新增常規版 | TW 規格 | 品牌品飲描述的整理 | 台灣單瓶參考價草稿 |
|---|---|---|---|
| 麥卡倫 Double Cask 12 | 40%／700ml | 糖漬柑橘、香草、葡萄乾、太妃糖與柔和辛香；葡萄乾整理為乾果。 | TWD 1717，橡木桶建議售價；會員1631／多瓶1545排除。 |
| 拉弗格 10 | 40%／700ml | 泥煤煙燻、海藻、鹹味與甜味；不從甜味推定香草。 | TWD 1021，橡木桶建議售價；會員／三瓶970、六瓶919排除。 |
| 泰斯卡 Talisker 10 | 45.8%／700ml | 泥煤煙燻、柑橘、乾果、麥芽與胡椒；胡椒整理為辛香。 | TWD 1231，橡木桶建議售價；會員／三瓶1169、六瓶1108排除。 |
| 格蘭昆奇 Glenkinchie 12 | 43%／700ml | 花香、香草、奶油與柑橘；不由 Lowland 或未提煙燻推定低煙燻。 | 無合格價格。上層發酵顯示920–5520，單瓶／組合對應不明，未填 price observation，不以最低值篩預算。 |

來源與版本核對：

- 麥卡倫：[官方 Double Cask 12](https://www.themacallan.com/en/single-malt-scotch-whisky/double-cask-12-years-old)、[TW 規格／價](https://www.drinks.com.tw/product.aspx?Id=3320)。限定 Double Cask，不是 Sherry Oak／Triple Cask／其他容量；40%與700ml取台灣頁。官方描述葡萄乾，不從桶型自行推導風味。
- 拉弗格：[官方 10 Year Old](https://www.laphroaig.com/whiskies/10-year-old)、[TW 規格／價](https://www.drinks.com.tw/product.aspx?Id=16872)。限定40%常規版，不是 Cask Strength Batch、Sherry Oak Finish 或其他市場43%版本；全球品牌頁只引用該10年品飲描述。
- 泰斯卡：[官方常規10年](https://www.malts.com/en-gb/products/talisker-10-year-old)、[TW 規格／價](https://www.drinks.com.tw/product.aspx?Id=17374)。不使用 Special Release、Wild Blue 或禮盒價格。中文名稱採台灣來源「泰斯卡」；未添加來源沒有確認的 aliases。
- 格蘭昆奇：[官方12年70cl](https://www.malts.com/en-gb/products/glenkinchie-12-year-old-single-malt-scotch-whisky-70cl)、[TW 規格／未明價格](https://topfermenting.com.tw/zh-TW/products/格蘭昆奇12年-glenkinchie-12-year-old-lowland-single-malt-scotch-whisky)。限定12年常規版，不是 Distillers Edition；43%／700ml取台灣頁。

三個橡木桶頁已於2026-10-01直接HTTP200取得HTML，核對頁面本商品的建議售價／ABV／容量；不是從相關商品或頁首購物車取價。其他品牌與零售內容經 web 讀取，部分搜尋內容有快取，請人工開原頁核對。取得日與人工review date分開；新增reviewed_on目前仍為null。

擬展示路徑：果香／香草→麥卡倫的葡萄乾描述；香草→格蘭昆奇花香（無合格價，須關閉預算）；煙燻→拉弗格與泰斯卡的海藻／胡椒描述比較。尚未通過實際selector／UI旅程，不把資料盤點當成產品驗收。

覆核接受上述四個版本、來源支持、整理標籤及三個公開單瓶價；格蘭昆奇保持無合格價，沿用已同意的30個台灣日曆日政策。此稿不改舊snapshot、不自動發布。覆核檔已通過既有 publication guard；離線擴充盤點補足六項主要標籤、列出21個來源描述比較路徑，仍保留兩款價格缺口。這不代替實際 selector、模型或部署驗收。
