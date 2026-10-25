# 审计报告输出模板（HTML 结构化版本）

> **本模板是审计报告的唯一规范格式（v2.2.0 起）。** 三个强制要求不变：
> 1. **每条主张都必须挂 `[E##]` 证据编号**，编号在「证据清单」中有完整出处（含链接与逐字摘录）——格式见 `citation-format.md`。
> 2. **分数的每一分都必须可推导**：给出统计口径的分子/分母构成、对应主张编号、五维公式、加权贡献、扣分清单。
> 3. **公式来源与自评声明必须写明**——分数依据 `scoring-spec.md` 的公开公式，属专家自评。

报告从 v2.2.0 起**默认输出为单文件 HTML**（内联 CSS、无外部依赖、双击即开）；结构、字段与纯文本版逐一对齐，只是用 HTML 把层级、色彩、可折叠、锚点跳转做清晰。**环境无法渲染/保存 HTML 时回退纯文本等价结构（见第九节）。**

---

## 〇、为什么是 HTML（设计意图）

- **单文件**：一个 `.html`，`<style>` 内联，不引外部字体/JS/图片，离线可开。
- **色彩编码结论**：支持绿 / 反驳红 / 部分支持琥珀 / 证据不足蓝 / 观点或预测灰，一眼定位风险。
- **锚点跳转**：主张卡里的 `[E02]` 可点，直接跳到证据清单的对应条目；证据清单反向链回主张。
- **可折叠细节**：证据清单、长主张卡用 `<details>` 折叠，首屏只看结论，展开看出处——比长纯文本更易扫读。
- **评分可点开**：五维明细表 + 扣分清单表内嵌，每一分都能追到主张/证据编号。

> **降级铁律**：若运行环境只能输出对话文本（无保存 HTML 能力），则按第九节的纯文本等价结构输出，字段要求完全一致，仅失去色彩/折叠/锚点。不得因"做不了 HTML"就省略任何必填字段。

---

## 一、HTML 设计系统（必须沿用，保证跨报告一致）

复制以下 `<style>` 到每个审计报告 `<head>`。配色与类名固定，便于用户形成肌肉记忆。

```html
<style>
  :root{
    --bg:#ffffff; --ink:#1f2328; --muted:#57606a; --line:#d8dee4;
    --sup:#1a7f37; --sup-bg:#e6f4ea;
    --ref:#cf222e; --ref-bg:#ffebe9;
    --par:#9a6700; --par-bg:#fff8e1;
    --ins:#0969da; --ins-bg:#ddf4ff;
    --opi:#57606a; --opi-bg:#f0f1f3;
    --s:#8250df; --a:#0969da; --oth:#57606a; --none:#cf222e;
    --shadow:0 1px 3px rgba(27,31,36,.08);
  }
  *{box-sizing:border-box}
  body{font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
       color:var(--ink);max-width:980px;margin:24px auto;padding:0 20px;line-height:1.6;
       background:var(--bg);font-size:15px}
  h1{font-size:24px;border-bottom:3px solid var(--ink);padding-bottom:8px}
  h2{font-size:19px;margin-top:34px;border-left:5px solid var(--ink);padding-left:10px}
  h3{font-size:16px;margin-top:22px}
  .meta{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 22px;
        background:var(--opi-bg);border:1px solid var(--line);border-radius:8px;
        padding:14px 18px;margin:14px 0}
  .meta div{font-size:13.5px}
  .meta b{color:var(--muted);font-weight:600;margin-right:6px}
  table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}
  th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
  th{background:#f6f8fa;font-weight:600}
  /* 结论色彩编码 */
  .v{display:inline-block;font-weight:700;padding:1px 9px;border-radius:999px;font-size:13px;white-space:nowrap}
  .v-sup{color:var(--sup);background:var(--sup-bg)}
  .v-ref{color:var(--ref);background:var(--ref-bg)}
  .v-par{color:var(--par);background:var(--par-bg)}
  .v-ins{color:var(--ins);background:var(--ins-bg)}
  .v-opi{color:var(--opi);background:var(--opi-bg)}
  /* 证据等级色 */
  .g{font-weight:700;padding:0 6px;border-radius:4px;font-size:12.5px}
  .g-s{color:var(--s);background:#f3effd}
  .g-a{color:var(--a);background:var(--ins-bg)}
  .g-oth{color:var(--oth);background:var(--opi-bg)}
  .g-none{color:var(--none);background:var(--ref-bg)}
  /* 证据锚点 */
  a.evid{color:var(--ins);text-decoration:none;font-weight:600;border-bottom:1px dotted var(--ins)}
  a.evid:hover{background:var(--ins-bg)}
  /* 主张卡 */
  .claim{border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:12px 0;box-shadow:var(--shadow)}
  .claim .hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
  .claim .num{font-weight:800;font-size:15px}
  .claim .risk{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 6px}
  .kv{display:grid;grid-template-columns:120px 1fr;gap:2px 12px;font-size:13.5px;margin-top:6px}
  .kv dt{color:var(--muted);font-weight:600}
  .kv dd{margin:0}
  /* 折叠 */
  details{border:1px solid var(--line);border-radius:8px;padding:8px 14px;margin:8px 0}
  details>summary{cursor:pointer;font-weight:600;color:var(--ins)}
  .warn{border-left:4px solid var(--ref);background:var(--ref-bg);padding:8px 14px;margin:12px 0;border-radius:0 6px 6px 0}
  .note{border-left:4px solid var(--par);background:var(--par-bg);padding:8px 14px;margin:12px 0;border-radius:0 6px 6px 0}
  .score-hero{font-size:46px;font-weight:800;text-align:center;padding:10px 0}
  code{background:#f6f8fa;padding:1px 5px;border-radius:4px;font-size:12.5px}
  .foot{color:var(--muted);font-size:12.5px;margin-top:30px;border-top:1px solid var(--line);padding-top:10px}
  /* 打印 / 存 PDF：强制展开全部折叠内容，避免证据清单被折叠隐藏而丢失 */
  @media print{
    body{max-width:none;margin:0;padding:14mm;font-size:11pt}
    details:not([open])>*:not(summary){display:block !important}  /* 覆盖 UA 默认隐藏，展开折叠内容 */
    details{border-color:#bbb;break-inside:auto}
    details>summary{color:var(--ink);list-style:none}
    h2{break-after:avoid-page;break-inside:avoid}
    .claim,.meta{break-inside:avoid-page;box-shadow:none}
    a.evid{border-bottom:none;color:var(--ink)}
    .score-hero{font-size:30pt}
  }
</style>
```

**结论色彩编码（全报告统一）**

| 结论 | class | 语义 |
|---|---|---|
| 支持 SUPPORTED | `v v-sup` | 证据直接支持，容差内 |
| 反驳 REFUTED | `v v-ref` | 冲突事实/错值/错期/错单位/反方向 |
| 部分支持 PARTIALLY_SUPPORTED | `v v-par` | 部分成立或关键部分缺失 |
| 证据不足 INSUFFICIENT_EVIDENCE | `v v-ins` | 既不能证也不能反 |
| 观点或预测 OPINION_OR_FORECAST | `v v-opi` | 不判真假 |
| 无法判断 UNABLE_TO_DETERMINE | `v v-opi` | 材料缺失/不可判定 |

**证据等级色**：S `g g-s` / A `g g-a` / 其他 `g g-oth` / 未注明 `g g-none`。

---

## 二、固定结构（与纯文本版字段一一对应）

