# xiaohongshu-tools

小红书 Web API 的 Python 封装。签名**纯本地计算**，不需要浏览器、不需要 CDP、不需要逆向注入。

- 签名引擎：**内置 `xhs/engine`，完全自主可控**，不依赖任何外部签名库
- Cookie：单独存放在 `cookies.json`（已 gitignore，不会被提交）
- 接口：搜索 / 笔记详情 / 用户 / 评论（含子评论）/ 登录态，**全部实测通过**

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

# 用户资料与账号
profile = api.user_profile(posts["user_id"])
print(profile["nickname"], profile["red_id"], profile["posted"])
print(api.me()["nickname"])

# 评论 —— xsec_token 必填，缺了服务端回 461/300031
first_note = r["items"][0]
c = api.comments(first_note["id"], xsec_token=first_note["xsec_token"])
for it in c["items"]:
    print(it["author"], it["content"], it["sub_comment_count"])
    if int(it["sub_comment_count"] or 0) > 0:
        subs = api.sub_comments(first_note["id"], it["id"],
                                xsec_token=first_note["xsec_token"],
                                cursor=it["sub_comment_cursor"])
        print("  ", [s["content"] for s in subs["items"]])

# 其余搜索
print([f["name"] for f in api.search_filter("opencode")["items"]])
print([s["text"] for s in api.search_recommend("opencode")["items"]])
print([t["name"] for t in api.search_topics("摄影")["items"]][:5])
print([u["nickname"] for u in api.search_users("摄影")["items"]][:5])
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

全部 **11 个端点均已通过真实 cookie 实测**（`tests/` 里的 51 个用例是离线的，只覆盖构造与归一化，不联网）。

| 方法 | 接口 | 路径 | 签名 | 说明 |
|---|---|---|---|---|
| POST | `search_notes` | `so.xiaohongshu.com/api/sns/web/v2/search/notes` | XYS | 关键词搜笔记。返回标题、作者、点赞数，以及后续所有接口都要用的 `xsec_token` |
| GET | `search_filter` | `edith.../api/sns/web/v1/search/filter` | XYS | 搜索结果页顶部的筛选项：排序依据、笔记类型、发布时间、搜索范围，带服务端分组 id，可回填给 `search_notes` |
| GET | `search_recommend` | `edith.../api/sns/web/v1/search/recommend` | XYS | 输入框的搜索联想词。返回 `code: 1000` 但 `success: true`，1000 是正常的「无精确匹配块」码，不是报错 |
| POST | `search_topic` | `edith.../web_api/sns/v1/search/topic` | XYW(creator) | 搜话题标签，返回话题名、链接、浏览量 |
| POST | `search_user` | `edith.../web_api/sns/v1/search/user_info` | XYW(creator) | 搜用户账号，返回昵称、小红书号、`user_id`、粉丝数，可直接接着调 `user_profile` |
| POST | `note_feed` | `edith.../api/sns/web/v1/feed` | XYS | 单篇笔记详情：正文、标签、点赞/收藏/评论/分享数、IP 属地。找不到笔记时返回空 `items` 而非报错 |
| GET | `user_me` | `edith.../api/sns/web/v2/user/me` | XYS | 当前登录账号是谁。最省的一次登录态探测，`guest: true` 说明 cookie 已被拒 |
| GET | `user_otherinfo` | `edith.../api/sns/web/v1/user/otherinfo` | XYS | 他人主页资料与统计：笔记数、收藏数、获赞数、关注/粉丝/点赞三项互动 |
| GET | `user_posted` | `edith.../api/sns/web/v1/user_posted` | XYS | 某个用户发布的笔记列表，`cursor` 翻页，回传的 `next_cursor` 原样喂下一页 |
| GET | `comment_page` | `edith.../api/sns/web/v2/comment/page` | XYS | 笔记的一级评论，含每条的 `sub_comment_count` 和首屏子回复 |
| GET | `comment_sub_page` | `edith.../api/sns/web/v2/comment/sub/page` | XYS | 某条评论下的完整子回复列表，用 `root_comment_id` 定位、`sub_comment_cursor` 翻页 |

配置表里**只有已验证的端点**：`VERIFIED` 中出现的键即代表实测通过，未通过的一律不收录。查一个不存在的名字会直接抛 `KeyError` 并列出已知键，而不是发出一个没人验证过的请求。

带 body 的两个 POST（`search_notes`、`note_feed`）还会额外发一个 `x-rap-param` 头，把请求体一并打包；漏发它**不报错**，只返回 `200` + `success: false` + 空 `payload`，所以排查"有 200 但没数据"时先看这个头。

### 两种签名：XYS 和 XYW

