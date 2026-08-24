# SEDB 無界動態欄位資料庫：AI 原生稀疏結構、欄位治理與任務投影

**SEDB Unbounded Dynamic Field Database: AI-Native Sparse Structures, Field Governance, and Task Projection**

作者：Neo.K  
機構：一言諾科技有限公司（EveMissLab）  
版本：v0.1  
日期：2026-08-20  
文件性質：技術白皮書／系統架構論文／可執行 MVP 規格  
實作狀態：Local-first executable checkpoint  
核心系統：SEDB — Semantic Evolution Database  
本次子系統：SEDB-UF — Unbounded Dynamic Field Layer  
公開授權：尚未選定  

---

## 摘要

傳統資料庫通常假設 schema 在設計階段已大致確定：資料列持續增加，而欄位集合相對穩定。這個假設對交易系統、固定業務表單與穩定資料管線十分有效，但對 AI 原生研究、長期知識策展、跨領域分類、多 Agent 觀測與持續探索而言，欄位本身也會成為研究結果的一部分。AI 在處理資料時可能持續發現新的分類維度、證據欄位、失敗原因、來源屬性、不確定性量測或比較條件；若每次發現新維度都要求重做 schema、遷移全部資料或回填所有歷史紀錄，系統會迅速陷入維護成本與語義污染。

本白皮書提出 SEDB-UF（Unbounded Dynamic Field Layer），作為 SEDB 的無界動態欄位層。其核心原則是：

$$
\boxed{
\text{Add Field}
\not\Rightarrow
\text{Fill Field}
}
$$

也就是「新增欄位」與「填入欄位」必須被視為兩個不同事件。欄位可以存在於全域 registry 中，而對絕大多數紀錄保持合法空白。空白不是錯誤，也不需要被強迫轉成 `unknown`、`N/A`、零值或其他假佔位符。

令 $E$ 為紀錄集合，$F$ 為可持續擴張的欄位集合，$D_f$ 為欄位 $f$ 的值域，則邏輯資料模型為：

$$
V:E\times F\rightarrow D_f\cup\{\varnothing\}.
$$

實體儲存只保留真正存在的 cell：

$$
C=
\left\{
(e,f,v)
\mid
V(e,f)\neq\varnothing
\right\}.
$$

因此系統將「邏輯 schema 寬度」與「實體儲存密度」解耦。對任務 $Q$，系統又只需要啟用局部欄位支撐：

$$
F_Q\subseteq F,
$$

使具有上千或上萬個邏輯欄位的資料庫，在特定查詢、比較、審計或 AI 任務中仍可只渲染少量相關欄位。

SEDB-UF v0.1 已完成 Python + SQLite 的本地可執行實作，包括：動態欄位 registry、稀疏 JSON cell、真正的 blank-by-absence 語義、欄位生命週期、收斂理由考核、重新啟用、field proposal queue、Task View、搜尋、CSV/JSONL 交換、本地 HTTP API、瀏覽器 UI 與 CLI。實際驗證資料庫註冊 10,000 個邏輯欄位、3 個 entity、僅 9 個實際 cell；邏輯容量為 30,000 個 entity-field 配對，而實體 cell 密度為 $0.0003$，即 $0.03\%$。完整測試為 31 項通過。

本系統所稱「無界」是架構上的開放欄位集合與持續擴張能力，不代表 v0.1 已實證任意大或數學意義上的無限規模。v0.1 的工程驗證錨點為 10,000 個邏輯欄位。

**關鍵詞：** AI 原生資料庫、動態 schema、稀疏資料、無界欄位、欄位治理、Task View、SEDB、知識演化、Agent、事件溯源、資料策展

---

# 0. 定位與邊界

SEDB-UF 不是要宣稱固定 schema 資料庫已失效，也不是要用一種資料模型取代所有關聯式資料庫、圖資料庫、文件資料庫或向量資料庫。

本系統處理的是一個更狹義但在 AI 時代逐漸重要的問題：

> 當「該有哪些欄位」本身也是持續被 AI、研究者與資料發現流程改寫的研究結果時，資料庫應如何保存、治理、搜尋與投影這些欄位？

因此 SEDB-UF 的主要場景不是傳統訂單表、會計表或固定 ERP schema，而是：

- 長期研究資料庫；
- 大型分類與策展系統；
- AI 對資料持續提出新維度的工作流；
- 論文、人物、組織、產品、事件、理論或實驗的異質紀錄；
- 多 Agent 共用但不要求所有 Agent 使用完全相同欄位的知識系統；
- 需要保留欄位產生、收斂、合併、拆分與停用理由的資料基礎設施。

