# 第三方源码声明 / Third-Party Notices

本项目**不依赖任何 GitHub 上的第三方 Python 包**，相关源码直接内嵌在仓库中。

## xhshow

| | |
|---|---|
| 路径 | `xhs/vendor/xhshow/` |
| 来源 | https://github.com/Cloxl/xhshow |
| 协议 | MIT |
| 版权 | Copyright (c) 2024 Cloxl |
| 原始许可证 | `xhs/vendor/xhshow-LICENSE` |
| 修改 | 无（原样拷贝，仅变更存放路径） |

`xhshow` 负责生成小红书的 `x-s` / `x-s-common` / `x-rap-param` 签名头。
它是纯算法实现，不需要浏览器或 CDP。

按 MIT 协议要求，保留上述版权声明与许可文本。若你二次分发本项目，
请一并保留 `xhs/vendor/xhshow-LICENSE`。

## 其他依赖

| 包 | 协议 | 用途 |
|---|---|---|
| `pycryptodome` | BSD-3-Clause | xhshow 的 RC4 加密（`generators/fingerprint.py`） |
| `requests` | Apache-2.0 | HTTP 请求 |

两者均为 PyPI 常规依赖，非本仓库内嵌源码。

## 未内嵌的项目

以下同类项目仅在调研阶段参考，**未引入其任何代码**：

- `jackwener/xiaohongshu-cli` — 未使用
- `ZhuJD-China/xiaohongshu-tools` — 本仓库的空模板，仅含 README
