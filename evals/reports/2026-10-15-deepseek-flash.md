# 2026-10-15 DeepSeek 切换与真实模型复测

已按用户选择切换到 DeepSeek 官方接口与 `deepseek-flash`。DeepSeek 密钥只保存在本地配置，不写入报告。接口连通性和 JSON 输出检查通过。

使用原 `resume_quality_v1.json` 的四个合成样例，在严格模式下执行完整投递生成流程，并对照 `evals/baselines/stub_v1.json`，沿用相同质量规则和 2 分分数容差。结果为 **4/4 通过、0 回退**。

| 样例 | 结果 | JD 匹配参考分 | 事实引用覆盖 | 规则真实性风险 | 耗时 |
| --- | --- | --- | --- | --- | --- |
| campus-data-zh | 通过 | 96 | 100% | low | 12.5 秒 |
| intern-backend-zh | 通过 | 96 | 100% | low | 12.8 秒 |
| experienced-data-en | 通过 | 67 | 100% | medium | 17.7 秒 |
| campus-backend-en | 通过 | 71 | 100% | low | 12.6 秒 |

全部样例保留要求的已确认技能，未出现规则审查的无引用条目或样例明确禁止的表述。英文社招样例的资历表达等风险仍以报告中的规则提示为准；通过门禁不等于事实认证。

本轮验证在引用清洗、排序与模块回退修复之后执行，补上了之前受模型额度限制未能执行的真实模型回归。此前 Qwen 的失败记录保留，结果不能跨模型视为完全等价。

机器可读结果见 [DeepSeek 评测报告](2026-10-15-deepseek-flash.json)，包含模型、提示词、生成流程摘要、指标和耗时，不含简历正文、接口地址或密钥。

## 复现

在 `.env` 配置好 DeepSeek 模型及密钥后执行：

```bash
python scripts/evaluate_quality.py --provider configured --baseline evals/baselines/stub_v1.json --output .dist/evaluations/deepseek-flash-current.json
```

这是一次四个短合成样例的回归验证，不代表所有岗位、复杂简历、求职材料包或模拟面试均完成真实模型验收，也不代表招聘通过概率。