本白皮書也不將「邏輯無界」偷換成「物理資源無限」。任何實際系統仍受到記憶體、磁碟、索引、查詢延遲與治理成本限制。SEDB-UF 的主張是：欄位集合不必在 schema 設計階段封閉，也不必因為欄位數增加就強迫每筆資料付出等比例的實體儲存成本。

---

# 1. 問題：真正的 AI 原生填表不是把 Excel 做得更大

人類表單通常隱含一個固定前提：

1. 先決定欄位；
2. 再建立表格；
3. 再要求資料逐欄填入。

AI 的資料工作流卻可能反過來：

1. 先觀察一批資料；
2. 發現原 schema 無法區分某些案例；
3. 提出新欄位；
4. 只有部分 entity 需要補值；
5. 新資料又揭露新的分類差異；
6. 某些欄位逐漸失去資訊增益；
7. 某些舊欄位在新任務中重新變得重要。

也就是：

$$
F_0
\subset
F_1
\subset
F_2
\subset
\cdots
$$

欄位集合本身成為時間函數：

$$
F=F(t,Q,\mathcal D,\mathcal A),
$$

其中 $t$ 表示時間，$Q$ 表示任務，$\mathcal D$ 表示目前資料狀態，$\mathcal A$ 表示參與的 Agent 或研究流程。

若仍以傳統「一個欄位等於一個永久 SQL column」理解這種工作流，會出現三個問題。

第一，schema migration 成為持續性成本。  
第二，歷史資料被迫產生大量假空值或佔位符。  
第三，資料庫無法回答「這個欄位為什麼會存在」。

因此本系統將欄位從「表格的一個固定位置」提升為「具有身份、狀態、版本與治理歷史的第一級物件」。

---

# 2. 與原始 SEDB 的關係

原始 SEDB 的核心問題是：

> 知識為什麼變成現在這樣？

它重視：

- claim；
- provenance；
- epistemic status；
- version；
- event sourcing；
- derivation lineage；
- semantic evolution。

SEDB-UF 不取代這一層，而是補上一個更底層的「動態表示空間」。

可寫成：

$$
\boxed{
\text{SEDB-UF}
\rightarrow
\text{Dynamic Representation Space}
\rightarrow
\text{SEDB Semantic Evolution}
}
$$

其中 SEDB-UF 處理：

- 有哪些可用欄位；
- 欄位何時新增；
- 欄位是否活躍；
- 哪些 entity 真正存在該值；
- 欄位何時收斂；
- 為何收斂；
- 哪個任務需要哪些欄位。

而上層 SEDB 可以進一步處理：

- 某 cell 或 claim 的來源；
- 主張的認識論狀態；
- 概念分裂與合併；
- 推論與觀測的區分；
- 跨版本的語義演化。

因此兩者的差異不是資料庫 A 與資料庫 B，而是：

$$
\text{Field Space Governance}
\neq
\text{Semantic Claim Governance}.
$$

但兩者可以共用事件溯源、來源記錄與可追蹤治理思想。

---

# 3. 核心設計原則

SEDB-UF v0.1 採用八個核心原則。

## 3.1 新增欄位不等於填入欄位

$$
\boxed{
\text{Add Field}
\not\Rightarrow
\text{Fill Field}
}
$$

欄位註冊只表示「系統承認這個維度存在」，不表示任何歷史 entity 都必須補值。

## 3.2 空白以 absence 表示

若 entity $e$ 在欄位 $f$ 沒有資料，系統不建立 cell：

$$
(e,f)\notin\operatorname{Dom}(C).
$$

這與下列值都不同：

- `false`
- `0`
- `""`
- `null`
- `"unknown"`
- `"not_applicable"`

它們都可以是某些 value domain 中真正存在的值。

## 3.3 邏輯寬度與實體密度分離

邏輯容量為：

$$
L=|E||F|.
$$

實體 cell 數量為：

$$
|C|.
$$

資料密度定義為：

$$
\rho=
\frac{|C|}{|E||F|}.
$$

系統成本不應被迫隨 $L$ 線性實體化。

## 3.4 欄位是第一級物件

每個 field 至少具有：

- 唯一 ID；
- key；
- label；
- value type；
- description；
- lifecycle status；
- created time；
- updated time。

欄位不是匿名 column。

## 3.5 收斂是治理，不是刪除

$$
\text{Converged}
\neq
\text{Deleted}.
$$

收斂只代表系統目前不需要主動擴張或優先填充該欄位。歷史資料與欄位身份仍然保留。

## 3.6 收斂必須有理由

從 `active` 進入 `converged` 時，空理由應被拒絕。

$$
\operatorname{Converge}(f)
\Rightarrow
R_f\neq\varnothing.
$$

