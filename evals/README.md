# 简历质量评测

P1-003 提供版本反馈、行为指标和固定样例回归评测。评测用于判断修改是否造成可观察的质量回退；真实招聘效果仍需独立验证。

## 页面反馈与指标

结果页可以评价整份已保存简历，也可以在差异卡片中评价单条修改。评分为 1–5 分，并可选择事实准确性、岗位相关性、表达清晰度、格式或信息遗漏等原因。同一版本、同一修改项重新评分会更新原记录，不增加样本数；更换简历版本会创建独立评价。反馈记录包含版本来源及生成环境，不收集自由文本。

任务历史下方的「反馈与质量概览」展示：

- 已开始、已完成、主动审阅、保存编辑和成功导出的任务数。这些是行为统计，各项不要求严格逐步递减。
- 整份评分的平均分与满意率，以及单条修改评分的数量和平均分。满意率为整份评分达到 4 分及以上的比例；没有评价时显示「暂无数据」。
- 用户主动点击的修改接受率。默认保留不算接受，切换决策以同一版本同一修改项的最后一次选择为准。
- 按招聘类型、输出语言、原始生成环境和北京时间日期查看的指标。评分针对用户所评价的保存版本，可能包含用户编辑，不能当作纯粹的原始 AI 输出评分。

保存编辑只统计实际内容变化；分页预览及失败的文件生成不算导出，成功的文件生成也不代表用户已提交申请。同一任务多次导出按一个导出任务计算。接口重试不会重复增加修改决策统计。

网页只汇总当前浏览器凭据可访问的任务。反馈和事件保存在 `QUALITY_STORE_PATH` 指定的本地 SQLite 中（默认 `.dist/quality.sqlite3`），随任务删除或过期清理；删除简历版本会清理对应评价和事件。因此指标覆盖当前保存期限内的数据，不能当作长期完整的产品统计。

产品维护者可以在服务器本地查看同一保存期内的汇总，无需通过公共接口暴露所有用户的统计：

```bash
python scripts/quality_report.py --output .dist/evaluations/quality-dashboard.json
```

## 生成环境标识

每次完整生成、局部重写和手工保存版本都会记录对应环境，包括模型标识、提示词版本与内容摘要、评分规则版本与源码摘要、生成流程源码摘要和处理模式。客户端传入的完整生成环境会被服务端覆盖。

任务恢复时保留已知的原始环境；恢复环境发生变化时记录环境历史，质量概览将这类任务单独列为混合环境。旧任务没有记录过的信息显示为未知，不会用当前配置冒充原始配置。

## 固定评测集

[resume_quality_v1.json](resume_quality_v1.json) 包含四个合成样例，覆盖中文、英文及校招、实习、社招。候选人、学校、项目均为示例，不包含联系方式；只有明确确认的事实会进入生成流程。

每个样例检查招聘类型、输出语言、已确认技能保留、经历事实溯源覆盖、匹配参考分阈值、未支持表述及明确禁止的虚构表述。报告只包含指标、生成环境、耗时和经过白名单处理的失败诊断，不写入简历正文、模型原始错误、响应正文、接口地址或密钥。失败时保留模型环境，并标明失败阶段和类别，例如模型不可用、凭据拒绝、限流、超时或结构校验失败。程序异常还记录白名单内的异常类型和仓库内代码位置，不包含异常原文或绝对文件路径。

先建立本地规则基线，再执行回归：

仓库也提供 [stub_v1.json](baselines/stub_v1.json) 作为初始规则基线，可直接通过 `--baseline evals/baselines/stub_v1.json` 执行对照。

```bash
python scripts/evaluate_quality.py --provider stub --output .dist/evaluations/stub-baseline.json
python scripts/evaluate_quality.py --provider stub --baseline .dist/evaluations/stub-baseline.json --output .dist/evaluations/stub-current.json
```

真实模型发布前，使用 `.env` 中配置的模型执行相同样例：

```bash
python scripts/evaluate_quality.py --provider configured --output .dist/evaluations/release-baseline.json
# 修改模型或提示词后：
python scripts/evaluate_quality.py --provider configured --baseline .dist/evaluations/release-baseline.json --output .dist/evaluations/release-current.json
```

只为本次评测覆盖模型名称，不修改 `.env`：

```bash
python scripts/evaluate_quality.py --provider configured --model qwen-plus --output .dist/evaluations/qwen-plus-current.json
```