**顺序：报告基本信息 → 审计结论 → 报告健康度 → 证据清单 → 主张核验卡 → 需用户自行核验清单 → 对抗性抽查 → 独立复核 → 审计轨迹 → 附录。**

> **三条硬规则**
> 1. **标题从简、不加序号前缀**：首段就叫「报告基本信息」，健康度段就叫「报告健康度」——**不写**"零、"、"一、"、也不写"（FinProof Score，完整推导）"这类括号。
> 2. **问题前置**：把「**错误**（反驳）」与「**找不到支撑材料**（证据不足）」集中放进紧接基本信息的「**审计结论**」，读者第一眼看到的就是问题。
> 3. **只报问题项、正分不展开**：**核验通过（支持）的主张不逐条写卡**，仅在审计结论末尾给一句计数（如"其余 N 条经核验支持，不展开"）；观点/预测类不判真假，也不进审计结论——**唯一例外是「预测事实化」**（确定性措辞的预测、依据未披露，见 `SKILL.md` §一 G 类输出纪律）：此类 G 类主张**必须进审计结论问题项与主张卡**，结论仍标"观点或预测"，问题写"预测事实化：确定性表述但依据未披露"。**正文不写客套话、不复述公式全文**（公式与标准在附录）。

- **报告基本信息**：报告名 · 页数/主张数 · 核验模式 · **运行档位（完整档 / 快速档；快速档须列省略项）** · 核验时间 · 证据来源统计 · 计算方法（含降级声明）· 联网检索次数 · **引擎复算覆盖 N_e/N_v（判定溯源）** · **主审模型 · 独立复核模型（方式）**。紧凑表格，**标题不带前缀**。**复现性声明随表**：数值复算由确定性引擎执行、可复现；主张拆解与语义判定由模型产出，两次运行可能不同，本报告依据当次运行快照。
- **审计结论**：★ 问题前置——**只列不确定与错误项**，按严重度排序（**反驳 > 证据不足 > 部分支持 > 无法判断 > 预测事实化**）。每条一行：`#编号 · 报告原句（可截断）· 结论 · 一句话问题 · 证据引用 [E##] · 建议`。末尾给支持类计数。预测事实化条目的结论仍为「观点或预测」（G 类不判真假），但须进本段并在问题列写明"预测事实化：确定性表述但依据未披露"；G 类其余条目在结论行标注「依据已披露 / 依据未披露」。
- **报告健康度**：分数 + 统计口径 + 五维明细 + 扣分清单 + 档位（含问题项计数）+ **审计质量分 AQS 并列行（v2.7.0：五维机械指标 C/E/V/R/L + 明细 + 独立性警示）** + 固定文案。**标题就写「报告健康度」**，不加"（FinProof Score，完整推导）"；公式与符号定义见附录，正文不重复。**证据等级分布处，S+A 级占比 <50% 或来源权威性 <60 时必须加「⚠ 弱来源依赖」警示行**。
- **证据清单**：**只收录被报告主张（问题项）引用的 `[E##]`**，每条 `<details>` 折叠九字段（编号·等级·类型·来源名称·**链接（含复验状态）**·抓取时间·定位·逐字摘录·关联主张）。
- **主张核验卡**：**只出问题项**（反驳/证据不足/部分支持/无法判断/**预测事实化**）的卡片——编号·报告原句·类型·风险等级·结论·证据引用·复算（**含判定来源标记〔引擎复算〕/〔心算估算〕**）·口径对照·单位确认·建议；预测事实化卡另含「依据披露」字段（依据已披露/未披露）。**支持类不建卡。**
- **需用户自行核验清单**：`[Gx]` + 主张 + 证据 + 原因 + 用户动作 + 已尝试手段 +「未闭环 ≠ 通过」；按影响核心结论程度排序。
- **对抗性抽查**：逐项列已查形态与结果（无可疑项写"未发现"）。
- **独立复核**：复核方式（**异源模型名 / 同源盲复核 / 自检复核〔机械层〕+ 引擎重跑·摘录复读计数 / 未复核+原因**，可组合如"异源 + 自检层"）· 复核范围（问题项 x/x + 支持项抽样 x + 评分复算）· 一致/分歧计数 · 分歧明细（协议见 `independent-review.md`）。
- **审计轨迹**：**仅回放问题项**的证据 → 计算（**引擎命令与输出，判定溯源**） → 判定。
- **附录 · 评分与分类标准**：必附，置于报告最末——五维定义与公式 / 统计口径符号 / 证据等级标准 / 分数档位与附加要求 / 主张分类 A–G / 六类结论与触发条件 / 缺口分类 G1–G4 / 复算容差表。
  > **要点：附录是本报告"自解释、可复核"的落点**——读者不必翻阅外部文档，就能在报告内查到"这么多个维度、每个怎么算、公式是什么、评分与分类标准是什么"。**分数是主观产出没关系，但依据必须是公开可查的。**

---

## 三、可核对性硬规则（HTML 版）

- **锚点跳转**：主张卡中写 `<a class="evid" href="#E01">[E01]</a>`；证据清单每条 `<details>` 设 `id="E01"`，并在 `summary` 写 `编号 [E01]`。点主张里的编号即跳到证据；证据里反向链回 `#c2` 等主张锚。
- **⚠️ HTML 转义**：必做，否则破版——凡把**报告原文**塞进 HTML 的地方——「报告原句」「逐字摘录」「来源名称」「修改建议」——其中的 `&` `<` `>` **必须转义**为 `&amp;` `&lt;` `&gt;`。财务文本高频踩雷：`毛利率<10%`、`营收>100亿`、`A&B`、`“<0”`；不转义会破坏结构，严重时报告里的文本可注入任意标记（**报告是外部不可信输入**）。转义须在**放进去之前**做，不要事后补。
- **唯一 id**：每个 `[E##]` 全报告只出现一个 `<details id="E##">`；每条主张一个 `id="cN"`。同一证据支撑多条主张时**复用编号、不复制 `<details>`**，避免锚点指向第一个而其余失效。
- **链接字段与复验状态**：联网证据 `<a href="https://..." target="_blank" rel="noopener noreferrer">完整 URL</a>`（`rel` 必加），链接后**必须缀复验状态**——`〔复验：可达 / 重定向 / 不可达(状态码) / 未复验(原因) · YYYY-MM-DD〕`（定稿前逐条访问，见 `SKILL.md` §9.1；不可达→等级降一档并保留原摘录）；本地文件写「本地文件（无 URL）— 用户于 YYYY-MM-DD 提供」；无链接显式写原因（未取得可访问链接/付费墙未检索），**绝不编造 URL**。
- **逐字摘录**：用 `「」` 包裹，原样，不得转述、不得改单位/正负号。
- **冲突证据全列**：同一主张的正反证据都放，用 `.note` 写明采信理由（高等级优先）。
- **降级声明**：无 shell 时复算标 `〔心算估算，未经引擎复算〕`；无 API Key 标「Mock 模式，非真实模型输出」。

---

## 四、评分可推导（HTML 版）

健康度一节用两张表呈现（不得只给总分）：

1. **五维明细表** `<table>`：列 = 维度 / 公式 / 原始观测 / 得分 / 加权贡献；末行「合计 → 取整」。
2. **扣分清单表** `<table>`：列 = 序号 / 主张 / 证据 / 错误类型 / 扣分依据 / 影响维度。
3. 档位用 `.score-hero` 大字展示 `76 / 100`，下接「良（75–89）」与附加要求。
4. 公式来源 + 固定警示 + 自评声明放在 `.note` / `.warn` 块，逐字附上（见下「固定文案」）。

**固定文案（每次逐字附）**：

```
【公式来源】FinProof Score 按公开公式计算：
  Score = 0.25×可判定率 + 0.25×数字准确性 + 0.20×引用一致性
        + 0.15×来源权威性 + 0.15×时间与口径一致性
  证据等级分值：S 级 100 / A 级 70 / 其他 40 / 未注明 0
  取整规则：加权求和使用未取整的各维分值，最后四舍五入到整数；
  展示时各维保留一位小数、加权贡献保留两位小数
  完整规格（含惩罚系数、档位、风险分、算例、边界）：scoring-spec.md

【固定警示】FinProof Score 反映证据链质量与引用规范，不代表结论正确性。
  引用规范的报告仍可能存在数字或口径错误；请结合「反驳/部分支持」条数与
  「需用户自行核验清单」一并判断。
  **不同报告的 Score 不可横向直接比较**——准确性与可判定率的分子/分母都随该报告
  自身的主张总数变化（40 条里错 1 条的扣分远小于 4 条里错 1 条）。

【口径披露】①「可判定率」（历史名「证据覆盖率」，公式与全部历史分数不变）衡量的是
  "能否判定"——闭环含支持/反驳/部分支持/无法判断，REFUTED 也计入闭环，故错误较多
  但都能被判定的报告本维可为 100；它不衡量"证据是否充分、来源是否可靠"。
  ② 「来源权威性」仅占 15%，因此**数字自洽但来源等级普遍偏低的报告仍可能拿到"优"档**
  ——请据此解读档次。③ 数值复算由确定性引擎执行（引擎复算覆盖 N_e/N_v 见基本信息），
  可复现；主张拆解与语义判定由模型产出，两次运行可能不同，本报告依据当次运行快照。

【自评声明】本分为专家自评，非第三方认证。上述分子/分母与公式均已列出，可自行复算；
  如复算结果与本文不一致，即为本专家实现有误，请指出。判定经独立复核（方式见
  「独立复核」段），复核分歧已如实披露，但不改变自评性质。
```

---

## 五、完整 HTML 模板（含 76 分完整算例，可直接打开）

> 以下即**完整可打开的审计报告骨架**，已填入 9 主张 → Score 76 的算例作为示范。
> 实际出报告时，把每处 `{{…}}` 占位符换成当次真实内容即可；数字必须与 `bin/finproof_calc.py` 复算一致。
>
> **⚠️ 示例数据禁令**：本节示例里的 `https://example.com/...` 链接、`某财经媒体`·`某公司` 等来源名、以及所有示例数字**仅用于演示版式，一律不得出现在真实报告中**。真实报告的每个 `[E##]` 必须是当次实际检索/读取到的来源，逐字摘录必须是原文——**照抄示例 URL 等同于编造来源**，直接违反「绝不编造 URL」铁律。

```html
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>鉴融审计报告 · {{报告标题}}</title>
<!-- 复制「一、HTML 设计系统」的完整 <style> 至此 -->
<style>/* …设计系统 style… */</style>
</head>
<body>