上面表格 `签名` 列写的 `XYS` / `XYW(creator)`，指的是请求头 `x-s` 的**信封前缀**，不是我们自己起的名字 —— 小红书前端发出来的 `x-s` 就长这样：

```
XYS_2UQ...（自定义字母表 Base64 的一段 JSON）   主站 /api/sns/web/*
XYW_ey... （标准 Base64 的一段 JSON）            创作者 /web_api/*
```

两者外层编码**不一样**：`XYS_` 先标准 Base64 再按自定义字母表换字符（所以解出来第一个字符恒是 `2` 而不是标准表的 `e`），`XYW_` 就是普通 Base64。看第一个字符就能立刻判断这次发的是哪套信封。

- **`XYS_`**：外层是 `{"x0":"4.3.5","x1":"xhs-pc-web","x2":"Windows","x3":"mns0301_...","x4":"object"}`，真正的签名在 `x3` 里 —— 一个 144 字节的结构体，依次塞了版本号、随机种子、毫秒时间戳、`uri+参数` 的 MD5、`a1`、`appId`、环境指纹位，最后整体 XOR 一段固定密钥再按第三套字母表 Base64 编码。
- **`XYW_`**：结构不同，`{"signSvn":"56","signType":"x2","appId":"...","signVersion":"1","payload":"..."}`，`payload` 是 AES-128-CBC 加密的结果，用于创作者侧接口。

两者**不能互换**：`/api/sns/web/*` 只认 `XYS_`，`/web_api/*` 只认 `XYW_`。发错的结果是被拒，而且是两种不同的拒法 —— 主站路径拿到 406，创作者路径用错 appId 会拿到 461/300011「当前账号存在异常」，后者会把整个会话打废，重试救不回来。封装层按端点路径自动选，调用方不用管。

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

7. **GET 的 query 必须自己编码 —— 否则 406**（最坑的一个）
   签名按 `quote(value, safe=",")` 计算，逗号**原样保留**；交给 `requests` 用 `urlencode` 编码会把
   `image_formats=jpg,webp,avif` 变成 `jpg%2Cwebp%2Cavif`，签名与实际 URL 对不上，服务端一律回
   **406**（body 恒为 `{"code":-1}`）。
   `comment_page` 和 `user_posted` 都栽在这里 —— 封装层现在用 `sign.query_url()` 构造 URL，
   与签名逐字节一致。

8. **评论接口缺 `xsec_token` 回 461/300031**
   报错文案是「当前笔记暂时无法浏览」，看着像笔记没了，其实是参数缺失。`comments()` / `sub_comments()`
   把 `xsec_token` 设成必填，缺了直接抛 `ValueError` 而不是发请求。
   `image_formats` 也要一起带。

9. **子评论的参数名是 `root_comment_id`，不是 `top_comment_id`**
   用错会得到 **-9109 参数错误**。翻页用父评论的 `sub_comment_cursor`（不是 data 顶层的 `cursor`）。

10. **`/web_api/*` 搜索的分页是嵌套对象**
    `page` 必须是 `{"page_size": 20, "page": 1}`；拍平成 `{"page": 1, "page_size": 20}` 会
    **400**（`page: required struct with json string format`）。`search_topic` 还要
    `suggest_topic_request`，`search_user` 的 `search_id` 是毫秒时间戳字符串 —— 和笔记搜索的
    18 位随机 `search_id` 不是一回事，不能互换。

11. **POST body 要紧凑 JSON、不转义中文**
    浏览器发的是 `{"keyword":"美食",...}`，`requests` 的 `json=` 会加空格并把中文转成 `\uXXXX`，
    与签名所覆盖的字符串不一致。封装层用 `sign.json_body()` 手动序列化。

12. **两套签名不能互换**
    `/api/sns/web/*` 用 `XYS_`；`/web_api/*` 用 `XYW_`（`appId=ugc`）。
    把引擎的 XYW（`appId=xhs-pc-web`）发给评论接口会触发 **461/300011「当前账号存在异常」**，
    直接把会话打废 —— 这不是重试能恢复的。

## 测试

```bash
# 离线测试（无网络、不需要 cookie）
pytest tests/ -q
```

51 个用例覆盖：端点配置与签名方案匹配、query/body 编码（406 回归）、签名头完整性、`page_size`/`sort`/`xsec_token` 参数守卫、各响应结构归一化、cookie 读写与「不泄露凭据」断言。

## 安全说明

- `cookies.json` 已 gitignore，模板用 `cookies.example.json`
- 任何日志/输出都**不打印 cookie 值**（`summarize()` 只给长度和前缀）
- 本项目为只读接口封装，不含批量抓取、点赞、评论等写操作
- 使用请遵守小红书用户协议，控制频率，仅用于个人学习研究

## License

本仓库代码见仓库所有者；组件许可文本见 [LICENSES/](LICENSES/)。
