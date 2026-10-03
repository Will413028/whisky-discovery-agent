---
title: Whisky 恢復條件原文採有限期保留
date: 2026-10-01
status: active
tags: [whisky-discovery-agent, decision, retention, pitr]
---

# 恢復條件原文採有限期保留

## Context

V1 控制意圖與結果各含 `newConditions`，用於 PITR 精確重套已確認條件；後續刪除計畫時，它也成為原文副本。ARCH 原「不含被刪原文」與此恢復行為有衝突。Will 比較有限期恢復資料與遺失後重新確認，明確採前者。

- `external`：Will 要保留精確 PITR；本次選擇不是由既有 V1 的改寫成本代替產品需求。
- `external`：PITR 依賴可用 full backup／WAL；pgBackRest time=7 不是物件七天硬上限，須量測實際窗口。
- `inherited`：產品與 Temporal 同 cluster，還原會一起倒退；VM 外控制 fence 仍必要。
- `inherited`：有限預算、單人維運與不自建通用 runner 仍成立；清除協調沿用 Temporal。
- `inherited`：pending 不按年齡過期仍成立，否則未確認完成的撤銷可能失去安全依據；終結須先完成或明確拒絕。
- `inherited`：既有 V1 codec／history 必須可讀，已有正式資料；不代表原文可無限保留。

## Options Considered

- **基準 A：有限期恢復資料（選用）**。用途限定的備份／控制輸入，隔離還原後重套外部 fence；可精確恢復新條件，代價是刪除後仍有有限期原文副本。[PostgreSQL PITR](https://www.postgresql.org/docs/current/continuous-archiving.html)、[pgBackRest retention](https://pgbackrest.org/configuration.html#section-repository/option-repo-retention-full-type)。官方文件說明恢復與 expiry 機制，不替產品決定原文必要性。
- **B：opaque control metadata＋重新確認**。只存 scope、instance／generation、revision、hash 與結果；原文遺失時停止舊研究並重新確認。副本較少，代價是已確認條件不能保證自動重建；hash 不能還原原文。
- **C：分離加密 recovery inputs＋可撤銷 key**。安全 fence 與 inputs 分開，刪除時令 inputs 不可讀；需獨立且不可隨 PITR 回滾的金鑰生命週期，增加單人維運負擔。一般 bucket 加密不等於 crypto-erasure。

## Decision

採 A。主要產品原文即時清除、讀寫撤銷；條件修改新輸入分類為有限期恢復資料。從 final result 起至少30日，且最後可能還原到 effect 前的獲准備份窗口失效＋實測緩衝後才清除。控制 DB、primary／witness 與相關副本均列入驗收。

## Rationale

相較 B，A 保留 Will 選定的精確恢復體驗；代價是必須明列恢復專用原文副本與到期清除，不能說所有副本即時刪除。不選 C，因目前沒有立即不可讀的額外要求，金鑰恢復及撤銷依賴尚未具備。

兩份獨立草稿均指出 V1 不是必須沿用的產品約束、30日不是無條件 TTL、pending 長等待可能使「有限」失真；故本決策不以設定值或文件代替實際清除。恢復資料不得重新注入模型、公開或作一般產品讀取來源。

## Expected Outcome

- 一致 PITR 可重套已確認的新條件，同時已刪內容不復活。
- 刪除說明分清主要原文清除與有限期恢復副本；期限、內容、用途與實際到期結果可查核。

## Followup

- 沿 T11 資料管理項，完成 control DB／兩份外部紀錄、history／traces、備份／WAL 到期實測與正式 PITR。
- 定義 final 後有限清除、pending 正式終結、失敗告警、允許的還原下界與 witness 同步清除；pending 不可因年齡刪除。
- V1 reader 目前要求 result 有 intent，且 DB receipt 缺外部 pair 時拒絕；先驗合法清除的完整性契約，不能把到期移除當漏頁，也不能把漏頁當合法移除。
- 驗 pgBackRest actual oldest restorable point／expire 與 OCI retention；超出可驗窗口的還原保持隔離。
- 凍結 V1 相容性，新增契約時驗舊 history／record、清除中斷與最終實體不存在。

## Revocation Triggers

- 增加更舊或第二份 restore 來源、延長窗口，或無法驗證到期清除。
- 條件含更敏感資料、要求刪除後立即不可讀，或改變精確恢復承諾。
- 改 DB restore topology 或具備可靠的獨立金鑰撤銷能力。

## Related

- 本 ADR 即與 Will 當場拍板的原始紀錄，無外部來源文件；選項回覆：「有限期保留恢復資料（建議）：保留精確 PITR，條件原文列明至少 30 日及備份窗口後清除。」
- V1 prior state 可由 `git show 5ae5f47:backend/src/whisky/modules/control/journal.py` 與同 SHA 的 ARCHITECTURE／recovery.py 取回。
- [既有執行權威決策](2026-09-28-temporal-workflow-ownership.md)。
- [OCI retention rules](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/usingretentionrules.htm)：最低保留保護不是自動 expiry；不建立法定保存義務的假設。
- 無新增 Lessons Rule：此為產品保存／恢復語意選擇；既有 PITR 對帳原則不重複抽取。