<h1>鉴融审计报告</h1>

<!-- 报告基本信息（标题不加序号前缀） -->
<h2>报告基本信息</h2>
<div class="meta">
  <div><b>报告名称</b>{{文件名或标题}}</div>
  <div><b>页数 / 主张总数</b>{{N}} 页 / {{N}} 条主张</div>
  <div><b>核验模式</b>{{本地模式（不联网） / 联网模式}}</div>
  <div><b>运行档位</b>{{完整档 / 快速档（省略项：…；发现 REFUTED/CRITICAL 时建议重跑完整档）}}</div>
  <div><b>核验时间</b>{{YYYY-MM-DD HH:MM}}</div>
  <div><b>证据来源</b>本地文件 {{X}} 份 + 联网来源 {{Y}} 条</div>
  <div><b>计算方法</b>{{确定性引擎复算 bin/finproof_calc.py / 〔心算估算，未经引擎复算〕}}</div>
  <div><b>联网检索次数</b>{{M}} 次（预算上限 40 次）</div>
  <div><b>降级声明</b>{{无 / 〔心算估算，未经引擎复算〕}}</div>
  <div><b>引擎复算覆盖</b>N_e {{x}} / N_v {{y}} 条数值主张（{{x/y%}}；证据不足主张无证据数值，不计入 N_e）——判定溯源见审计轨迹</div>
  <div><b>主审模型</b>{{模型名}}</div>
  <div><b>独立复核</b>{{异源 · {{模型名}}（子代理盲复核） / 同源盲复核 / 未复核（原因）}}</div>
  <div><b>复现性声明</b>数值复算由确定性引擎执行、可复现；拆解与语义判定由模型产出，两次运行可能不同</div>
  <div><b>审计质量 AQS</b>{{94}} / 100 · 优（C 已判定/总主张 · E 引擎复算率 · V 证据可核性 · R 复核完成度 · L 链接复验率，五维明细见健康度段）</div>
</div>

<!-- 审计结论：问题前置，只列不确定与错误项（预测事实化的 G 类标记性问题项也进本段） -->
<h2>审计结论</h2>
<p>仅列不确定与错误项（按 反驳 &gt; 证据不足 &gt; 部分支持 &gt; 无法判断 &gt; 预测事实化 排序）；支持类不展开。预测事实化条目结论仍为「观点或预测」（G 类不判真假），进本段是因为确定性表述无已披露依据支撑。</p>
<table>
  <tr><th>#</th><th>报告原句</th><th>结论</th><th>问题</th><th>证据</th><th>建议</th></tr>
  <tr><td>#2</td><td>"公司 2026Q1 净利润同比增长 20%"</td><td><span class="v v-ref">反驳</span></td><td>复算 12.45%，超容差 7.55pp；以归母净利充"净利润"表述，口径未注明</td><td><a class="evid" href="#E02">[E02]</a> <a class="evid" href="#E03">[E03]</a></td><td>改为"归母净利润同比增长约 12.4%"</td></tr>
  <tr><td>#5</td><td>"市场份额提升至 4.8%"</td><td><span class="v v-par">部分支持</span></td><td>证据为 4.5% 且"基本持平"，"提升"无据</td><td><a class="evid" href="#E05">[E05]</a></td><td>改为"份额约 4.5%，与去年基本持平"</td></tr>
  <tr><td>#6</td><td>"某细分产品最新报价 XX 元/吨"</td><td><span class="v v-ins">证据不足</span></td><td>无支撑：G2 检索不可达（付费墙）</td><td><a class="evid" href="#E06">[E06]</a></td><td>凭已授权终端核对后回填</td></tr>
  <tr><td>#7</td><td>"2026 年归母净利润达 12 亿元已无悬念"</td><td><span class="v v-opi">观点或预测</span></td><td>预测事实化："已无悬念"为确定性表述，依据未披露（无测算过程与假设）</td><td>依据未披露（无 [E##]）</td><td>改为"我们预计约 12 亿元（测算依据：H1×2 并计 Q3 排产）"或披露依据</td></tr>
</table>
<p class="foot">其余 5 条主张经核验支持或属观点/预测且依据已披露，不展开；如需可索取逐条明细。</p>

<!-- 报告健康度（标题从简） -->
<h2>报告健康度</h2>