`--model` 只适用于 `configured`；接口地址、密钥及其他设置沿用当前配置。配置中有模型名称和密钥并不代表该账号能使用模型；例如服务返回 `model_not_found` 时，应按服务方的账号、地区和模型权限核对，不会自动替换模型。HTTP 401 / 402 / 403 / 404 不重复请求；结构格式不支持时仍可重试为 JSON object。

`configured` 会调用真实模型，并要求模型可用且使用严格模式。`stub` 只验证流程和规则，不代表真实模型质量。评测通过返回退出码 `0`，质量失败或回退返回 `1`，配置或基线无效返回 `2`；输出文件不能覆盖所用基线或评测集。每个样例完成后立即输出进度、耗时和诊断；最终报告同时记录开始与结束时间。

评测集与基线在调用模型前校验，避免因配置或基线无效产生不必要调用。回归要求评测集内容摘要和评测规则版本一致，且基线样例完整、不重复、指标有效。部分样例生成失败时，仍会检查其他样例的质量回退。报告格式新增字段使用 `report_schema_version: 2` 标记，质量规则仍为 `resume-quality-v1`，原规则基线可以继续对照。默认允许匹配参考分下降最多 2 分；原通过样例失败、事实溯源覆盖下降、未支持表述增加或真实性风险升高都会阻止通过。可通过 `--max-score-drop` 修改分数容差。

## 求职材料包与模拟面试评测

`--suite preparation` 使用 [preparation_quality_v1.json](preparation_quality_v1.json) 的 10 个合成样例，不读取用户任务、基础档案或面试数据库。上下文是人工构造的已保存简历、JD 与事实快照，覆盖中英文。

- 两个材料包样例检查七种材料齐全、事实来自当前已保存版本、未确认经历不会进入正文、项目之间不混用事实、自我介绍长度区分、编辑风险提示和导出版本 / JD 标识。
- 八个面试样例覆盖正常回答、数字与职责夸大、未确认技术、否定表达、假设回答，以及从另一项目借用数字。检查回答引文、事实 ID、规则风险保留、追问边界、改进建议不新增数字或技术、复习报告与源事实不被修改。
- 真实模型模式要求调用成功；结果来自生产标准化与规则保护之后的内容。材料正文中的事实仍采用原句与模板，模型只选择证据和顺序；面试分轮问题与追问由现有规则构建。通过检查不表示未经处理的模型输出全部正确，也不验证表达自然度或面试通过率。

```bash
python scripts/evaluate_quality.py --suite preparation --provider stub --baseline evals/baselines/preparation_stub_v1.json --output .dist/evaluations/preparation-stub.json
python scripts/evaluate_quality.py --suite preparation --provider configured --baseline evals/baselines/preparation_stub_v1.json --output .dist/evaluations/preparation-live.json
```

准备材料评测使用独立规则版本 `preparation-quality-v1` 和基线；样例及基线在调用前校验，检查结果、失败指标、模型环境与耗时写入报告，正文与回答不进入报告。回归检查原先通过的检查是否失败。该套件没有 JD 参考分，`--max-score-drop` 仅影响默认简历套件；准备材料采用布尔门禁。

## 样例维护规则

新增样例前，应先删除姓名、联系方式、真实公司、精确日期及其他可识别信息，用合成事实替换，并人工核对事实与断言。不要自动从用户任务或反馈中导入资料。

修改样例后更新数据集版本并重建基线；修改评测规则后更新 `EVALUATION_VERSION`。模型或提示词调整应使用相同评测集与规则进行对照，保留两份报告，并人工复核真实性和表达质量。四个样例只提供初始回归覆盖，尚不足以证明各类岗位的生成效果。

## 实测记录

[2026-10-15 真实模型验证](reports/2026-10-15.md) 保留配置模型不可用、两次真实模型质量回归及引用修复后的 stub 报告。真实模型两轮均未完整通过；修复后因额度不足未执行真实模型复测，这些失败记录不能作为发布通过基线。

[2026-10-15 DeepSeek 切换与复测](reports/2026-10-15-deepseek-flash.md)：按用户选择切换到官方 `deepseek-flash` 后，在引用修复代码上完成严格模式真实模型回归，4/4 样例通过，与已有 stub 基线相比 0 回退。该次结果不改变前面 Qwen 失败记录，也不替代更广的岗位与材料质量验证。

[2026-10-15 准备材料真实模型验收](reports/2026-10-15-deepseek-preparation.md)：DeepSeek 的中英文材料包与八个面试场景合计 10/10 样例、146 个检查通过，0 基线回退；已说明生产规则保护范围和未覆盖场景。
