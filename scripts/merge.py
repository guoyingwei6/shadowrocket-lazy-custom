#!/usr/bin/env python3
"""
Merge upstream Shadowrocket lazy_group.conf with custom overrides.

- Downloads upstream config from LOWERTOP/Shadowrocket
- Applies key-value overrides from custom/general.conf to [General]
  (use '__DELETE__' as value to remove a key entirely from upstream)
- Splits custom/rules.conf at '# --- pre-final ---':
    - Rules ABOVE the marker → inserted at the very top of [Rule],
      before all upstream service rules (ensures advertising REJECT /
      .cn direct / Scholar direct match first)
    - Rules BELOW the marker → inserted immediately before FINAL
  If the marker is absent, all rules are treated as pre-final (backwards compatible).
- Appends custom URL rewrites from custom/url_rewrite.conf to [URL Rewrite]
  (file is silently skipped when it contains only comments or whitespace)
- Removes proxy groups listed in custom/remove_groups.conf and their associated rules
"""

import re
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

UPSTREAM_URL = (
    "https://raw.githubusercontent.com/LOWERTOP/Shadowrocket/main/lazy_group.conf"
)

ROOT = Path(__file__).resolve().parent.parent
CUSTOM_DIR = ROOT / "custom"
OUTPUT = ROOT / "lazy_group_custom.conf"

# Sentinel value in general.conf: removes the key from upstream entirely.
# Example: fallback-dns-server = __DELETE__
_GENERAL_DELETE = "__DELETE__"

# Divider in rules.conf separating top-inserted rules from pre-FINAL rules.
_RULES_SPLIT_MARKER = "# --- pre-final ---"


def download_upstream() -> str:
    with urllib.request.urlopen(UPSTREAM_URL) as resp:
        return resp.read().decode("utf-8")


def parse_sections(text: str) -> list[tuple[str, str]]:
    """Parse config into [(section_name, section_body), ...].

    Content before the first section header is stored with section_name=''.
    """
    sections: list[tuple[str, str]] = []
    current_name = ""
    current_lines: list[str] = []

    for line in text.splitlines(keepends=True):
        m = re.match(r"^\[(.+)\]\s*$", line)
        if m:
            sections.append((current_name, "".join(current_lines)))
            current_name = m.group(1)
            current_lines = [line]
        else:
            current_lines.append(line)

    sections.append((current_name, "".join(current_lines)))
    return sections


def load_custom(filename: str) -> str:
    path = CUSTOM_DIR / filename
    if not path.exists():
        return ""
    return path.read_text("utf-8").strip()


def apply_general_overrides(body: str) -> str:
    """Override key=value pairs in [General] section.

    Keys whose value is '__DELETE__' are removed from the upstream config
    entirely, allowing deletion of keys that have no neutral override value
    (e.g. fallback-dns-server cannot be "disabled" by setting a value —
    it must be absent from the config).
    """
    overrides_text = load_custom("general.conf")
    if not overrides_text:
        return body

    overrides: dict[str, str] = {}
    for line in overrides_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            overrides[key.strip()] = val.strip()

    if not overrides:
        return body

    result_lines = []
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in overrides:
                val = overrides.pop(key)
                if val == _GENERAL_DELETE:
                    # Drop this upstream key entirely
                    continue
                result_lines.append(f"{key} = {val}\n")
                continue
        result_lines.append(line)

    # Append overrides that had no matching upstream key (skip __DELETE__ entries)
    for key, val in overrides.items():
        if val != _GENERAL_DELETE:
            result_lines.append(f"{key} = {val}\n")

    return "".join(result_lines)


def load_rules_conf() -> tuple[str, str]:
    """Load rules.conf and split into (top_rules, prefinal_rules).

    Rules above '# --- pre-final ---' are inserted at the top of [Rule],
    before all upstream service rules, so they are evaluated first.
    Rules below the marker are inserted immediately before FINAL.
    Without the marker, all rules go before FINAL (backwards compatible).
    """
    text = load_custom("rules.conf")
    if not text:
        return "", ""
    if _RULES_SPLIT_MARKER in text:
        idx = text.index(_RULES_SPLIT_MARKER)
        top = text[:idx].strip()
        prefinal = text[idx + len(_RULES_SPLIT_MARKER):].strip()
        return top, prefinal
    return "", text