## 3.7 任務只啟用局部欄位

對任務 $Q$：

$$
F_Q\subseteq F.
$$

全域 registry 可以很大，但 UI、Agent 或查詢不必每次讀取全部欄位。

## 3.8 所有擴張都應可審計

欄位新增、收斂、重新啟用、合併、拆分與停用都不應只剩最後狀態，而應保留事件或評估歷史。

---

# 4. 形式資料模型

令：

$$
E=\{e_1,e_2,\ldots\}
$$

為 entity 集合，

$$
F=\{f_1,f_2,\ldots\}
$$

為動態欄位集合。

對每一個 field $f$，存在值域 $D_f$。資料映射定義為：

$$
V:E\times F\rightarrow D_f\cup\{\varnothing\}.
$$

其中 $\varnothing$ 代表「沒有 cell」，而不是值域中的特殊值。

實體 cell 集合：

$$
C=
\left\{
(e,f,v,s,c,t)
\right\},
$$

其中：

- $e$：entity；
- $f$：field；
- $v$：JSON 可表示值；
- $s$：source；
- $c$：confidence；
- $t$：updated time。

v0.1 在 SQLite 中以 `(entity_id, field_id)` 作為 cell 主鍵，因此同一 entity-field 配對在當前狀態最多存在一個 cell。

若需要完整 cell versioning，可在後續版本加入 append-only cell event ledger，而不需要修改本白皮書的核心 sparse model。

---

# 5. 實體儲存架構

v0.1 使用 SQLite 正規化結構，而不是動態執行大量 `ALTER TABLE ADD COLUMN`。

核心表：

```text
entities
fields
cells
field_events
field_evaluations
field_proposals
task_views
task_view_fields
```

其關係可以抽象為：

```text
fields -------------------+
  |                       |
  |                       v
  +--> field_events     cells <-- entities
  |
  +--> field_evaluations
  |
  +--> task_view_fields <-- task_views
  |
  +--> field_proposals   (pre-registry proposal space)
```

其中 `cells` 只保存真正存在的值。

這個設計使欄位增加時不需要：

1. 修改 `entities` table schema；
2. 為所有既有 entity 建立新 column；
3. 回填大量 `NULL`；
4. 重建整張寬表。

---

# 6. Field Registry

欄位 registry 是 SEDB-UF 的核心。

每個 field 包含：

```text
id
key
label
value_type
description
status
created_at
updated_at
```

其中 `key` 唯一。

v0.1 支援批次註冊欄位，因此可以一次建立大規模邏輯欄位集合。批次內重複 key 會被拒絕，既有 key 衝突也會失敗，而不是默默覆蓋。

此設計使 AI 可以先提出或註冊大量候選維度，再由後續資料工作流決定哪些 entity 需要填值。

---

# 7. 欄位生命週期

v0.1 支援：

```text
proposed
active
converged
merged
split
deprecated
```

主要合法轉換為：

$$
\text{proposed}
\rightarrow
\{\text{active},\text{deprecated}\}
$$

$$
\text{active}
\rightarrow
\{\text{converged},\text{merged},\text{split},\text{deprecated}\}
$$

$$
\text{converged}
\rightarrow
\{\text{active},\text{merged},\text{split},\text{deprecated}\}.
$$

目前 `merged`、`split`、`deprecated` 為終止狀態；更完整的 lineage graph 可在後續版本加入。

## 7.1 收斂

收斂事件至少保存：

$$
R_f=
(
r,e,m,a,\chi,t
),
$$

其中：

- $r$：reason；
- $e$：evidence；
- $m$：metrics；
- $a$：evaluator；
- $\chi$：reversible；
- $t$：timestamp。

`reason` 為必填。

## 7.2 重新啟用

若新任務、新資料或新證據使已收斂欄位重新具有區分力：

$$
\text{converged}
\rightarrow
\text{active}.
$$

重新啟用同樣要求理由，避免欄位治理變成無法追蹤的開關。

---

# 8. Field Proposal Queue：AI 不應直接無限制污染 Registry

AI 可以非常快速地提出新欄位，但「能提出」不應自動等於「永久加入全域 schema」。

因此 v0.1 將 proposal 與 active registry 分開：

```text
field_proposals
```

proposal 至少包含：

- key；
- label；
- value type；
- description；
- reason；
- proposed by；
- status；
- created time。

這形成：

$$
\text{Observe}
\rightarrow
\text{Propose}
\rightarrow
\text{Review}
\rightarrow
\text{Register}.
$$

未來可增加：

- 語義去重；
- 同義欄位合併；
- namespace；
- proposal score；
- information gain；
- cost estimate；
- automated acceptance policy。

