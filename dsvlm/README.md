# dsvlm

华鲲元启视频算法编排 skill。用于把自然语言场景需求转换成平台 `视频解析 -> 策略中心 -> 算法配置` 可填写的算法表格，并在明确授权时提交到平台。

## 目录

```text
dsvlm/
├── SKILL.md                         # Codex/Agent 实际读取的 skill 入口
├── README.md                        # 给人看的说明
├── references/
│   ├── platform-components.md       # 组件、字段、parsingId、解析模式
│   ├── orchestration-patterns.md    # 常见编排套路
│   ├── examples.md                  # 真实配置案例
│   ├── loop-strategy.md             # loop 场景探索和方案评审策略
│   └── posting.md                   # 提交、鉴权、.env 说明
└── scripts/
    ├── configure_env_from_curl.command # 弹窗配置 .env
    ├── setup_env_from_curl.py       # 从三段 cURL 生成 .env
    └── post_theme_config.py         # dry-run / post 平台接口脚本
```

## 快速入口

| 请求 | 行为 |
| --- | --- |
| `/dsvlm --config` | 弹出终端窗口，粘贴三段 cURL 自动配置 `.env` |
| `/dsvlm 场景：人员落水 --loop` | 场景探索和方案评审，只输出不提交 |
| `/dsvlm 场景：人员落水 --loop 6 --save` | loop 6 轮并保存为 Markdown，无新增会提前停止 |
| `/dsvlm 场景：识别垃圾车 --垃圾车识别` | 只生成配置，不提交 |
| `/dsvlm 场景：识别垃圾车 --垃圾车识别 --d:只识别正在作业的垃圾车` | 带补充描述生成配置，不提交 |
| `/dsvlm 场景：识别垃圾车 --垃圾车识别 --post` | 明确提交 |
| `/dsvlm 场景：识别垃圾车 --垃圾车识别 --post --d:只识别正在作业的垃圾车` | 带补充描述提交 |
| `/dsvlm --识别火情 --update --灯光总是误测为火情，需要优化` | 读取现有算法并给出优化后的替换方案 |
| `/dsvlm --识别火情 --update --灯光误报 --d:排除稳定灯光和车灯` | 带补充描述给出优化方案 |
| `/dsvlm --识别火情 --update --灯光总是误测为火情，需要优化 --post` | 读取详情，优化后修改保存原算法 |
| `/dsvlm --识别火情 --update --灯光误报 --post --d:排除稳定灯光和车灯` | 带补充描述修改已有算法 |

`--post` 必须是用户原始请求里的独立片段。Agent 自己补 `--post` 不算授权。
`--d:` 只是详细描述或补充，推荐放全文最后；需要提交时写 `--post --d:...`。
`--loop` 永远不上传；默认 2 轮，不设硬性最大轮数；只有带 `--save` 才保存到 `loop_outputs/`，无新增会提前停止。

## 规则入口

| 文件 | 用途 |
| --- | --- |
| `SKILL.md` | Agent 读取的主规则，包含入口、安全边界、输出格式和提交约束 |
| `references/platform-components.md` | 组件、字段、parsingId、解析模式 |
| `references/orchestration-patterns.md` | 常见场景拆解套路 |
| `references/examples.md` | 历史实测案例 |
| `references/loop-strategy.md` | 场景探索和方案评审策略 |
| `references/posting.md` | 提交、鉴权、`.env` 说明 |
| `scripts/post_theme_config.py` | dry-run / post 平台接口 |
| `scripts/configure_env_from_curl.command` | 弹窗配置 `.env` |
| `scripts/setup_env_from_curl.py` | 从三段 cURL 生成 `.env` |

## 输出格式

Skill 默认生成 Markdown 表格：

```markdown
| 字段 | 内容 |
| --- | --- |
| 算法 | 垃圾车识别 |
| 解析模式 | 通用模式 |
| 预警等级 | 二级预警 |
| 启用区域框 | 开 |
| 排序 | 自动 |
| 思维条件1 | 目标理解 / 多模态目标理解 / garbage truck / 大于 / 0 / 阈值 60 |
| 备注 | ... |
```

