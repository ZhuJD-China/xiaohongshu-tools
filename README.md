# xiaohongshu-tools

小红书 Web API 的 Python 封装。签名**纯本地计算**，不需要浏览器、不需要 CDP、不需要逆向注入。

- 签名引擎：**内置 `xhs/engine`，完全自主可控**，不依赖任何外部签名库
- Cookie：单独存放在 `cookies.json`（已 gitignore，不会被提交）
- 接口：搜索 / 笔记详情 / 用户笔记 / 登录态检查

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

依赖仅 `pycryptodome` 与 `requests`，两者均为 PyPI 常规包。

## 配置 Cookie

```bash
cp cookies.example.json cookies.json
```

浏览器登录 <https://www.xiaohongshu.com/> → F12 → Application → Cookies，至少填两项：

| 字段 | 说明 |
|---|---|
| `a1` | 设备标识，签名必需 |
| `web_session` | 登录态，约 7 天过期 |

`cookies.json` 已在 `.gitignore` 中，**不要提交**。

## 使用

### Python

```python
from xhs import XHSApi

api = XHSApi()                       # 读取 ./cookies.json

# 登录态是否有效
print(api.status())                  # {'ok': True, 'code': 0, 'msg': '成功'}

# 搜索（page_size 只能是 10 或 20）
r = api.search_notes("opencode", page=1, page_size=20)
for it in r["items"]:
    print(it["liked_count"], it["title"], it["author"])

# 笔记详情 —— xsec_token 必须从搜索结果里带过来
first = r["items"][0]
note = api.get_note(first["id"], xsec_token=first["xsec_token"])
print(note["note"]["title"], note["note"]["comment_count"], note["note"]["tags"])

# 用户笔记（cursor 翻页）
posts = api.user_notes("5ff000000000000000000000", cursor="")
print(posts["next_cursor"], len(posts["items"]))
```

### CLI

```bash
python -m xhs.cli status
python -m xhs.cli search "opencode" --page-size 20 --json
python -m xhs.cli note <note_id> --xsec-token <token>
python -m xhs.cli user-notes <user_id>
python -m xhs.cli cookies          # 只看状态，不打印 cookie 值
```

## 接口状态

| 名称 | 方法 | 路径 | 状态 |
|---|---|---|---|
| `search_notes` | POST | `so.xiaohongshu.com/api/sns/web/v2/search/notes` | ✅ 已实测 |
| `note_feed` | POST | `edith.xiaohongshu.com/api/sns/web/v1/feed` | ✅ 已实测 |
| `user_posted` | GET | `edith.xiaohongshu.com/api/sns/web/v1/user_posted` | ✅ 已实测 |
| `comment_page` | GET | `.../v2/comment/page` | ⚠️ 未验证 |
| `search_user` / `search_topic` | POST | `so.../v1/search/...` | ⚠️ 未验证 |
| `home_feed` | POST | `.../v1/homefeed` | ⚠️ 未验证 |

未验证的接口**默认拒绝调用**，需显式 `XHSClient(allow_unverified=True)`。这样可以避免「路径写错了但看起来像能用」。

## 实测踩到的坑

这些坑在封装层已经挡掉了，但值得知道：

1. **`page_size` 只接受 `10` 和 `20`**
   传 3/5/25/30/50 会返回 `success: true` + **0 条数据 + `has_more: false`** —— 不报错，极易误判成"没有搜索结果"。`search_notes()` 会直接抛 `ValueError`。

2. **搜索接口的域名和版本容易搞错**
   正确的是 `so.xiaohongshu.com/api/sns/web/v2/search/notes`（POST）。
   `edith.xiaohongshu.com/api/sns/web/v1/search/notes` 会返回 **404**。

3. **`page_size=20` 实际返回 22 条**
   服务端会多给 1~2 条（含推广位），别拿返回条数当翻页依据，用 `has_more`。

4. **`/feed` 的响应结构**
   数据在 `items[0].note_card`，不是 `items[0][model_type]`。
   找不到笔记时返回 `items: []` 且 `success: true`，不是报错。

5. **`xsec_token` 必须带**
   搜索结果里的 `xsec_token` 要透传给 `get_note`，否则拿不到数据。

6. **`x-s` 每次都不一样**
   签名内含随机填充序列，这是正常的（不是 bug）。固定 `timestamp` 时 `x-t` 和签名前缀稳定，尾部随机。

## 测试

```bash
# 离线测试（无网络、不需要 cookie）
pytest tests/ -q
```

34 个用例覆盖：端点配置、签名头完整性、`page_size`/`sort` 参数守卫、响应结构归一化、cookie 读写与「不泄露凭据」断言。

## 安全说明

- `cookies.json` 已 gitignore，模板用 `cookies.example.json`
- 任何日志/输出都**不打印 cookie 值**（`summarize()` 只给长度和前缀）
- 本项目为只读接口封装，不含批量抓取、点赞、评论等写操作
- 使用请遵守小红书用户协议，控制频率，仅用于个人学习研究

## License

本仓库代码见仓库所有者；组件许可文本见 [LICENSES/](LICENSES/)。