因此「無界展開」不是無治理展開。

---

# 9. Sparse Cell 與真正的空白

本系統最重要的實作語義之一是：

> 空白不是一個特殊字串，而是沒有 row。

令：

$$
B(e,f)=
\begin{cases}
1,& (e,f)\notin C,\\
0,& (e,f)\in C.
\end{cases}
$$

若使用者把 cell 刪除，系統直接刪除 `(entity_id, field_id)` 的 cell row。

因此：

```text
blank
```

與：

```json
null
```

在概念上不同。

同樣地：

```json
false
```

和：

```json
0
```

也不會因為語言中的 falsy 規則被誤當成空白。

這對 AI 特別重要，因為模型很容易把：

- 未觀測；
- 不適用；
- 不知道；
- 明確為否；
- 明確為零；

混成一個「空」概念。

SEDB-UF 要求它們在資料層可區分。

---

# 10. Task View：不是再建一張表，而是建立投影

若全域欄位集合有 10,000 個欄位，UI 不應真的產生 10,000 個 DOM column。

對任務 $Q$，定義：

$$
\Pi_Q(E,F,C)
=
(E,F_Q,C_Q),
$$

其中：

$$
F_Q\subseteq F.
$$

Task View 保存：

```text
view_id
name
query_text
ordered field set
```

並從原 sparse database 動態投影。

因此：

$$
\boxed{
\text{Task View}
\neq
\text{Copied Table}
}
$$

這帶來三個好處：

1. 不複製資料；
2. 不產生 view-specific data drift；
3. 同一 entity 的不同任務可以使用完全不同欄位子集。

例如全域資料庫可能有 10,000 個欄位，但「研究者超高產掃描」只需要 34 個欄位；「論文品質審計」可能只需要 21 個；「來源驗證」又使用另一組 18 個。

---

# 11. Matrix Window：讓萬欄資料仍可操作

即使 Task View 本身包含大量欄位，瀏覽器也不應一次渲染全部。

因此 v0.1 的 matrix API 支援：

```text
field_offset
field_limit
entity_offset
entity_limit
```

即：

$$
W=
F_Q[k:k+n].
$$

UI 只取得目前窗口 $W$。

這使「10,000 個邏輯欄位」不等於「10,000 個同時渲染欄位」。

更完整版本可以進一步加入雙向 virtualization，但 v0.1 已建立必要的 field-window 邊界。

---

# 12. 搜尋與分類

v0.1 提供對：

- field；
- entity；
- cell text；

的基本搜尋。

目前搜尋主要使用 SQLite 與字串匹配，目標是先驗證資料模型與工作流，而不是宣稱已完成大規模全文或語義搜尋。

後續版本可以加入：

$$
\text{Lexical Search}
+
\text{Structured Filters}
+
\text{Graph Relations}
+
\text{Optional Embeddings}.
$$

其中 embedding 應是可選層，不應成為動態欄位系統成立的必要條件。

---

# 13. CSV 與 JSONL 交換

SEDB-UF 不要求外部世界也採用相同資料模型，因此 v0.1 提供 CSV 與 JSONL 匯入／匯出。

## 13.1 JSONL

JSONL 適合保存 sparse entity：

```json
{
  "id": "paper-001",
  "label": "Paper 001",
  "kind": "paper",
  "values": {
    "verified": false,
    "year": 2026
  }
}
```

沒有出現在 `values` 的 field 就是 blank。

## 13.2 CSV

CSV 必須面對固定 header，因此 SEDB-UF 將它視為外部投影格式，而不是 canonical storage。

CSV 空字串在匯入時可解釋為 absence，不強制建立 cell。

存在的值則使用 JSON 語義編碼，使：

- integer；
- float；
- boolean；
- array；
- object；
- explicit JSON `null`；

可以和真正空白區分。

---

# 14. 本地 API 與 Browser UI

v0.1 提供 dependency-free 的本地 HTTP JSON API 與 vanilla HTML/JavaScript UI。

主要 API：

```text
GET    /api/health
GET    /api/stats
GET    /api/fields
POST   /api/fields
POST   /api/fields/{id}/transition
GET    /api/fields/{id}/evaluations
GET    /api/proposals
POST   /api/proposals
GET    /api/entities
POST   /api/entities
GET    /api/entities/{id}
PUT    /api/entities/{id}/cells/{field_key}
DELETE /api/entities/{id}/cells/{field_key}
GET    /api/search?q=...
GET    /api/views
POST   /api/views
GET    /api/views/{id}
```

其中刪除 cell 使用 `DELETE`，而不是把某個假的空值寫回 cell。

UI 的目標不是取代完整資料分析平台，而是驗證：