提交成功后才追加提交结果表。

## 提交流程

脚本支持三种输入。默认 post 必须用 stdin：

| 输入 | 用途 |
| --- | --- |
| `--agent-output -` | 默认方式，读 stdin，适合自动化和并发 |
| `--agent-output output.txt` | 只在特别要求调试、复现、留档时使用 |
| `--config payload.json` | 读 JSON |

Agent 提交时直接把刚生成的最终表格传给 stdin，不要先写 `output.txt`：

```bash
printf '%s\n' '算法: 垃圾车识别
解析模式: 通用模式
预警等级: 二级预警
启用区域框: 开
排序: 自动
思维条件1: 目标理解 / 多模态目标理解 / garbage truck / 大于 / 0 / 阈值 60
备注: 自动解析测试' \
| python3 scripts/post_theme_config.py \
  --agent-output - \
  --user-request '/dsvlm 场景：识别垃圾车 --垃圾车识别 --post'
```

`output.txt` 只是调试用中转文件，不是 agent 回复的自动存储位置；除非特别要求，不要作为 post 主流程。

## 关键规则

- 默认解析模式用 `通用模式`。
- 具体物体用 `目标理解`；动作、状态、关系用 `内容理解` 或 `深度内容理解`。
- 只有 `目标理解 / 通用目标理解` 和 `目标理解 / 多模态目标理解` 会给检测物体套框。
- 多条件默认按 AND 执行；只有任一独立分支成立就预警时才加 `逻辑理解 / 或者`。
- `逻辑理解 / 或者` 按编程语言 `||` 理解：它分隔完整条件分支，公共前提和公共排除项必须在每个分支重复。
- `目标理解` 最后的数字是置信度，不是目标数量。
- `启用区域框` 是只检测画面指定区域，不是全画幅。
- 反向思维主要用于调试误报，不要默认添加。

## 鉴权

本地鉴权配置放在 `.env`，不要写进文档或提交记录。动态鉴权说明见 `references/posting.md`。

配置入口：

```bash
open scripts/configure_env_from_curl.command
```

`--theme-data-page` 和真实 post 会优先复用现有 token，探活失败才刷新一次；通常不用手动跑 `--refresh-auth`。

常用检查：

| 命令 | 用途 |
| --- | --- |
| `python3 scripts/post_theme_config.py --self-test` | 本地解析自检，不访问平台 |
| `python3 scripts/post_theme_config.py --theme-data-page` | 读取当前主题算法列表 |
| `python3 scripts/post_theme_config.py --theme-data-page --theme-label '识别火情'` | 按算法名读取现有配置，用于 update 优化 |
| `python3 scripts/post_theme_config.py --theme-data-detail '算法id'` | 按 id 读取单条算法详情，用于 update 保存前合并原配置 |

update 模式不加 `--post` 只输出；加 `--post` 时脚本会查同名算法、读取旧详情、合并修改后用 `PUT /s/theme/data` 保存，避免新建同名算法。

## 注意

- `SKILL.md` 是唯一正式 skill 入口。
- 不要保存 Authorization、Cookie、access token 到 README 或 references。
- 并发 post 时避免共享 `output.txt`；排序自动递增可能仍有竞态，必要时显式指定排序。

## 更新日志

### 2026-07-01

- 重大修复 `逻辑理解 / 或者` 语义：按 C++/编程语言 `||` 理解，OR 会把上下条件拆成独立分支。
- 明确 OR 分支必须完整展开：公共目标、区域、正向证据、反向排除项不会自动跨分支继承，需要在每个分支重复。
- 补充人员临水风险示例，说明正确写法是 `(A && B && C && !D) || (A && B && F && !D)`，不是 `A && B && (C || F) && !D` 的隐式写法。

### 2026-06-30

