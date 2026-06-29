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
| `/dsvlm 场景：识别垃圾车 --垃圾车识别` | 只生成配置，不提交 |
| `/dsvlm 场景：识别垃圾车 --垃圾车识别 --post` | 明确提交 |

`--post` 必须是用户原始请求里的独立片段。Agent 自己补 `--post` 不算授权。

## 规则入口

| 文件 | 用途 |
| --- | --- |
| `SKILL.md` | Agent 读取的主规则，包含入口、安全边界、输出格式和提交约束 |
| `references/platform-components.md` | 组件、字段、parsingId、解析模式 |
| `references/orchestration-patterns.md` | 常见场景拆解套路 |
| `references/examples.md` | 历史实测案例 |
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
- 多条件默认按 AND 执行；只有任一成立就预警时才加 `逻辑理解 / 或者`。
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

## 注意

- `SKILL.md` 是唯一正式 skill 入口。
- 不要保存 Authorization、Cookie、access token 到 README 或 references。
- 并发 post 时避免共享 `output.txt`；排序自动递增可能仍有竞态，必要时显式指定排序。