1. 動態欄位可以被建立；
2. entity 可以被建立；
3. sparse cell 可以被讀寫；
4. 欄位可收斂與重新啟用；
5. Task View 可以被建立；
6. 大型欄位集合可以透過窗口操作。

---

# 15. AI 原生欄位展開演算法

一個基本 AI 欄位展開 LOOP 可以寫成：

$$
\boxed{
\text{Observe}
\rightarrow
\text{Propose}
\rightarrow
\text{Deduplicate}
\rightarrow
\text{Register}
\rightarrow
\text{Selective Fill}
\rightarrow
\text{Evaluate}
\rightarrow
\text{Expand or Converge}
\rightarrow
\text{Repeat}
}
$$

更形式化地，令目前欄位集合為 $F_t$，AI 在時間 $t$ 根據資料 $\mathcal D_t$ 與任務 $Q_t$ 提出候選：

$$
P_t=
\mathcal A(\mathcal D_t,Q_t,F_t).
$$

經治理函數 $G$ 後：

$$
A_t=G(P_t,F_t),
$$

其中 $A_t$ 為真正接受的新欄位。

下一狀態：

$$
F_{t+1}
=
F_t
\cup
A_t
-
D_t,
$$

其中 $D_t$ 不表示物理刪除，而是可代表從 active support 移入 converged 或 deprecated 的集合。

對每個新增 field $f$，回填不是全域操作，而是選擇相關 entity 子集：

$$
E_f^\star
\subseteq
E.
$$

只有：

$$
e\in E_f^\star
$$

時才需要考慮 evidence retrieval 或 cell fill。

因此新增欄位的預設成本不是：

$$
O(|E|),
$$

而可以接近：

$$
O(|E_f^\star|).
$$

這是 AI 原生無界欄位設計的主要工程價值之一。

---

# 16. 欄位收斂的原因考核

若允許無限增加欄位卻沒有收斂機制，系統會產生 schema entropy。

因此每個欄位可以建立評估向量：

$$
\Gamma_f
=
(
u_f,
c_f,
r_f,
d_f,
m_f,
q_f
),
$$

例如：

- $u_f$：近期使用率；
- $c_f$：填值成本；
- $r_f$：對任務的資訊增益；
- $d_f$：與其他欄位的重複度；
- $m_f$：缺失率；
- $q_f$：目前任務相關性。

v0.1 尚未自動計算這些指標，但其 `field_evaluations` 已提供 `reason`、`evidence` 與 `metrics` 儲存位置。

一個未來收斂判斷可以寫成：

$$
\operatorname{Converge}(f)
=
1
$$

當且僅當治理策略認為：

$$
\operatorname{Benefit}(f)
<
\operatorname{Cost}(f)
$$

並且保留人類或 Agent 可審核的理由。

重要的是，這不是不可逆 schema deletion。

---

# 17. 複雜度與擴張性

傳統完全實體化寬表可抽象理解為邏輯矩陣：

$$
M\in\prod_{e\in E,f\in F}(D_f\cup\{\varnothing\}).
$$

若大量位置為空，其語義資訊量並不等於矩陣大小。

SEDB-UF 的核心儲存量近似為：

$$
O(|E|+|F|+|C|+|H|),
$$

其中 $H$ 為欄位事件、評估與治理歷史。

若：

$$
|C|
\ll
|E||F|,
$$

則 sparse model 具有明顯優勢。

但需要明確指出：SQLite index、JSON encoding、查詢 join 與大量 registry row 仍然有成本；因此此式是架構級近似，而不是所有工作負載下的實測複雜度保證。

---

# 18. v0.1 實際 10,000 欄驗證

v0.1 的 demo database 實際建立：

$$
|F|=10{,}000
$$

個 active field，

$$
|E|=3
$$

個 entity，

$$
|C|=9
$$

個 cell。

邏輯容量為：

$$
L
=
|E||F|
=
30{,}000.
$$

資料密度：

$$
\rho
=
\frac{9}{30{,}000}
=
0.0003
=
0.03\%.
$$

也就是說，全域 registry 中 10,000 個欄位全部存在，但三筆資料只真正保存九個 entity-field 值。

該 demo 同時存在一個 Task View。

2026-08-20 的 release validation：

```text
31 passed
Python compileall: pass
fields: 10000
entities: 3
cells: 9
views: 1
logical_capacity: 30000
density: 0.0003
```

這個結果證明的是：

> 在目前 v0.1 實作與測試規模下，註冊 10,000 個邏輯欄位不需要物化 30,000 個 cell。

它不證明 100,000、1,000,000 或無限欄位在所有工作負載下仍具有相同效能。

---

# 19. 與其他資料模型的關係

