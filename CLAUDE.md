# 项目约定

## 架构

- `scripts/merge.py` — 合并脚本，从上游拉取配置 + 合并 `custom/` 目录下的自定义内容
- `custom/` — 所有自定义内容，修改后 push 会触发 CI 自动重新合并
- `.github/workflows/update.yml` — CI 流程，每日北京时间 18:30 自动构建
- `lazy_group_custom.conf` — 最终输出文件（CI 自动生成，不要手动编辑）

## custom/ 目录文件说明

| 文件 | 作用 |
|------|------|
| `header.conf` | 配置文件头部模板（核心特性、更新日志等），支持 `{date}` 占位符自动替换为构建日期 |
| `general.conf` | `[General]` 键值覆盖；值设为 `__DELETE__` 可将该键从上游配置中删除 |
| `rules.conf` | 自定义分流规则；`# --- pre-final ---` 分隔符以上插入 `[Rule]` 最前端，以下插入 FINAL 之前 |
| `url_rewrite.conf` | 额外 URL Rewrite 规则 |
| `remove_groups.conf` | 要移除的策略组（一行一个） |

## 重要注意事项

- **不要直接编辑 `lazy_group_custom.conf`**，它会被 CI 覆盖。所有修改都应在 `custom/` 目录下进行
- **更新文件头**（核心特性、更新日志）只需编辑 `custom/header.conf`，不需要改 `merge.py`
- `merge.py` 不含任何配置内容，只负责合并逻辑
