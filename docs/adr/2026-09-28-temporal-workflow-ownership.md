---
title: Whisky Discovery Agent 採 PydanticAI 與 Temporal
date: 2026-09-28
status: active
tags: [whisky-discovery-agent, decision, pydanticai, temporal]
---

# 採 PydanticAI 與 Temporal

## Context

第一版已要求背景研究、等待補充與故障恢復。前案 114fb8c 建議 LangGraph 原生 Agent Server；使用者在三條路線比較後明確選「使用第三條」，即 Agent framework＋Temporal；隨後選定「PydanticAI＋Python 後端（建議）」。

- `external`：使用者本輪明確選擇 Temporal 路線；接續選定 PydanticAI＋Python 後端；未提供預算或特定雲限制。
- `inherited`：小型 reviewed catalog、台灣價格、探索計畫及可靠記憶仍成立，因本輪未變更產品範圍。
- `inherited`：不自建通用執行引擎仍成立，Temporal 正是承接這項責任的現成元件。
- `inherited`：舊 LangGraph、Agent Server、共用 TypeScript domain 只是提案，未採用，不作本輪限制；repo 尚無應用，沒有既有執行歷史要遷移。

## Options Considered

- **基準 A：LangGraph＋Agent Server**。完整原生 runtime 提供背景佇列與 persistence，整合邊界少；承擔該 runtime 的平台依賴。[官方說明](https://docs.langchain.com/langsmith/agent-server)
- **B：Agent framework＋Temporal（選用）**。Agent 推理與持久執行分工，Temporal 管 workflow、activities、等待及重試；需自行部署 worker，維護 replay 相容性及產品 UI 整合。[Temporal 文件](https://docs.temporal.io/develop/python/workers)
- **C：Agent library＋checkpointer，自行組裝執行環境**。掌控度高，但還需補完整背景派送與恢復管理；不符合本案不自建通用 runner 的原則。[Persistence 文件](https://docs.langchain.com/oss/javascript/langgraph/persistence)


### Agent framework

- **PydanticAI＋Python（選用）**：官方原生 Temporal 整合將 Agent 協調與模型／工具 activities 分開；需維護 Python 與 TypeScript Web 的 API 契約。
- **Mastra＋TypeScript**：同語言可共用工具鏈，官方 step／activity 映射明確；需驗證 step 內 Agent I/O、等待與取消的恢復粒度。
- **LangGraph＋Temporal**：可保留圖建模；需明確分配兩者的狀態與恢復責任，本案沒有既有 graph 必須沿用。

## Decision

- 採 B，Temporal 是研究任務生命週期的唯一執行權威；LangSmith Deployment／Agent Server 不再列為推薦 runtime。
- Agent framework 採 PydanticAI＋Python 後端，透過官方 TemporalDurability 整合；Web／後端以版本化契約連接，不維持全 TypeScript 假設。
- 產品資料與 Temporal history 分開保存；PostgreSQL 仍是配套建議。Temporal Cloud 或自架、Web／API 套件、身分服務、ORM、模型仍需選型。

## Rationale

使用者已在比較後選 B；沒有另行提供商業或學習動機，不代填。工程上的收益是把持久工作生命週期交給獨立平台，Agent framework 專注工具及模型協調。相較 A，代價是額外 worker／服務整合與 workflow 版本管理；沒有跨系統長交易不是排除 Temporal 的理由。

兩份獨立草稿都指出 A 的整合負擔較少，這個優勢仍成立；本次選擇並非證明 A 不足，而是依使用者選定路線承擔 B 的責任。C 的控制力不抵銷自行營運通用 runner 的工作。

選 PydanticAI 的理由是官方整合把模型／工具 I/O 放進 activities，Agent 協調留在 workflow，符合研究的恢復粒度；代價是 Python／TypeScript 契約。Mastra 官方把 workflow steps 映射為 activities，是否涵蓋 step 內每次模型／工具呼叫需實測，不能推論不支援或已等價。使用者已確認接受 PydanticAI＋Python 方向；這不等於 Auth、模型或雲端供應商已定。

## Expected Outcome

- 已接受工作在 worker 恢復後接續；等待補充不佔用模型呼叫，換瀏覽器可續辦。
- Activity 可能重做，但產品寫入不重複；取消、條件改版後的晚到結果不能覆寫現行探索。
- 用非正常中止、回覆重送及舊歷史 replay 驗證，而非只看聊天紀錄或 UI 重開。

## Followup

- 驗證後續收斂的跨語言 API／身分、部署及資料存取配套；沿用既有的技術入口驗證項。
- 持久研究骨架驗證接受／對帳、等待、worker crash、回覆去重、取消與舊部署恢復；沿用原垂直流程待辦。
- 模型以固定繁中語料評估；資料樣本與實際費用核對沿用原驗收工作，不另開平行進度表。

## Updates (2026-09-28)

- 後續選定 Next.js on Workers、AG-UI、Auth0 Free 與無網域的 Workers VPC 私有 API 路線；現行實作基準與未驗證條件見 `ARCHITECTURE.md`，本 ADR 的 Temporal／PydanticAI 決策不變。

## Invariants

- Workflow 只執行可重播協調；模型、HTTP、DB 等 I/O 經 activities，副作用由產品規則去重。
- 一個研究 task 對應一個 workflow 身分；長期探索計畫留在產品 DB，不建永不結束的使用者 workflow。
- 人為補充採有版本的 command；正式 catalog 與待覆核研究維持分離。

## Revocation Triggers

- 官方整合不能通過所需恢復粒度、等待或跨版本驗收時，先重評 framework；若 Temporal 路線仍無法滿足，另提取代本決策，不默默換回舊 runtime。
- 實際部署成本或 worker 維護需求超出可接受範圍時，重新比較完整執行方案。

## Related

- 本 ADR 即與使用者當場拍板的原始紀錄，無外部來源文件；使用者原話「使用第三條」，對應 Agent framework＋Temporal；後續回覆「PydanticAI＋Python 後端（建議）」，並允許建立及保存 ADR。
- 舊提案可由 `git show 114fb8c:ARCHITECTURE.md` 取回；它是提案，非被 supersede 的已採用 ADR。
- [PydanticAI Temporal 整合](https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/)、[Mastra Temporal 整合](https://mastra.ai/integrations/deploy/temporal/)、[安全部署](https://docs.temporal.io/develop/safe-deployments)。
- 沒有新增 Lessons Rule：這是本案選型，尚無已驗證的新通用機制，不抽取通用規則。