## 19.1 與傳統 Wide Table

傳統 wide table：

```text
entity | field_1 | field_2 | ... | field_10000
```

優點是固定查詢簡單、型別與索引成熟。

SEDB-UF：

```text
field registry
+
sparse cells
+
field lifecycle
+
task projection
```

優勢是 schema 可持續擴張，且空白不需要物化。

因此兩者不是絕對替代關係。

## 19.2 與 EAV

SEDB-UF 的 `cells` 在形態上接近 Entity-Attribute-Value，但本系統並不只提出 EAV row。

增加的核心包括：

- field registry；
- lifecycle；
- field event ledger；
- convergence evaluation；
- proposal queue；
- Task View；
- blank-by-absence 規則；
- AI governance semantics。

因此可以理解為：

$$
\text{SEDB-UF}
=
\text{Sparse Attribute Storage}
+
\text{Field Governance}
+
\text{AI-Native Projection}.
$$

## 19.3 與 JSON Document Store

JSON document 很適合每個 entity 擁有不同欄位，但欄位若沒有全域身份與治理層，長期可能出現：

- 同義 key；
- 拼字分裂；
- 欄位定義漂移；
- 無法追蹤欄位何時加入；
- schema inference 不一致。

SEDB-UF 將 field 從 document 內部 key 提升為全域 registry entity。

## 19.4 與 Knowledge Graph

Knowledge graph 強於關係、實體與路徑。

SEDB-UF 主要處理 attribute space 與 field governance。

未來可以把：

$$
\text{Field}
$$

本身也轉成 graph node，建立：

```text
derived_from
merged_into
split_from
equivalent_to
conflicts_with
supersedes
```

等欄位關係。

## 19.5 與 Vector Database

Vector database 解決相似性檢索，不負責欄位生命週期與 sparse structural truth。

SEDB-UF 可以使用 embedding 做：

- proposal deduplication；
- semantic field search；
- entity retrieval；

但 embedding 不應取代 canonical field identity。

---

# 20. 典型使用案例

## 20.1 超高產研究者資料庫

初始可能只有：

- author name；
- publication count；
- year range。

研究後可以逐步增加：

- first-author ratio；
- median team size；
- solo ratio；
- retraction count；
- AI-use evidence；
- repository distribution；
- publication type composition；
- duplicate-version suspicion；
- institutional network size；
- source reliability。

不是先要求世界上所有作者填完全部欄位，而是：

$$
\text{Need}
\rightarrow
\text{Add Field}
\rightarrow
\text{Selective Fill}.
$$

## 20.2 論文與理論資料庫

研究系列可以隨時間增加：

- theorem status；
- proof dependency；
- computational validation；
- falsification condition；
- external citation；
- internal dependency；
- concept lineage；
- implementation status。

## 20.3 AI 工具與產品策展

不同 Agent 可以持續發現：

- price model；
- API availability；
- local deployment；
- privacy；
- model provider；
- license；
- latency；
- benchmark；
- supported platform；
- last verified time。

## 20.4 長期 Agent Memory

Agent 不需要一開始知道未來所有 memory attribute。新任務出現時可以提出新 field，但只對相關 memory entity 補充。

---

# 21. 失敗模式與治理風險

無界欄位架構的主要風險不是「欄位太少」，而是「欄位無限制碎裂」。

## 21.1 同義欄位爆炸

例如：

```text
author_country
country_of_author
nationality
researcher_country
```

可能描述部分重疊概念。

v0.1 尚未提供自動 semantic deduplication。

## 21.2 欄位定義漂移

同一 key 的 meaning 可能被不同 Agent 不知不覺改寫。

後續需要 field version 或 immutable semantic contract。

## 21.3 AI 自動填值幻覺

「欄位存在」不能成為模型編造值的壓力來源。

因此：

$$
\boxed{
\text{Blank}
>
\text{Unsupported Guess}
}
$$

對沒有證據的欄位，保持 blank 應是合法且常見的結果。

## 21.4 收斂指標被濫用

低使用率不一定代表欄位沒有價值；某些低頻欄位可能只在高風險案例中重要。

因此 convergence 必須允許：

- evidence；
- metrics；
- evaluator；
- reversibility；
- reactivation。

## 21.5 Registry 本身成為瓶頸

當欄位數進入更高量級後，field search、namespace、索引、cache 與 schema governance 都可能需要新的資料結構。

這是後續實測問題，而不是由「sparse」二字自動解決。

---

# 22. 安全、權限與多使用者限制

v0.1 是 local-first research MVP，目前尚未實作：

- authentication；
- authorization；
- row-level security；
- field-level permission；
- multi-user conflict resolution；
- remote synchronization；
- encrypted-at-rest policy；
- audit identity verification。

