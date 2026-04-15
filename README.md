# Shadowrocket 懒人分组 · 自定义增强版

基于 [LOWERTOP/Shadowrocket](https://github.com/LOWERTOP/Shadowrocket) 懒人分组配置，通过 GitHub Actions 每日自动拉取上游最新版本并合并自定义规则，自定义内容永不被上游更新覆盖。

**作者：Yingwei Guo ([@guoyingwei6](https://github.com/guoyingwei6))**

## 核心特性

1. **每日自动拉取 LOWERTOP 懒人分组最新配置** — 北京时间 18:30 自动合并自定义规则后发布，无需手动维护
2. **AI 多重规则保障** — 叠加 iab0x00 + blackmatrix7 (OpenAI/Claude/Gemini) 三套 AI 规则集 + 手动域名兜底，确保 AI 流量无遗漏；iab0x00 同时覆盖 Apple Intelligence / Siri / iCloud Private Relay 相关域名
3. **大规模去广告** — blackmatrix7 Advertising 规则集插入到 `[Rule]` 最前端，先于所有服务规则命中，确保广告不被误代理
4. **学术域名直连** — blackmatrix7 Scholar 规则集，覆盖 Nature/IEEE/Springer/Elsevier/JSTOR/Web of Science/Scopus/Z-Library/Zotero 等主流学术平台，保障校园网机构 IP 访问
5. **精简策略组** — 裁剪 YouTube/Netflix/Disney+/Facebook/Amazon 等 8 个低频策略组，保持 UI 清爽，流量仍通过 Global / FINAL 兜底
6. **代理连接 QUIC 屏蔽 + IPv6 关闭** — 仅对走代理的连接屏蔽 QUIC（强制回退 HTTP/2），直连流量可正常使用 HTTP/3；关闭 IPv6 防止泄漏
7. **.cn 域名最前端直连** — 插入 `[Rule]` 最前端，域名层面短路所有 .cn 请求，完全跳过 GEOIP DNS 查询开销
8. **WebRTC 真实 IP 防泄漏** — `stun-response-ip` 返回虚假 IP，防止 WebRTC STUN 绕过代理暴露真实 IP
9. **DNS 防泄漏加固** — 仅使用自建 DoH + Cloudflare；从上游配置中删除 `fallback-dns-server`；禁用系统 DNS 回落与直连 DNS 代理回退

## 订阅地址

| 来源 | 地址 |
|------|------|
| GitHub Raw | `https://raw.githubusercontent.com/guoyingwei6/shadowrocket-lazy-custom/main/lazy_group_custom.conf` |
| GitHub Pages | `https://guoyingwei6.github.io/shadowrocket-lazy-custom/lazy_group_custom.conf` |

在 Shadowrocket 中添加远程配置，粘贴以上任一地址即可。

## 自定义规则

所有自定义内容在 `custom/` 目录下，修改后 push 即自动重新合并：

| 文件 | 作用 |
|------|------|
| `custom/header.conf` | 配置文件头部模板 (核心特性、更新日志，`{date}` 自动替换为构建日期) |
| `custom/general.conf` | `[General]` 键值覆盖 (如 `dns-server`、`fallback-dns-server`) |
| `custom/rules.conf` | 自定义分流规则；`# --- pre-final ---` 分隔符以上插入 `[Rule]` 最前端，以下插入 FINAL 之前 |
| `custom/url_rewrite.conf` | 额外 URL Rewrite 规则 |
| `custom/remove_groups.conf` | 要移除的策略组 (一行一个) |

## 与上游的差异

| 项目 | 上游 (LOWERTOP) | 本配置 |
|------|-----------------|--------|
| IPv6 | `true` | `false` |
| QUIC 屏蔽 | 注释掉 | `block-quic=all-proxy`，仅屏蔽代理连接，直连可用 HTTP/3 |
| 去广告 | 无 | blackmatrix7 Advertising 规则集，插入 `[Rule]` 最前端优先命中 |
| AI 规则 | iab0x00 单一来源 | iab0x00 + blackmatrix7 三套 + 手动兜底（含 Apple Intelligence/Relay）|
| 学术直连 | 无 | blackmatrix7 Scholar 规则集，主流学术平台直连 |
| .cn 直连 | 依赖 GEOIP（需 DNS 查询） | 插入 `[Rule]` 最前端，完全跳过 GEOIP DNS 查询 |
| 低频策略组 | YouTube/Netflix/Facebook/Amazon 等 8 个 | 已裁剪，流量由 Global / FINAL 兜底 |
| WebRTC 防泄漏 | 未启用 | `stun-response-ip` 返回虚假 IP |
| DNS 防泄漏 | 明文回落 | 仅自建 DoH + Cloudflare；删除 `fallback-dns-server`；禁用系统 DNS 回落 |

## 更新日志

| 日期 | 内容 |
|------|------|
| 2026-04-15 | 规则位置修正：广告/学术/.cn 规则移至 `[Rule]` 最前端；修复 `fallback-dns-server = system` 未删除问题（`merge.py` 新增 `__DELETE__` 语义）；清理冗余手写域名（Gmail、Gemini 子域等） |
| 2026-04-10 | DNS 防泄漏加固：移除阿里/腾讯 DoH（出口 IP 走移动骨干被误判为运营商 DNS），去除 fallback（明文被透明代理劫持），仅保留自建 DoH + Cloudflare |
| 2026-04-01 | WebRTC 真实 IP 防泄漏 (`stun-response-ip`)；修正 QUIC 屏蔽范围（仅代理连接，直连保留 HTTP/3）；DNS 安全加固（禁用系统 DNS 回落、直连 DNS 不走代理）|
| 2026-03-22 | 自建 DoH 加密 DNS + 阿里/腾讯明文 DNS 兜底，杜绝运营商 DNS；头部模板提取到 `custom/header.conf` |
| 2026-03-19 | 初始版本：自动合并框架 + AI/学术/去广告规则 + 策略组精简 |

## 致谢

- [LOWERTOP/Shadowrocket](https://github.com/LOWERTOP/Shadowrocket) — 上游懒人分组配置
- [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) — 去广告 + AI + 学术分流规则集
- [iab0x00/ProxyRules](https://github.com/iab0x00/ProxyRules) — AI 规则集