def insert_rules_at_top(body: str, top_rules: str) -> str:
    """Insert rules at the very top of [Rule] section, right after its header line.

    Guarantees top_rules are evaluated before any upstream service rules.
    Intended for: advertising REJECT, Scholar DIRECT, .cn DIRECT.
    """
    if not top_rules:
        return body
    lines = body.splitlines(keepends=True)
    result = []
    inserted = False
    for line in lines:
        result.append(line)
        if not inserted and re.match(r"^\[Rule\]$", line.strip()):
            result.append("\n# --- Top Custom Rules ---\n")
            result.append(top_rules + "\n")
            result.append("\n")
            inserted = True
    return "".join(result)


def insert_rules_before_final(body: str, custom_rules: str) -> str:
    """Insert custom rules immediately before the FINAL line in [Rule] section."""
    if not custom_rules:
        return body

    lines = body.splitlines(keepends=True)
    result = []
    inserted = False

    for line in lines:
        if not inserted and line.strip().startswith("FINAL,"):
            result.append("\n# --- Custom Rules ---\n")
            result.append(custom_rules + "\n")
            result.append("\n")
            inserted = True
        result.append(line)

    if not inserted:
        # No FINAL found, append at end
        result.append("\n# --- Custom Rules ---\n")
        result.append(custom_rules + "\n")

    return "".join(result)


def load_remove_groups() -> set[str]:
    """Load group names to remove (case-insensitive)."""
    text = load_custom("remove_groups.conf")
    if not text:
        return set()
    groups = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            groups.add(line.lower())
    return groups


def remove_proxy_groups(body: str, groups: set[str]) -> str:
    """Remove specified proxy group definitions from [Proxy Group] section."""
    if not groups:
        return body
    lines = body.splitlines(keepends=True)
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and " = " in stripped:
            name = stripped.split(" = ", 1)[0].strip()
            if name.lower() in groups:
                continue
        result.append(line)
    return "".join(result)


def remove_rules_for_groups(body: str, groups: set[str]) -> str:
    """Remove rule lines whose policy references a removed group.

    Note: matching rules are deleted, not redirected to PROXY.
    Unmatched traffic falls through to Global / China / FINAL.
    """
    if not groups:
        return body
    lines = body.splitlines(keepends=True)
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            parts = stripped.split(",")
            if len(parts) >= 2:
                policy = parts[-1].strip()
                if policy.lower() in groups:
                    continue
        result.append(line)
    return "".join(result)


def append_url_rewrites(body: str) -> str:
    """Append custom URL rewrite rules to [URL Rewrite] section.

    Silently skips the file when it contains only comments or blank lines,
    avoiding an empty placeholder block in the generated config.
    """
    raw = load_custom("url_rewrite.conf")
    if not raw:
        return body
    # Only append if at least one real (non-comment, non-blank) line exists
    has_content = any(
        line.strip() and not line.strip().startswith("#")
        for line in raw.splitlines()
    )
    if not has_content:
        return body
    return body.rstrip("\n") + "\n\n# --- Custom URL Rewrites ---\n" + raw + "\n"


def make_header() -> str:
    template = (CUSTOM_DIR / "header.conf").read_text("utf-8")
    beijing = timezone(timedelta(hours=8))
    date = datetime.now(beijing).strftime("%Y-%m-%d")
    return template.format(date=date)


def merge() -> str:
    upstream = download_upstream()
    sections = parse_sections(upstream)
    remove_groups = load_remove_groups()
    top_rules, prefinal_rules = load_rules_conf()

    result_sections = []
    for name, body in sections:
        if name == "General":
            body = apply_general_overrides(body)
        elif name == "Proxy Group":
            body = remove_proxy_groups(body, remove_groups)
        elif name == "Rule":
            body = remove_rules_for_groups(body, remove_groups)
            body = insert_rules_at_top(body, top_rules)
            body = insert_rules_before_final(body, prefinal_rules)
        elif name == "URL Rewrite":
            body = append_url_rewrites(body)
        result_sections.append(body)

    return make_header() + "\n" + "".join(result_sections)


def main():
    merged = merge()
    OUTPUT.write_text(merged, encoding="utf-8")
    print(f"Merged config written to {OUTPUT}")


if __name__ == "__main__":
    main()
