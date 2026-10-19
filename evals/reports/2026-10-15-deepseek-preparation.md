# 2026-10-15 DeepSeek 求职材料与模拟面试验收

使用已配置的官方 `deepseek-flash`，严格模式执行 [preparation_quality_v1.json](../preparation_quality_v1.json) 的 10 个合成样例。结果为 **10/10 通过、146 个检查通过、0 基线回退**，样例执行总耗时约 38.2 秒。

| 样例 | 类型 | 结果 | 检查数 | 耗时 |
| --- | --- | --- | --- | --- |
| materials-zh | materials | 通过 | 13 | 1.1 秒 |
| materials-en | materials | 通过 | 13 | 1.1 秒 |
| interview-honest-zh | interview | 通过 | 15 | 3.5 秒 |
| interview-inflated-zh | interview | 通过 | 15 | 4.5 秒 |
| interview-negation-zh | interview | 通过 | 15 | 4.6 秒 |
| interview-hypothesis-zh | interview | 通过 | 15 | 5.7 秒 |
| interview-honest-en | interview | 通过 | 15 | 5.0 秒 |
| interview-inflated-en | interview | 通过 | 15 | 5.1 秒 |
| interview-negation-en | interview | 通过 | 15 | 3.9 秒 |
| interview-project-metric-isolation-en | interview | 通过 | 15 | 3.7 秒 |

## 本轮覆盖

材料验收调用生产材料生成、编辑风险检查和导出序列化逻辑，使用中英文已保存简历与 JD 快照。每种语言生成七份材料，检查已确认事实引用、排除未确认经历、项目隔离、自我介绍长度区分、JD 与版本标识、默认未核对状态及手工改动风险。模型负责选择证据与顺序，事实原句和衔接模板由现有实现组合；没有把模板生成描述为模型自由写作。

面试验收调用生产问题构建、模型评估、反馈标准化、追问与报告逻辑，覆盖中英文正常回答、数字及个人职责夸大、未确认技术、否定表达、假设回答，以及挪用其他项目数字。检查回答引用、有效事实 ID、人工指定的风险断言、规则风险保留、建议内容边界、追问次数与原始快照不变。

## 修复与验证

修复模型反馈上限可能挤掉规则事实风险的问题：先保留确定性风险，再加入模型建议并限制展示数量。新增回归用 12 条表达类建议验证数字、职责和技术风险仍然保留。

修正测试凭据隔离：仅删除环境变量会让设置重新读取本地 `.env` 的真实密钥；测试现在通过空环境值覆盖本地凭据。未修改用户密钥。

全量后端测试 **261 项通过**，插件检查 **4 项通过**。准备材料 stub 基线 **10/10**，本轮真实模型对照 **10/10**。本套件使用内存快照，不读取或写入用户任务、档案、材料和面试数据库。

机器可读结果见 [DeepSeek 准备材料报告](2026-10-15-deepseek-preparation.json)，基线见 [preparation_stub_v1.json](../baselines/preparation_stub_v1.json)。报告仅保留检查结果、指标、模型环境和耗时，不保存材料正文、回答、JD、密钥或接口地址。

## 验证边界

检查针对生产规则保护和标准化后的输出，不能据此认为原始模型输出始终正确。正常、否定及假设回答的断言检查是否被误判为事实矛盾，不要求模型完全不提出表达建议或补充核实问题。未评估表达自然度、所有事实的语义真实性或招聘效果。

这是一次针对十个短合成样例的验收，没有重新验证网页交互、数据库授权、多轮完整会话、PDF / DOCX 布局、全部岗位或模型长期稳定性。相关离线回归继续保留，更复杂场景仍需新增样例和人工复核。

## 复现

```bash
python scripts/evaluate_quality.py --suite preparation --provider configured --baseline evals/baselines/preparation_stub_v1.json --output .dist/evaluations/preparation-live.json
```