<h3>统计口径</h3>
<table>
  <tr><th>统计量</th><th>构成</th><th>对应主张</th></tr>
  <tr><td>总主张数 N</td><td>9 条</td><td>—</td></tr>
  <tr><td>G 类（不计入分母）</td><td>3 条</td><td>#7、#8、#9</td></tr>
  <tr><td>可判主张数 N_d</td><td>9 − 3 = 6 条</td><td>—</td></tr>
  <tr><td>闭环主张数 N_c</td><td>5 条</td><td>#1–#5</td></tr>
  <tr><td>未闭环</td><td>1 条</td><td>#6（证据不足）</td></tr>
  <tr><td>数值类主张数 N_v</td><td>4 条</td><td>#1、#2、#3、#6</td></tr>
  <tr><td>数值类错误数 E_v</td><td>1 条</td><td>#2</td></tr>
  <tr><td>引用错配 E_q / 期间错配 E_p / 口径问题 E_s / 证据不足 E_i</td><td>0 / 0 / 1(#2) / 1(#6)</td><td>—</td></tr>
</table>

<h3>五维明细</h3>
<table>
  <tr><th>维度</th><th>公式</th><th>原始观测</th><th>得分</th><th>加权贡献</th></tr>
  <tr><td>可判定率</td><td>N_c / N_d × 100</td><td>5 / 6</td><td>83.3</td><td>20.83</td></tr>
  <tr><td>数字与计算准确性</td><td>100 − E_v/N_v×100×2</td><td>100 − (1/4×100×2)</td><td>50.0</td><td>12.50</td></tr>
  <tr><td>引用一致性</td><td>100 − E_q/N_d×100×2</td><td>100 − 0</td><td>100.0</td><td>20.00</td></tr>
  <tr><td>来源权威性</td><td>闭环主张所用最高等级分均值</td><td>(3×100+1×70+1×40)/5</td><td>82.0</td><td>12.30</td></tr>
  <tr><td>时间与口径一致性</td><td>100 − (E_p+E_s)/N_d×100×2</td><td>100 − (1/6×100×2)</td><td>66.7</td><td>10.00</td></tr>
  <tr><th>合计</th><th></th><th></th><th></th><td><b>75.63 ≈ 76</b></td></tr>
</table>

<h3>证据等级分布</h3>
<table>
  <tr><th>等级</th><th>条数</th></tr>
  <tr><td><span class="g g-s">S 级</span></td><td>3</td></tr>
  <tr><td><span class="g g-a">A 级</span></td><td>1</td></tr>
  <tr><td><span class="g g-oth">其他</span></td><td>1</td></tr>
  <tr><td><span class="g g-none">未注明</span></td><td>0</td></tr>
</table>
<p class="foot">来源权威性 = (3×100 + 1×70 + 1×40) / 5 = 82.0。证据不足的 #6 不计入本维度（不属闭环）。S+A 级占比 4/5 = 80% ≥ 50%，权威性 82.0 ≥ 60——未触发弱来源警示。<b>若 S+A 占比 &lt;50% 或权威性 &lt;60，此处必须加显著警示行「⚠ 弱来源依赖：S+A 级证据占比 X%（x/y），本报告结论可靠性受限，建议补充交易所/定期报告等一手来源」。</b></p>

<h3>扣分清单</h3>
<table>
  <tr><th>序号</th><th>主张</th><th>证据</th><th>错误类型</th><th>扣分依据</th><th>影响维度</th></tr>
  <tr><td>1</td><td>#2</td><td>[E02]</td><td>#2 计算错误 + #2 口径错误</td><td>同比重算 12.45%，报告称 20%，差 7.55pp（超 0.5pp）；以归母净利充"净利润"表述，口径未注明</td><td>准确性 −50.0；时间口径 −33.3</td></tr>
  <tr><td>2</td><td>#6</td><td>[E06]</td><td>#6 证据不足</td><td>检索不可达（付费墙），未闭环</td><td>可判定率 −16.7</td></tr>
</table>
<p class="foot">本列口径为<b>维内扣分（含惩罚系数 2）</b>：准确性/引用一致性/时间口径三维的扣分 = 错误率 × 100 × 2；可判定率无惩罚系数。与五维明细得分一一对应（100 − 维内扣分 = 维度得分）。</p>

<h3>档位与固定文案</h3>
<div class="score-hero">76 / 100</div>
<p style="text-align:center"><b>‖ 审计质量 AQS 94 / 100 · 优</b>（C 100 · E 75 · V 100 · R 100 · L 100 → 93.75≈94；AQS 衡量审计过程，FinProof Score 衡量报告证据链——两分独立解读）</p>
<p><b>76 / 100 · 良——问题项 4 条（反驳 1 / 证据不足 1 / 部分支持 1 / 无法判断 0 / 预测事实化 1）；分数衡量证据链质量与引用规范，不代表结论正确性。</b>附加要求：列出瑕疵条数（上表 4 条，其中 #7 预测事实化为 G 类标记性问题项、不计入评分分母）；"优"档才强制首行点名 REFUTED 矛盾。</p>
<div class="note">
<b>【公式来源】</b>FinProof Score = 0.25×可判定率 + 0.25×数字准确性 + 0.20×引用一致性 + 0.15×来源权威性 + 0.15×时间与口径一致性；证据等级 S 100 / A 70 / 其他 40 / 未注明 0；加权求和使用未取整的各维分值，最后四舍五入到整数。完整规格见 scoring-spec.md。
</div>
<div class="warn">
<b>【固定警示】</b>FinProof Score 反映证据链质量与引用规范，不代表结论正确性。请结合「反驳/部分支持」条数与「需用户自行核验清单」一并判断。<b>不同报告的 Score 不可横向直接比较</b>——准确性与可判定率的分子/分母均随该报告自身主张总数变化。
</div>
<div class="note">
<b>【口径披露】</b>①「可判定率」（历史名「证据覆盖率」，公式与全部历史分数不变）衡量"能否判定"——闭环含支持/反驳/部分支持/无法判断，REFUTED 也计入闭环，错误较多但都能被判定的报告本维可为 100，它不衡量"证据是否充分、来源是否可靠"。②「来源权威性」仅占 15%，<b>数字自洽但来源等级普遍偏低的报告仍可能拿到"优"档</b>，请据此解读档次。③ 数值复算由确定性引擎执行（覆盖 N_e/N_v 见基本信息），拆解与语义判定由模型产出，两次运行可能不同。
</div>
<div class="note">
<b>【自评声明】</b>本分为专家自评，非第三方认证。分子/分母与公式均已列出，可自行复算；如复算与本文不一致，即为本专家实现有误，请指出。
</div>

<!-- 证据清单（只收录被问题项引用的 [E##]） -->
<h2>证据清单</h2>
<details id="E02">
  <summary><span class="g g-oth">[E02]</span> 其他 · 联网来源</summary>
  <div class="kv">
    <dt>来源</dt><dd>某财经媒体，2026-04-24 报道</dd>
    <dt>链接</dt><dd><a href="https://example.com/news/2026-04-24/xxxxx" target="_blank" rel="noopener noreferrer">https://example.com/news/2026-04-24/xxxxx</a>〔复验：可达 · 2026-09-10 17:30〕</dd>
    <dt>抓取</dt><dd>2026-09-10 17:20</dd>
    <dt>定位</dt><dd>正文第 6 段、第 14 段</dd>
    <dt>逐字摘录</dt><dd>「一季度实现归属于母公司股东的净利润 2.8 亿元，同比增长 12.4%」</dd>
    <dt>关联</dt><dd>反驳 <a class="evid" href="#c2">#2</a></dd>
  </div>
</details>
<details id="E03">
  <summary><span class="g g-s">[E03]</span> S 级 · 联网来源</summary>
  <div class="kv">
    <dt>来源</dt><dd>某公司 2026 年第一季度报告（交易所信息披露平台）</dd>
    <dt>链接</dt><dd><a href="https://example.com/disclosure/detail?id=xxxxx" target="_blank" rel="noopener noreferrer">https://example.com/disclosure/detail?id=xxxxx</a>〔复验：重定向至信息披露平台 · 2026-09-10 17:31〕</dd>
    <dt>抓取</dt><dd>2026-09-10 17:22</dd>
    <dt>定位</dt><dd>第 3 页「主要会计数据」表第 2 行</dd>
    <dt>逐字摘录</dt><dd>「营业收入 60.00 亿元，本报告期比上年同期增减 12.40%」</dd>
    <dt>关联</dt><dd>反驳 <a class="evid" href="#c2">#2</a>（2026Q1 对照期数据）</dd>
  </div>
</details>
<details id="E05">
  <summary><span class="g g-a">[E05]</span> A 级 · 联网来源</summary>
  <div class="kv">
    <dt>来源</dt><dd>某公司投资者关系活动记录表（公司官网）</dd>
    <dt>链接</dt><dd><a href="https://example.com/ir/xxxxx" target="_blank" rel="noopener noreferrer">https://example.com/ir/xxxxx</a>〔复验：可达 · 2026-09-10 17:33〕</dd>
    <dt>抓取</dt><dd>2026-09-10 17:25</dd>
    <dt>定位</dt><dd>问答第 3 问</dd>
    <dt>逐字摘录</dt><dd>「公司在 XX 细分市场的份额约为 4.5%，与去年同期基本持平」</dd>
    <dt>关联</dt><dd>部分支持 <a class="evid" href="#c5">#5</a>（报告称"提升至 4.8%"，与 4.5% 不符；"提升"无据）</dd>
  </div>
</details>
<details id="E06">
  <summary><span class="g g-oth">[E06]</span> 其他 · 联网来源（不可达）</summary>
  <div class="kv">
    <dt>来源</dt><dd>某行业数据库（需授权终端）</dd>
    <dt>链接</dt><dd>未取得可访问链接（付费墙，未检索）</dd>
    <dt>抓取</dt><dd>—</dd>
    <dt>定位</dt><dd>—</dd>
    <dt>逐字摘录</dt><dd>—</dd>
    <dt>关联</dt><dd>证据不足 <a class="evid" href="#c6">#6</a>（[G2] 检索不可达）</dd>
    <dt>备注</dt><dd>已尝试 3 轮检索（见聚焦再搜索记录），未取得可访问来源；未闭环 ≠ 通过，请用户凭已授权终端自行核对。</dd>
  </div>
</details>

<!-- 主张核验卡（只出问题项；支持类不建卡） -->
<h2>主张核验卡</h2>

<div class="claim" id="c2">
  <div class="hd"><span class="num">#2</span><span class="v v-ref">反驳</span><span class="risk">风险：高</span><span>B 计算型 + C 口径型</span></div>
  <div class="kv">
    <dt>报告原句</dt><dd>"公司 2026 年第一季度净利润同比增长 20%"</dd>
    <dt>证据引用</dt><dd><a class="evid" href="#E02">[E02]</a>（其他）第 6 段；<a class="evid" href="#E03">[E03]</a>（S 级）p.3「主要会计数据」</dd>
    <dt>复算</dt><dd>报告值 +20%；证据 2026Q1 净利 2.8 亿 / 2025Q1 2.49 亿 → (2.8−2.49)/2.49 = 12.45%；绝对差 7.55pp，相对差 60.6%；容差 ±0.5pp，严重超限 → 不匹配〔引擎复算〕</dd>
    <dt>口径对照</dt><dd>报告口径 = 净利润（归母/扣非未注明）｜证据口径 = 归母净利润 → 不一致（以归母数据充"净利润"表述，口径未注明）</dd>
    <dt>单位确认</dt><dd>亿元（CNY）；% 与 pp 未混用</dd>
    <dt>修改建议</dt><dd>改为"归母净利润同比增长约 12.4%"，并注明所用口径</dd>
  </div>
</div>

<div class="claim" id="c5">
  <div class="hd"><span class="num">#5</span><span class="v v-par">部分支持</span><span class="risk">中</span><span>F 比较型</span></div>
  <div class="kv">
    <dt>报告原句</dt><dd>"市场份额提升至 4.8%"</dd>
    <dt>证据引用</dt><dd><a class="evid" href="#E05">[E05]</a>（A 级）问答第 3 问</dd>
    <dt>复算</dt><dd>证据 4.5% 且"基本持平"；报告 4.8% 且"提升" → 数值差 0.3pp，方向无据〔引擎复算〕</dd>
    <dt>修改建议</dt><dd>改为"份额约 4.5%，与去年基本持平"</dd>
  </div>
</div>
<div class="claim" id="c6">
  <div class="hd"><span class="num">#6</span><span class="v v-ins">证据不足</span><span class="risk">高</span><span>A 原始数字</span></div>
  <div class="kv">
    <dt>报告原句</dt><dd>"某细分产品最新报价 XX 元/吨"</dd>
    <dt>证据引用</dt><dd><a class="evid" href="#E06">[E06]</a>（其他·不可达）</dd>
    <dt>缺口分类</dt><dd>[G2] 检索不可达（付费墙）</dd>
    <dt>修改建议</dt><dd>凭已授权终端核对后回填；未闭环 ≠ 通过</dd>
  </div>
</div>

<div class="claim" id="c7">
  <div class="hd"><span class="num">#7</span><span class="v v-opi">观点或预测</span><span class="risk">中</span><span>G 预测观点 · 依据未披露</span></div>
  <div class="kv">
    <dt>报告原句</dt><dd>"2026 年归母净利润达 12 亿元已无悬念"</dd>
    <dt>依据披露</dt><dd>依据未披露——报告未给出测算过程、假设与输入（无 [E##] 可挂）</dd>
    <dt>问题定性</dt><dd>预测事实化："已无悬念"为确定性措辞，把前瞻值当事实陈述；G 类不判真假，故结论仍为观点或预测，但按 SKILL §一 G 类输出纪律列入问题项</dd>
    <dt>修改建议</dt><dd>改为"我们预计约 12 亿元"并披露测算依据；或删除确定性措辞</dd>
  </div>
</div>

<!-- 需用户自行核验清单 -->
<h2>需用户自行核验清单</h2>
<div class="claim">
  <div class="hd"><span class="v v-ins">影响核心结论</span></div>
  <div class="kv">
    <dt>主张</dt><dd><a class="evid" href="#c6">#6</a></dd>
    <dt>证据</dt><dd><a class="evid" href="#E06">[E06]</a>（其他·不可达）</dd>
    <dt>原因</dt><dd>该价格是报告盈利预测的直接输入项，错则结论反转</dd>
    <dt>已尝试</dt><dd>3 轮检索（见 [E06] 备注），未取得可访问来源</dd>
    <dt>动作</dt><dd>请用已授权终端核对后回填</dd>
    <dt>注意</dt><dd>未闭环 ≠ 通过</dd>
  </div>
</div>
<div class="claim">
  <div class="hd"><span class="v v-opi">次优先</span></div>
  <div class="kv">
    <dt>主张</dt><dd><a class="evid" href="#c7">#7</a>（预测事实化）</dd>
    <dt>缺口分类</dt><dd>[G3] 非公开数据——预测依据（测算假设/输入）未随报告披露</dd>
    <dt>动作</dt><dd>向作者索取测算依据；确认后标注「内部估算」或补披露</dd>
  </div>
</div>

<!-- 对抗性抽查 -->
<h2>对抗性抽查</h2>
<table>
  <tr><th>检查项</th><th>结果</th></tr>
  <tr><td>明细偏差（>0.1% / 增长率 >0.5pp）</td><td>4 条数值主张中超容差 1 条：#2（7.55pp）；标 [舍入差异] 0 条</td></tr>
  <tr><td>口径伪装（归母↔扣非 / 营收↔营业总收入 / 单季↔累计 / 合并↔母公司）</td><td>核验 4 项，发现 1 处（#2 以归母净利充"净利润"表述，口径未注明）</td></tr>
  <tr><td>单位与币种</td><td>确认单位 6 条 / 未确认 0 / % 与 pp 混用 0 处</td></tr>
  <tr><td>编造因果</td><td>E 类主张 0 条</td></tr>
  <tr><td>引用错配（来源+页码/章节+报告期三对齐，含时序不可能检查）</td><td>检查 5 条，发现 0 处不对齐；时序不可能 0 处（来源覆盖期间均不早于数据所属期间）</td></tr>
  <tr><td>预测事实化（确定性措辞的 G 类）</td><td>G 类主张 3 条中 1 条带确定性措辞且依据未披露（#7），已列问题项；其余 2 条标注依据已披露</td></tr>
  <tr><td>元攻击</td><td>[疑似检索逃逸] 0 条 / G2 付费墙缺口 1 条（#6，未闭环 ≠ 通过）</td></tr>
</table>
<div class="warn">Score 提示：FinProof Score 反映证据链质量与引用规范，不代表结论正确性。</div>

<!-- 独立复核 -->
<h2>独立复核</h2>
<table>
  <tr><th>项</th><th>内容</th></tr>
  <tr><td>复核方式</td><td>异源 · {{复核模型名，如 GLM-5.3-Flash}}（经子代理盲复核，仅输入主张原文+证据摘录+复算数字，不含主审结论）+ 自检层〔引擎重跑 3/3 一致 · 摘录复读 3/3 一致 · 口径核对 ✓〕</td></tr>
  <tr><td>复核范围</td><td>问题项 4/4 条（#2 #5 #6 #7）+ 支持项抽样 3 条（#1 #3 #4）+ 评分复算 ✓</td></tr>
  <tr><td>结果</td><td>一致 7 条 · 分歧 0 条（若有分歧逐条列：#N · 主审判 X（依据）· 复核判 Y（理由）· 分歧点与处理）</td></tr>
</table>
<p class="foot">协议见 independent-review.md：异源优先（不同模型经子代理盲复核）> 同源盲复核 > 自检复核〔机械层：仅防算错抄错，非独立判断〕> 未复核（如实写原因）。复核降低单模型误判风险，不改变评分的自评性质。</p>

<!-- 审计轨迹（仅问题项） -->
<h2>审计轨迹</h2>
<table>
  <tr><th>主张</th><th>证据 → 计算 → 判定</th></tr>
  <tr><td><a class="evid" href="#c2">#2</a></td><td>[E02]+[E03] → 引擎 yoy --current 2.8 --previous 2.49 → 12.4498%，vs 报告 20%，超容差 7.55pp → REFUTED</td></tr>
  <tr><td><a class="evid" href="#c5">#5</a></td><td>[E05] → 证据 4.5% 且"基本持平" vs 报告 4.8% 且"提升"，数值差 0.3pp、方向无据 → PARTIALLY_SUPPORTED</td></tr>
  <tr><td><a class="evid" href="#c6">#6</a></td><td>[E06] 付费墙不可达，3 轮检索无果 → INSUFFICIENT（未闭环 ≠ 通过）</td></tr>
</table>

<!-- 附录：评分与分类标准（必附，置于报告最末） -->
<h2 id="appendix">附录 · 评分与分类标准</h2>
<p>本附录是本次评分所依据的全部标准，随报告交付，便于读者直接在报告内复核；口径与 <code>scoring-spec.md</code>、<code>SKILL.md</code> 一致。</p>

<h3>A. 五维定义与公式</h3>
<table>
  <tr><th>维度</th><th>权重</th><th>公式</th><th>满分条件</th></tr>
  <tr><td>可判定率</td><td>25%</td><td>N_c / N_d × 100</td><td>全部可判主张有证据闭环</td></tr>
  <tr><td>数字与计算准确性</td><td>25%</td><td>max(0, 100 − E_v/N_v × 100 × 2)</td><td>无数值类 REFUTED</td></tr>
  <tr><td>引用一致性</td><td>20%</td><td>max(0, 100 − E_q/N_d × 100 × 2)</td><td>引用均三对齐</td></tr>
  <tr><td>来源权威性</td><td>15%</td><td>Σ(每条闭环主张最高证据等级分) / N_c</td><td>全部主张由 S 级证据支撑</td></tr>
  <tr><td>时间与口径一致性</td><td>15%</td><td>max(0, 100 − (E_p+E_s)/N_d × 100 × 2)</td><td>无期间错配与口径混用</td></tr>
  <tr><th>总分</th><th>100%</th><td colspan="2">0.25×可判定率 + 0.25×准确性 + 0.20×引用一致性 + 0.15×来源权威性 + 0.15×时间口径</td></tr>
</table>
<p class="foot">取整规则：加权求和使用未取整的各维分值，最后四舍五入到整数；展示时各维保留一位小数、加权贡献保留两位小数（先各自取整再加权会产生累积误差，禁止）。惩罚系数 = 2。N_v = 0（纯定性报告）时准确性按 80 计。</p>

<h3>B. 统计口径</h3>
<table>
  <tr><th>符号</th><th>含义</th></tr>
  <tr><td>N</td><td>总主张数（含观点/预测）</td></tr>
  <tr><td>N_d</td><td>可判主张数 = N − 观点/预测类(G)</td></tr>
  <tr><td>N_c</td><td>闭环主张数（有证据可判：支持/反驳/部分支持/无法判断；不含证据不足）</td></tr>
  <tr><td>N_v</td><td>数值类主张数（A/B/C 三类）</td></tr>
  <tr><td>N_e</td><td>数值类主张中经引擎复算的条数（不计分，仅判定溯源；证据不足主张无证据数值，不计入）。口径（v2.6.0 固定）：只计"实际调用引擎且审计轨迹留有命令与输出"的主张；〔逐字一致，免引擎〕与〔心算估算〕均计入 N_v、不计入 N_e</td></tr>
  <tr><td>E_v / E_q / E_p / E_s / E_i</td><td>数值错误 / 引用错配 / 期间错配 / 口径问题 / 证据不足 的条数</td></tr>
</table>

<h3>C. 证据等级标准</h3>
<table>
  <tr><th>等级</th><th>分值</th><th>典型来源</th></tr>
  <tr><td><span class="g g-s">S</span></td><td>100</td><td>交易所公告、定期报告（年报/中报）、招股书、监管/审计/法院/政府正式文件</td></tr>
  <tr><td><span class="g g-a">A</span></td><td>70</td><td>公司官网、投资者关系材料、业绩说明会、公司公告性新闻稿</td></tr>
  <tr><td><span class="g g-oth">其他</span></td><td>40</td><td>权威财经媒体、第三方研究机构、行业协会、政府统计年鉴</td></tr>
  <tr><td><span class="g g-none">未注明</span></td><td>0</td><td>报告未给出来源，或来源不可追溯</td></tr>
</table>

<h3>D. 分数档位与附加要求</h3>
<table>
  <tr><th>档位</th><th>区间</th><th>含义</th><th>附加要求</th></tr>
  <tr><td>优</td><td>90–100</td><td>证据链完整，无实质性问题</td><td>若仍有 REFUTED，须在摘要首行点名该矛盾</td></tr>
  <tr><td>良</td><td>75–89</td><td>个别瑕疵，不影响核心结论</td><td>列出瑕疵条数</td></tr>
  <tr><td>一般</td><td>60–74</td><td>存在影响局部结论的问题，需修订</td><td>给出修订优先级</td></tr>
  <tr><td>差</td><td>&lt;60</td><td>存在影响核心结论的问题，不建议直接使用</td><td>列出所有 REFUTED 与核心缺口</td></tr>
</table>

<h3>E. 主张分类</h3>
<table>
  <tr><th>类型</th><th>说明</th><th>核验重点</th></tr>
  <tr><td>A 原始数字</td><td>直接陈述的数值</td><td>数字 / 单位 / 量级 / 期间 / 口径</td></tr>
  <tr><td>B 计算型</td><td>含同比·环比·比率等推导</td><td>取两期数据重新算</td></tr>
  <tr><td>C 口径型</td><td>涉及单季/累计、归母/扣非等</td><td>披露的是哪种口径</td></tr>
  <tr><td>D 业务事实</td><td>定性业务结论</td><td>是否有披露支撑（市占率/客户/产能等）</td></tr>
  <tr><td>E 因果型</td><td>归因结论</td><td>原文是否支持所引原因、机制性表述</td></tr>
  <tr><td>F 比较型</td><td>同业 / 对标比较</td><td>对标对象、指标、期间、口径是否可比</td></tr>
  <tr><td>G 预测观点</td><td>前瞻 / 主观判断</td><td>标为观点，核查是否披露依据，不判真假；标注「依据已披露/未披露」，确定性措辞的预测按「预测事实化」进问题项</td></tr>
</table>

<h3>F. 六类结论与触发条件</h3>
<table>
  <tr><th>结论</th><th>触发条件</th></tr>
  <tr><td><span class="v v-sup">支持</span></td><td>证据直接支持主体/指标/期间/单位/口径/数值，且在容差内</td></tr>
  <tr><td><span class="v v-ref">反驳</span></td><td>证据给出冲突事实、错值、错期、错单位或相反方向</td></tr>
  <tr><td><span class="v v-par">部分支持</span></td><td>多组成部分中部分成立、关键部分缺失，或证据只支持较弱表述</td></tr>
  <tr><td><span class="v v-ins">证据不足</span></td><td>既不能证明也不能反驳（不得把解析失败归入此类）</td></tr>
  <tr><td><span class="v v-opi">观点或预测</span></td><td>预测/展望/主观判断，不判真假；须标注依据已披露/未披露；确定性措辞的预测按「预测事实化」列入审计结论问题项</td></tr>
  <tr><td><span class="v v-opi">无法判断</span></td><td>材料缺失或不可判定</td></tr>
</table>
<p class="foot">优先级顺序（取舍顺序，非等级）：REFUTED &gt; SUPPORTED &gt; PARTIALLY_SUPPORTED &gt; INSUFFICIENT。</p>

<h3>G. 缺口分类</h3>
<table>
  <tr><th>缺口</th><th>含义</th><th>用户动作</th></tr>
  <tr><td>G1</td><td>源文件缺失</td><td>上传后重跑该主张</td></tr>
  <tr><td>G2</td><td>检索不可达（付费墙 / 未索引 / 离岸 / Pre-IPO 分散披露）</td><td>凭已授权数据源自核；未闭环 ≠ 通过</td></tr>
  <tr><td>G3</td><td>非公开数据（细分口径、内部假设）</td><td>确认依据，标注「内部估算/未审计」</td></tr>
  <tr><td>G4</td><td>提取失败（加密 / 损坏 / 模糊到手写级）</td><td>提供清晰文本版；须先走内置 OCR</td></tr>
</table>

<h3>H. 复算容差表</h3>
<table>
  <tr><th>复算类型</th><th>容差</th><th>超限判定</th></tr>
  <tr><td>数值比对 / 累计转单季 / 比率</td><td>相对 0.1%</td><td>REFUTED</td></tr>
  <tr><td>同比 / 环比增长率</td><td>0.5 个百分点（pp）</td><td>REFUTED</td></tr>
  <tr><td>披露舍入豁免（唯一例外）</td><td>最多 0.5%</td><td>超过 0.5% 一律 REFUTED</td></tr>
</table>

<div class="note"><b>口径披露</b>：①「可判定率」（历史名「证据覆盖率」，公式与全部历史分数不变）衡量"能否判定"——闭环含 REFUTED，不衡量证据是否充分、来源是否可靠；②「来源权威性」仅占 15%，数字自洽但来源等级普遍偏低的报告仍可能拿到"优"档；③ 数值复算由确定性引擎执行（覆盖 N_e/N_v 见基本信息），拆解与语义判定由模型产出、两次运行可能不同；④ 本分为<b>专家自评</b>（判定经独立复核，见「独立复核」段），且不同报告的 Score 不可横向直接比较。完整依据见 <code>scoring-spec.md</code>。</div>

<p class="foot">本报告由鉴融（FinProof）生成 · {{YYYY-MM-DD HH:MM}} · 专家自评，非第三方认证 · 公式与分子分母均公开，可自行复算。</p>
</body>
</html>
```

---

## 六、主张卡 HTML 片段（单条，复制填写）

```html
<div class="claim" id="cN">
  <div class="hd"><span class="num">#N</span><span class="v v-XXX">结论</span><span class="risk">风险：低/中/高</span><span>类型 A–G</span></div>
  <div class="kv">
    <dt>报告原句</dt><dd>"逐字引用"</dd>
    <dt>证据引用</dt><dd><a class="evid" href="#EXX">[EXX]</a>（等级）定位</dd>
    <dt>复算</dt><dd>报告值 / 复算值 / 绝对差 / 相对差%（数值类必填）＋判定来源标记〔引擎复算〕/〔心算估算，未经引擎复算〕</dd>
    <dt>口径对照</dt><dd>报告口径 vs 证据口径（数值类必填）</dd>
    <dt>单位确认</dt><dd>单位 / 币种 / 汇率来源 / % 与 pp 区分</dd>
    <dt>修改建议</dt><dd>如何修正</dd>
  </div>
</div>
```

## 七、证据清单 HTML 片段（单条，复制填写）

```html
<details id="EXX" open>
  <summary><span class="g g-s/g-a/g-oth/g-none">[EXX]</span> 等级 · 本地文件/联网来源（不可达）</summary>
  <div class="kv">
    <dt>来源</dt><dd>具体机构/文件名</dd>
    <dt>链接</dt><dd><a href="url" target="_blank" rel="noopener noreferrer">完整 URL</a>〔复验：可达 / 重定向 / 不可达(状态码) / 未复验(原因) · YYYY-MM-DD〕 或 「本地文件（无 URL）」/「未取得可访问链接（原因）」</dd>
    <dt>抓取</dt><dd>YYYY-MM-DD HH:MM 或 —</dd>
    <dt>定位</dt><dd>页码/章节/表格/段落</dd>
    <dt>逐字摘录</dt><dd>「原文片段，不得转述」</dd>
    <dt>关联</dt><dd>支撑/反驳/部分支持 <a class="evid" href="#cN">#N</a></dd>
  </div>
</details>
```

---

## 八、分批审输出（主张数 > 25 条时）

主张数 > 25 条先用「审查计划」卡片列出总数/分类计数/高风险项/分批数，再按批输出主张卡（高风险优先），每批末标进度（"第 2/4 批，已审 15/40 条"）。**全部批次完成后才输出总分**——分数必须基于已审全部主张，未审完不得给分。

**交付收敛纪律（避免"假完整报告"）**：
- 分批过程中**只输出中间态主张卡**，此时**不得给出总分、档位或「零/一」两段**——没有分数的半份报告不会被人误当成结论。
- 全部批次审完后，**最终必须收敛为单一 HTML 文件**（一个 `.html`，含全部主张卡与全量证据清单）。**不得**把每批各存成一个 HTML，那会产出多份"看起来都完整"的报告。
- 若因轮次限制确实无法一次承载，则：中间批次只给文本片段，最后一批再统一生成完整 HTML；并在报告中声明实际审计覆盖的主张范围（如"已审 40/40"或"仅审 12/40，其余列入未检索清单"）。

```html
<div class="claim"><div class="hd"><span class="num">审查计划</span></div>
  <div class="kv">
    <dt>总主张</dt><dd>40 条（高风险 12）</dd>
    <dt>分批</dt><dd>4 批，高风险优先</dd>
    <dt>进度</dt><dd>第 2/4 批完成，已审 20/40 条</dd>
  </div>
</div>
```

---

## 九、纯文本降级模板（环境无法输出 HTML 时）

若运行环境不支持保存/渲染 HTML，按以下纯文本输出，**结构、字段与上方 HTML 版完全一致**（含问题前置、只报问题项、末尾附录），仅去色彩/折叠/锚点。必填项一字不省：

```text
报告基本信息
  报告名 · 页数/主张数 · 核验模式 · 核验时间 · 证据来源统计 · 计算方法（含降级声明）· 联网检索次数
  · 引擎复算覆盖 N_e/N_v · 主审模型 · 独立复核模型（方式）· 复现性声明
  （标题不带序号前缀）

审计结论（只列不确定与错误项，按 反驳 > 证据不足 > 部分支持 > 无法判断 > 预测事实化 排序）
  #N 报告原句 / 结论 / 一句话问题 / 证据引用[E##] / 建议
  （预测事实化：结论仍为观点或预测，问题写"确定性表述但依据未披露"）
  末行：其余 N 条经核验支持（或属观点/预测且依据已披露），不展开

报告健康度
  统计口径：N / N_d / N_c / N_v / N_e / E_v·E_q·E_p·E_s·E_i 的数值 + 对应主张编号
  五维明细：维度 → 原始观测 → 得分 → 加权贡献 → 合计取整
  证据等级分布：按等级给条数（用于复核来源权威性）；S+A<50% 或权威性<60 加「⚠ 弱来源依赖」
  扣分清单：序号·主张·证据·错误类型·扣分依据·影响维度（维内扣分，含惩罚系数 2）
  档位行（含问题项计数）+ 公式来源 + 固定警示 + 口径披露 + 自评声明（逐字）

证据清单（只收录问题项引用的 [E##]）
  每条九字段：编号·等级·类型·来源名称·链接（含复验状态）·抓取时间·定位·逐字摘录·关联主张

主张核验卡（只出问题项；支持类不建卡；预测事实化的 G 类问题项建卡，另含"依据披露"字段）
  #N 报告原句 / 类型 / 风险 / 结论 / 证据引用[E##] / 复算(报告值·复算值·绝对差·相对差%＋判定来源标记) / 口径对照 / 单位确认 / 建议

需用户自行核验清单（按影响核心结论程度排序）
  [Gx] + 主张 + 证据 + 原因 + 用户动作 + 已尝试手段 + 未闭环 ≠ 通过

对抗性抽查（无可疑项写"未发现"）

独立复核
  复核方式（异源模型名 / 同源盲复核 / 自检复核〔机械层〕+ 计数 / 未复核+原因）· 范围 · 一致/分歧计数 · 分歧明细

审计轨迹（仅回放问题项：证据 → 计算（引擎命令与输出） → 判定）

附录 · 评分与分类标准（置于报告最末，必附）
  A 五维定义与公式 / B 统计口径符号 / C 证据等级标准 / D 分数档位与附加要求
  / E 主张分类 A–G / F 六类结论与触发条件 / G 缺口分类 G1–G4 / H 复算容差表
```

---

## 十、输出约束（铁律，HTML 与纯文本通用）

- **可核对**：每条主张挂 `[E##]`；每个 `[E##]` 在证据清单有完整九字段；联网证据带 URL 与抓取时间；摘录逐字不转述。
- **可速读**：问题前置、只报问题项——① 标题从简、不加序号前缀（"报告基本信息""报告健康度"）；② 「审计结论」紧随基本信息，**只列反驳 / 证据不足 / 部分支持 / 无法判断 / 预测事实化**；③ **支持类主张不建卡、不逐条叙述**，只在审计结论末尾给一句计数；④ 正文不写客套话、不复述公式全文（公式与标准在附录）。**省篇幅，但不省必填项。**
- **可溯源（v2.5.0）**：数值判定标判定来源〔引擎复算〕/〔心算估算〕；审计轨迹保留引擎命令与输出；基本信息公开引擎复算覆盖 N_e/N_v——"数字归程序"要有运行证据，不能只靠声明。
- **双通道（v2.5.0）**：报告必含「独立复核」段——异源模型名 / 同源盲复核 / 自检复核〔机械层〕/ 未复核+原因，四档如实写（可组合）；**没做复核不得伪装成做过**，自检复核不得写成"已独立复核"。
- **链接复验（v2.5.0）**：定稿前逐条访问证据 URL，复验状态缀于链接字段（可达/重定向/不可达(状态码)/未复验(原因)+日期）；不可达降一档并保留原摘录；**不得谎称已验**。
- **HTML 安全**：报告原文一律先转义 `&` `<` `>` 再入 HTML（报告是**不可信输入**）；`[E##]` 锚点 id 全报告唯一；外链带 `rel="noopener noreferrer"`。**不得照抄模板里的 `example.com` 示例链接**。
- **可留档**：必须保留 `@media print` 规则，并确保打印/存 PDF 时折叠的证据清单被展开——否则最关键的溯源层会在打印件上消失。
- **可推导**：分数附统计口径构成 + 五维公式 + 原始观测 + 加权贡献 + 扣分清单 + 档位（含问题项计数）+ 公式来源 + 固定警示 + 口径披露 + 自评声明。
- **可自解释**：附录必附——报告最末必须附「评分与分类标准」附录（五维公式 / 统计口径 / 证据等级 / 档位 / 主张分类 / 六类结论 / 缺口分类 / 容差表）。**读者应在报告内就能查到"依据哪些维度、怎么算、公式是什么、评分与分类标准是什么"，无需翻阅外部文档。** 分数是主观产出没问题，但依据必须公开可查。
- **不编造**：不编造 URL/页码/摘录/演示数据；无来源须显式标"未注明"档，不得写"据公开资料"含糊带过。
- **不隐瞒**：冲突证据全部列出并说明采信理由；未检索项单列；不利结论照写；复核分歧照写。
- **不越界**：不提供投资建议；预测/观点不判真假，但须核查是否披露依据。
- **降级声明**：无 shell 时标 `〔心算估算，未经引擎复算〕`；无 API Key 时标「Mock 模式，非真实模型输出」。
