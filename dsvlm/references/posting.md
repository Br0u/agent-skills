# 接口提交和鉴权

本文件只记录 `scripts/post_theme_config.py` 的提交链路、`.env` 配置和鉴权规则。算法编排规则仍以 `SKILL.md` 为准。

## 基本原则

- `.env` 放在当前安装的 `dsvlm` 技能目录下，用于本地鉴权和请求头；不要写进 `SKILL.md`。
- 默认先 dry-run 或用 `--theme-data-page` 验证链路。
- 真实写入必须由用户明确授权；`--agent-output` 模式下以原始 `--user-request` 里的独立 `--post` 为准。
- 默认 post 必须使用 `--agent-output -` 从 stdin 读取 agent 刚生成的最终表格；只有特别要求调试、复现或留档时才读 `output.txt`。
- `success: true` 且 `status` 为 `POST_SUCCEEDED_DO_NOT_RETRY` 或 `ALREADY_EXISTS_DO_NOT_RETRY` 时，任务已完成，停止重试。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `open scripts/configure_env_from_curl.command` | 弹出新窗口，粘贴三段 cURL 自动配置 `.env` |
| `python3 scripts/post_theme_config.py --auto-login` | 验证主平台跳转链路 |
| `python3 scripts/post_theme_config.py --refresh-auth` | 强制刷新 `DSVLM_ACCESS_TOKEN` |
| `python3 scripts/post_theme_config.py --theme-data-page` | 只读算法列表；优先复用现有 token，失败才刷新 |
| `printf '%s\n' "$AGENT_OUTPUT" \| python3 scripts/post_theme_config.py --agent-output - --user-request '/dsvlm 场景：识别垃圾车 --垃圾车识别 --post'` | 用 stdin 提交 agent 刚生成的表格 |

## 登录和 token

- `--auto-login` 调主平台 `DSVLM_PORTAL_AUTO_LOGIN_URL`，用于确认能拿到 61.172 跳转地址。
- `--refresh-auth` 调 `/s/sys/auth/login`，把返回的 `access_token` 写入 `DSVLM_ACCESS_TOKEN`。
- `/dsvlm --config` 是 agent 入口：打开 `scripts/configure_env_from_curl.command`，让用户粘贴 `auto-login-url`、`login`、`theme data page` 三段 cURL，自动写当前安装目录里的 `dsvlm/.env`。
- `--theme-data-page` 和真实 post 会先用当前 `DSVLM_ACCESS_TOKEN` 探活；token 缺失或探活失败时才刷新一次。
- `/s/theme/*` 的 `Authorization` 不是固定值；脚本用 `DSVLM_DYNAMIC_AUTH=true` 按前端规则生成：`04 + SM2(access_token + 当前毫秒时间戳)`。
- 如果不使用动态鉴权，需要在 `.env` 中显式设置 `DSVLM_AUTHORIZATION`。

## 主题和请求

- `--theme-data-page` 只读当前主题算法列表。
- `DSVLM_THEME_TYPE_ID` 对应主题，例如 `wbr`。
- 请求头、接口地址和超时时间优先从 `.env` 读取；没有配置时脚本使用内置默认值。
