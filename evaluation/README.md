# Vidferry 效果评测

评测工具用于回答同一批输入下，候选改动相对基线是否提升。它不启动前后端，不访问真实发布账号，也不把 ASR、翻译和 Agent 合成一个总分。

实现、测试、依赖、清单和运行产物统一放在仓库根目录的 `evaluation/` 中。`scripts/evaluate.py` 仅为兼容原命令保留启动入口。

## 目录

- `evaluation/*.py`：评测实现。
- `evaluation/tests/`：不访问外部服务的评测测试。
- `evaluation/manifests/v1/`：60 个 ASR、300 个翻译和 40 个 Agent 标注清单。
- `evaluation/media/`：本地音频，Git 忽略。
- `evaluation/results/`：运行输出、对比报告和人工盲评文件，Git 忽略。

ASR 和翻译清单初始为 `pending`。对应语言评审填写真实参考并把 `status` 改为 `ready`；不得直接把模型输出当作金标。ASR 的 `entities[].text` 是原文关键实体，翻译的 `entities[].target` 是期望中文字幕形式；`type` 使用 `entity`、`number` 或 `negation`，报告会分组统计保留率。

ASR 时间标注格式：

```json
{"text":"reference cue","start":1.2,"end":3.4}
```

翻译上下文中的每一项同时提供源文和冻结初译：

```json
{"source":"previous source","initialTranslation":"上一条初译"}
```

## 量化指标

三个 suite 都记录两类时间：`output.durationMs` 是被测处理链路时间，`wallDurationMs` 是包含评分和结果落盘的评测端到端时间。汇总提供总耗时、平均值、中位数和 P95；`compare` 对同一案例的处理时间做配对 bootstrap，并报告 95% 置信区间。速度只作为独立维度，不改变质量主指标。

- ASR：处理时间、RTF、英语 WER、日语/韩语 CER、实体召回率和时间戳误差。
- 翻译：总处理时间及 Google/LLM 分阶段耗时、Google 初译 chrF++、最终 chrF++、修订增益、实体/数字/否定词保留率，以及完整成功、降级成功和失败比例。
- Agent：处理时间、意图准确率、工具与 Skill 的 precision/recall、参数和工具顺序、流程正确率、任务完成率及状态变化。

翻译结果等级：

- `full_success`：目标字幕非空，要求的 LLM 修订正常完成且没有回退。
- `degraded`：仍有可用字幕，但 LLM 修订关闭、不可用或部分批次回退到 Google 初译。
- `failed`：处理异常或最终字幕为空。

Agent 金标在 `expected` 中使用 `intent`、`requiredTools`、`allowedTools`、可选的 `requiredSkills` / `allowedSkills`、`completion`、`expectedState` 和 `stateChanged`。当前 runner 会优先读取未来意图识别或路由节点的输出；尚未接入该节点时，根据实际安全决策、提案和工具轨迹推导当前意图。

需要验证执行后状态时，使用隔离状态补丁，不访问真实数据库：

```json
{
  "initialState": {"task": {"status": "pending"}},
  "frozenTools": {
    "execute_task": {
      "__result__": {"ok": true},
      "__statePatch__": {"task": {"status": "completed"}}
    }
  },
  "expected": {
    "completion": "state_change",
    "expectedState": {"task": {"status": "completed"}},
    "stateChanged": true
  }
}
```

## 安装

在项目 `vidferry` 环境中安装轻量评测依赖：

```powershell
E:\miniforge3\condabin\conda.bat run -n vidferry python -m pip install -r evaluation/requirements.txt
```

只有运行历史 Whisper 基线时才安装：

```powershell
E:\miniforge3\condabin\conda.bat run -n vidferry python -m pip install -r evaluation/requirements-whisper.txt
```

Whisper 评测按单任务加载模型，因此首版 `rtf` 包含模型加载时间，并在原始输出标记 `rtfIncludesModelLoad=true`。不要把它解释为常驻模型的纯推理吞吐。

## 校验和运行

```powershell
python scripts/evaluate.py validate --suite asr
python scripts/evaluate.py run --suite asr --system faster-whisper --run-id asr-whisper
```

翻译 `--system` 支持：

- `google`：只测 Google 初译。
- `review`：从清单的 `initialTranslation` 开始，只测 LLM 修订增益。
- `google-review`：运行完整初译和修订链路。

Agent 默认每个场景运行三次，工具只能读取清单内的 `frozenTools`。任何未声明工具都会返回显式错误，不连接真实发布平台。

```powershell
python scripts/evaluate.py run --suite translation --system review --run-id translation-baseline
python scripts/evaluate.py run --suite agent --run-id agent-candidate --trials 3
```

中断后使用相同 `run-id` 加 `--resume`；已成功的案例不会重复运行，失败案例会重试。运行中任一案例失败时仍保存 `raw.jsonl` 和 `summary.json`，但命令返回非零且 `complete` 为 `false`。

## 人工盲评

`compare` 生成 `blind_review.jsonl` 和单独的 `blind_key.json`。评审只编辑前者：

- `preference`：`A`、`B` 或 `TIE`。
- `mqmA` / `mqmB`：元素格式为 `{"severity":"critical|major|minor","category":"mistranslation","note":"..."}`。

完成后重新比较并传入标注文件：

```powershell
python scripts/evaluate.py compare --baseline translation-baseline --candidate translation-candidate --output-id translation-reviewed --annotations evaluation/results/compare-translation-baseline--translation-candidate/blind_review.jsonl
```

返回码：`0` 表示运行完整且硬门禁通过，`2` 表示清单或运行不完整，`3` 表示对比硬门禁失败。完整判断以 `report.md` 和失败案例为准，不能只看返回码或单个平均分。