因此 v0.1 不應直接作為含敏感資料的公開多使用者服務。

後續若接入原始 SEDB 與 ODSTT，可將權限、來源、版本與合法操作檢查提升為正式 guard layer。

---

# 23. v0.1 已完成能力

截至 2026-08-20，本地 v0.1 已實作：

- SQLite schema initialization；
- dynamic field registry；
- bulk field registration；
- 10,000-field demo；
- sparse JSON cell；
- blank-by-absence；
- entity CRUD 的核心建立與讀取操作；
- cell set/get/delete；
- field lifecycle；
- mandatory convergence reason；
- reactivation reason；
- field event history；
- field evaluation history；
- proposal queue；
- Task View；
- bounded field window；
- field/entity/cell search；
- storage statistics；
- JSONL import/export；
- CSV import/export；
- local HTTP API；
- browser UI；
- CLI；
- automated test suite。

---

# 24. v0.1 刻意延後的能力

目前未完成：

- PostgreSQL backend；
- DuckDB backend；
- distributed execution；
- production concurrency model；
- authentication；
- authorization；
- remote synchronization；
- vector search；
- direct LLM provider integration；
- semantic proposal deduplication；
- automatic field information-gain scoring；
- field lineage graph；
- full cell version history；
- multi-Agent merge policy；
- public software license selection。

這些項目不應被 README 或白皮書描述為已存在能力。

---

# 25. 下一階段路線

## Phase 0.2：欄位治理強化

增加：

- proposal accept/reject；
- duplicate detection；
- namespace；
- alias；
- merge/split lineage；
- field definition versioning。

## Phase 0.3：大規模瀏覽與查詢

增加：

-雙向 virtualization；
- compound filters；
- indexed structured search；
- saved query；
- task-specific support recommendation。

## Phase 0.4：AI Field Agent

建立：

$$
\text{Data}
\rightarrow
\text{Field Proposal}
\rightarrow
\text{Evidence}
\rightarrow
\text{Human/Policy Review}
\rightarrow
\text{Registry}.
$$

AI 可以提出新欄位，但不能無理由直接污染 canonical registry。

## Phase 0.5：自動收斂與重新啟用

定義欄位效用函數：

$$
U_f(Q,t)
=
\alpha I_f
-
\beta C_f
-
\gamma D_f
+
\delta R_f,
$$

其中可包含資訊增益、填值成本、重複度與任務相關性。

## Phase 1.0：SEDB 完整整合

把 field layer 與：

- claim ledger；
- semantic evolution；
- provenance；
- epistemic state；
- event sourcing；
- SEQL；

正式整合。

此時 SEDB 不只回答：

> 這筆資料目前有哪些值？

還能回答：

> 為什麼有這個欄位？  
> 誰提出它？  
> 它何時被收斂？  
> 哪個任務又重新啟用了它？  
> 哪些值來自觀測，哪些來自推論？  
> 哪個版本的欄位定義產生了目前結果？

---

# 26. 可否證條件

SEDB-UF 的工程價值應被弱化，若實驗顯示：

1. 固定 schema 加普通 migration 已能以更低成本處理相同 AI 工作流；
2. sparse cell join 成本在實際資料規模上遠大於節省的 schema 成本；
3. 欄位 registry 無法控制同義欄位爆炸；
4. Task View 無法有效降低大型欄位集合的操作負擔；
5. 收斂理由與 lifecycle history 對實際治理沒有可測量價值；
6. AI proposal layer 只增加噪音而不能提高資料覆蓋或分類能力；
7. 高欄位數使搜尋、索引與理解成本高到不可治理；
8. blank-by-absence 在實際交換流程中無法可靠保留；
9. 大多數目標任務其實具有穩定 schema，動態欄位帶來的複雜度大於收益。

SEDB-UF 因此應被視為可實驗、可比較的工程架構，而不是預設正確的萬用資料庫哲學。

---

# 27. 核心不變量

v0.1 建議把下列條件視為系統不變量。

## 不變量一：欄位存在不推出 cell 存在

$$
f\in F
\not\Rightarrow
(e,f)\in C.
$$

## 不變量二：空白不等於 false

$$
\varnothing
\neq
\texttt{false}.
$$

## 不變量三：空白不等於零

$$
\varnothing
\neq
0.
$$

## 不變量四：Task View 不複製 canonical cell

$$
C_Q
\subseteq
C.
$$

## 不變量五：收斂不得無理由

$$
\operatorname{Converge}(f)
\Rightarrow
R_f\neq\varnothing.
$$

## 不變量六：重新啟用可追蹤

$$
\text{Converged}
\rightarrow
\text{Active}
$$