- 新增 `/dsvlm 场景：... --loop` 模式，用于场景探索和现有方案评审，不触发上传。
- 将详细 loop 方法拆到 `references/loop-strategy.md`，`SKILL.md` 只保留入口和路由。
- loop 同时支持 `探索模式` 和 `评审模式`：既能扩展模糊场景，也能检查方案完整性、误报/漏报风险、组件合理性和提交就绪度。
- 默认 loop 2 轮；支持 `--loop N`；不设硬性最大轮数，但无新增、重复或主要变成不可验证假设时提前停止。
- 新增 `--save`：只有显式使用时才把 loop 分析保存到 `loop_outputs/`。

### 2026-06-29

- 将 `dsvlm/` 作为独立 skill 包发布到 `Br0u/agent-skills`，仓库根目录即 `dsvlm/`，不再套 `skills/dsvlm/`。
- 发布包排除 `.env`、`output.txt`、`.vscode`、`__pycache__` 等本机状态和敏感文件。
- 明确安装命令形态：`npx skills add Br0u/agent-skills@dsvlm --dir /Users/brou/.codex/skills -a codex -y --copy`。
- 明确鉴权配置写入当前安装的 `dsvlm/.env`；代码已经按 skill 目录相对定位，不需要写死机器路径。

### 2026-06-26

- 标准化输出为 Markdown 表格；只有真实 `--post` 请求并实际提交后，才追加提交结果表。
- 修复新算法排序：用户未显式指定排序时，脚本读取现有算法列表并使用 `max(sort) + 1`；读取失败时停止，不再静默落到 `1`。
- `post_theme_config.py` 支持解析 Markdown 表格和普通 `字段: 值` 两种 agent 输出。
- 明确默认实时提交走 stdin：`--agent-output -`；`output.txt` 只作为调试/复现中转，避免读到旧内容。
- 梳理上传链路：`--auto-login`、`--refresh-auth`、`--theme-data-page` 是预检/读路径；`--agent-output` 只在原始 `--user-request` 含独立 `--post` 时写入；`--config payload.json --post` 是直接 JSON 提交路径。
- 加强动态鉴权说明：`/s/theme/*` 请求使用 `access_token + 当前毫秒时间戳` 生成 Authorization，并复用同一时间戳参数。
- 对齐平台实测 `parsingId`：`counter`、`dmt_counter`、`ocr`、`logic_or`、`1`、`2`、`11`、`21`、`101`、`102`、`103`、`104`、`121`、`122` 等只保留有证据的映射。
- 明确 `目标理解` 数字语义偏置信度/阈值，不是目标数量；只有目标理解类组件负责套框。
- 新增/强化生成前自检、组件快速决策、token 复用说明；示例按 `推荐初版` 和 `历史实测案例` 标注，避免把历史复杂配置当默认模板。
- 移除未实现的 `结果回流` 文档，不在 README 或 skill 中宣传未落地行为。

### 2026-06-24

- 校验工作区 `skills/dsvlm` 与全局安装 `/Users/brou/.agents/skills/dsvlm` 已同步；无差异时不做无意义重写。
- 固化默认建模偏好：初版优先 `通用模式`、2-4 条稳定可见主证据、正向证据优先；反向思维主要用于调试误报。

### 2026-06-23

- 初始建立视频算法编排 skill：把自然语言场景映射到华鲲元启 `视频解析 -> 策略中心 -> 算法配置` 的固定字段和 `思维条件` 行。
- 从 `video-algorithm-orchestration` 演进并重命名为 `dsvlm`，同时维护工作区和全局安装两份。
- 固化核心模块边界：`内容理解`、`深度内容理解`、`目标理解`、`文字理解`、`逻辑理解`、`全结构化理解`。
- 增加 `人贴小广告/乱贴小广告` 编排经验：抽象行为要拆成“人 + 物料/工具 + 固定表面接触 + 张贴/按压/固定动作 + 排除项”，不要只写抽象标签。
- 明确多条件默认 AND，但 `逻辑理解 / 或者` 在真实替代分支场景中仍然有效，不能误写成“永远不加或者”。
