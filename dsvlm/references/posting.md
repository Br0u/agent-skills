# 接口提交和鉴权

本文件集中记录 `scripts/post_theme_config.py` 的 8898 提交协议，以及 `scripts/algorithm_service.py` 的 9079 鉴权。算法编排规则仍以 `SKILL.md` 为准。

## 8898 提交边界

- Markdown 表格只用于回复展示，不作为机器输入。
- 提交只接受 `--payload -`，从 stdin 读取一个 JSON 对象；不读取配置文件或输出中转文件。
- 是否写入只取决于原始 `--user-request` 末尾是否有独立 `--post`。没有时始终 dry-run。
- 主题名来自用户的 `主题：...`，去掉首尾空格后按区分大小写的名称精确匹配；不固定为 `wbr`，也没有默认主题 ID。
- 主题缺失、无匹配、同名对应多个 ID或目录鉴权失败时停止。
- 同名查重和自动排序复用一次最多 200 条的主题分页结果。超过该上限的主题需先扩展分页逻辑，不能静默假设完整。
- 新建发现同主题同名算法时返回 `ALREADY_EXISTS_DO_NOT_RETRY`。优化找不到同名算法时停止，不退化成新建。
- 优化只覆盖 JSON 明确提供的字段；`false` 和空字符串是有效显式值，未提供字段保留平台原值。

## 结构化 JSON

支持字段：

| JSON 字段 | 含义 |
| --- | --- |
| `algorithm` | 算法名；原始请求中的 `算法名：...` 优先 |
| `mode` | `通用模式`、`深度解析模式`、`深度串行解析` |
| `level` | `一级预警` 至 `五级预警` |
| `area_flag` | 是否启用区域框，布尔值 |
| `portal_flag` | 是否添加到门户，布尔值 |
| `docking_code` | 对接编码；可显式传空字符串清空 |
| `sort` | 整数或 `auto` |
| `extension_ratio` | 延伸比例 |
| `target_extension_ratio` | 平台自定义目标延伸配置原值 |
| `conditions` | 非空条件字符串数组；目标规则必须显式写 `阈值 N` |
| `remark` | 备注 |

示例：

```bash
printf '%s\n' '{
  "algorithm": "垃圾车识别",
  "mode": "通用模式",
  "level": "二级预警",
  "area_flag": true,
  "portal_flag": false,
  "docking_code": "",
  "sort": "auto",
  "conditions": [
    "目标理解 / 多模态目标理解 / garbage truck / 大于 / 0 / 阈值 60",
    "内容理解 / 正向思维1 / 图中存在正在作业的垃圾车"
  ],
  "remark": "自动解析测试"
}' | python3 scripts/post_theme_config.py --payload - \
  --user-request '/dsvlm 新建：识别垃圾车；算法名：垃圾车识别；主题：园区A --post'
```

常用只读命令：

```bash
python3 scripts/post_theme_config.py --theme-data-page --theme-name '园区A'
python3 scripts/post_theme_config.py --theme-data-detail '算法id'
python3 scripts/post_theme_config.py --refresh-auth
```

## 8898 鉴权

长期配置只有三个键：

- `DSVLM_LOGIN_USERNAME`
- `DSVLM_LOGIN_PASSWORD`
- `DSVLM_ALLOW_INSECURE_HTTP`

`DSVLM_ACCESS_TOKEN` 是脚本登录后写入私有 `.env` 的运行时值，不放进 `.env.example`，也不手工维护。`scripts/configure_env.py` 仅在首次安装、`.env` 丢失或凭据变更时维护前三个键；密码不回显，文件权限为 `0600`。

鉴权流程：

1. 主题目录和详细配置共用 8898 登录，不再经过 8108。
2. 登录端点是 `POST /s/sys/auth/login`。密码按当前前端规则使用 SM2 公钥加密并加 `04` 前缀。
3. 验证码关闭时提交空 `key` 和 `captcha`。登录失败后才读取 `GET /s/sys/auth/captcha/enabled`；若已启用，返回 `CAPTCHA_REQUIRED` 并停止，不尝试绕过。
4. 登录返回的 `access_token` 写入 `DSVLM_ACCESS_TOKEN`。
5. `/s/theme/*` 请求使用 `04 + SM2(access_token + 当前毫秒时间戳)` 生成动态 `Authorization`，并在查询参数中使用同一时间戳。
6. 主题目录为 `GET /s/theme/type/all`；`/#/data-task/task` 只是前端 hash 路由。

8898 当前地址是明文 HTTP。客户端默认拒绝 HTTP 和重定向；只有确认目标主机及当前网络可信后，才在私有 `.env` 设置 `DSVLM_ALLOW_INSECURE_HTTP=true`。`.env.example` 必须保持 `false`。

## 9079 算法服务

9079 使用独立的 `DSVLM_SERVICE_*` 配置，不参与 8898 主题提交：

```bash
python3 scripts/algorithm_service.py --list
python3 scripts/algorithm_service.py --add --name '穿黑衣的人' --text '识别穿黑衣的人' --type 1
```

9079 当前也是明文 HTTP；可信网络下才在私有 `.env` 设置 `DSVLM_SERVICE_ALLOW_INSECURE_HTTP=true`。`type=99` 时 `typeDescription` 必须至少包含一个中文字符。9079 `--add` 没有 `themeTypeId`，不能替代 8898 的主题内上传。