必須留下 evaluation。

## 不變量七：未知不得被迫填值

若證據不足：

$$
\operatorname{Evidence}(e,f)
=
\varnothing,
$$

合法結果可以是：

$$
V(e,f)=\varnothing.
$$

---

# 28. 結論

AI 時代真正需要重新思考的，不只是「AI 如何填表」，而是：

> 誰決定表格有什麼欄位？

在傳統資料系統中，schema 通常由人類工程師提前決定；在 AI 原生系統中，分類維度本身可能由研究、資料與 Agent 在運行過程中持續發現。

若每個新欄位都要求對全部歷史資料回填，動態知識系統會被固定 schema 綁死。若完全放棄 schema，只依賴任意 JSON key，又會失去欄位身份、治理、收斂、版本與可追蹤性。

SEDB-UF 的折衷方案是：

$$
\boxed{
\text{Open Field Registry}
+
\text{Sparse Cells}
+
\text{Lifecycle Governance}
+
\text{Task Projection}
}
$$

它允許欄位空間持續展開，同時讓大多數 entity 保持空白；允許 AI 提出新維度，但把 proposal 與 canonical registry 分離；允許欄位收斂，但要求留下理由；允許全域存在上萬個欄位，但每個任務只啟用局部支撐。

因此，「真正的 AI 原生填表」不是要求 AI 把一萬格全部填完，而是讓 AI 知道：

> 哪些欄位值得存在，哪些紀錄真的需要填，哪些地方應該保持空白，以及為什麼。

SEDB-UF v0.1 已完成第一個可執行錨點。下一階段的核心問題不再是「能不能建立一萬欄」，而是：

$$
\boxed{
\text{如何讓欄位的生成、選擇、收斂與重新啟用本身成為可治理的智能過程。}
}
$$

---

# 附錄 A：v0.1 SQLite 核心 Schema

```sql
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE fields (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    value_type TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE cells (
    entity_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(entity_id, field_id)
);

CREATE TABLE field_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    evaluator TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE field_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    evaluator TEXT NOT NULL,
    reversible INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE field_proposals (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    value_type TEXT NOT NULL,
    description TEXT NOT NULL,
    reason TEXT NOT NULL,
    proposed_by TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE task_views (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    query_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE task_view_fields (
    view_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    PRIMARY KEY(view_id, field_id),
    UNIQUE(view_id, ordinal)
);
```

---

# 附錄 B：最小 Python 使用範例

```python
from sedb.db import Database
from sedb.fields import FieldService
from sedb.entities import EntityService

db = Database("research.sqlite")
fields = FieldService(db)
entities = EntityService(db)

fields.create_field(
    key="verified",
    label="Verified",
    value_type="boolean",
)

entity = entities.create_entity(
    label="Paper 001",
    kind="paper",
)

entities.set_cell(
    entity["id"],
    "verified",
    False,
    source="manual",
)
```

註冊其他 10,000 個欄位不會自動替 `Paper 001` 生成 10,000 個 cell。

---

# 附錄 C：v0.1 驗證命令

```bash
PYTHONPATH=src pytest -q
python -m compileall -q src examples
```

驗證結果：

```text
31 passed in 4.02s
```

10,000 欄 demo：

```json
{
  "fields": 10000,
  "entities": 3,
  "cells": 9,
  "views": 1,
  "logical_capacity": 30000,
  "density": 0.0003
}
```

---

# 附錄 D：前置與相關內部文件

本白皮書與以下既有 SEDB / 類型治理文件保持概念連續性：

1. 《AI 原生語義演化資料庫：從事件溯源、主張帳本到動態語義圖查詢語言的系統架構》；
2. 《開放維度語義類型理論：面向異質資料 Agent 與跨尺度計算》；
3. 《動態多維空間狀態類型論：第一輪實戰擬合驗證報告》；
4. 《通用動態策展目錄：由分類導航到 Agent 自動治理》。

SEDB-UF v0.1 的定位是把其中「開放維度」、「動態有效支撐」、「事件治理」與「Agent 自動策展」思想壓縮為一個可直接執行的資料層。

---

# 版本紀錄

## v0.1 — 2026-08-20

- 建立 SEDB-UF 正式技術白皮書；
- 對應 SEDB Local v0.1 executable checkpoint；
- 明確定義 `Add Field != Fill Field`；
- 定義 blank-by-absence；
- 定義 sparse cell model；
- 定義 field lifecycle 與 convergence reason；
- 定義 proposal queue；
- 定義 Task View；
- 記錄 10,000 欄實證與 31 項測試；
- 明確限制「無界」為架構性開放集合，而非已實證數學無限規模。
