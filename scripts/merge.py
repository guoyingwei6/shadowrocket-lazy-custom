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

import os
import re
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

UPSTREAM_URL = (
    "https://raw.githubusercontent.com/LOWERTOP/Shadowrocket/main/lazy_group.conf"
)

ROOT = Path(__file__).resolve().parent.parent
CUSTOM_DIR = ROOT / "custom"
OUTPUT = ROOT / "lazy_group_custom.conf"

# Sections that must exist in the upstream config for a valid merge.
# 'URL Rewrite' is intentionally excluded: it is optional in valid Shadowrocket
# configs and may be absent in future upstream variants. Custom rewrites are
# synthesized as a new section when the upstream section is missing.
_REQUIRED_SECTIONS = {"General", "Proxy Group", "Rule"}

# Sections that the script mutates; duplicate detection covers all of these
# so custom content is never double-inserted.
_MUTATED_SECTIONS = _REQUIRED_SECTIONS | {"URL Rewrite"}

# Built-in Shadowrocket policy names that are not user-created proxy groups.
# remove_groups.conf must not contain these — removing them would silently
# delete large portions of the rule set.
_BUILTIN_POLICIES = {"direct", "proxy", "reject", "final", "mitm"}
_BUILTIN_POLICY_PREFIXES = ("reject-",)  # covers REJECT-TINYGIF, REJECT-DROP, etc.

# Sentinel value in general.conf: removes the key from upstream entirely.
# Example: fallback-dns-server = __DELETE__
_GENERAL_DELETE = "__DELETE__"

# Divider in rules.conf separating top-inserted rules from pre-FINAL rules.
# Must appear as an exact standalone line (not inside a comment).
_RULES_SPLIT_MARKER = "# --- pre-final ---"

# Trailing rule options that are not the policy name.
# Update this set if Shadowrocket introduces new trailing options.
_RULE_OPTIONS = {"no-resolve", "pre-matching", "extended-matching"}

# Valid section header: "[Name]" or "[ Name ]", but not "[[Name]]".
_SECTION_RE = re.compile(r"^\[([^\[\]]+)\]\s*$")


def download_upstream() -> str:
    """Download upstream config with a 30-second timeout and clear error messages."""
    try:
        with urllib.request.urlopen(UPSTREAM_URL, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[merge] HTTP {e.code} downloading upstream: {e.reason}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"[merge] Network error downloading upstream: {e.reason}") from e
    try:
        # utf-8-sig strips a leading BOM if present
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise SystemExit(f"[merge] Upstream response is not valid UTF-8: {e}") from e


def parse_sections(text: str) -> list[tuple[str, str]]:
    """Parse config into [(section_name, section_body), ...].

    Content before the first section header is stored with section_name=''.
    Section names are stripped to tolerate minor upstream formatting differences.
    '[[Rule]]'-style double brackets are rejected by _SECTION_RE.
    BOM at the very start is handled upstream via utf-8-sig decoding.
    """
    sections: list[tuple[str, str]] = []
    current_name = ""
    current_lines: list[str] = []

    # Strip BOM defensively; download_upstream uses utf-8-sig but guard here too
    text = text.lstrip("\ufeff")

    for line in text.splitlines(keepends=True):
        m = _SECTION_RE.match(line)
        if m:
            sections.append((current_name, "".join(current_lines)))
            current_name = m.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    sections.append((current_name, "".join(current_lines)))
    return sections


def validate_sections(sections: list[tuple[str, str]]) -> None:
    """Raise SystemExit if any required section is missing or duplicated."""
    names = [name for name, _ in sections if name]
    present = set(names)

    missing = _REQUIRED_SECTIONS - present
    if missing:
        raise SystemExit(
            f"[merge] Upstream config is missing required sections: "
            f"{', '.join(sorted(missing))}. Aborting to avoid a broken output."
        )

    # Duplicate mutated sections would cause custom content to be inserted twice
    counts = Counter(names)
    duplicates = {name for name, count in counts.items() if count > 1} & _MUTATED_SECTIONS
    if duplicates:
        raise SystemExit(
            f"[merge] Upstream config contains duplicate sections: "
            f"{', '.join(sorted(duplicates))}. Aborting to avoid double-inserting custom content."
        )


def load_custom(filename: str) -> str:
    path = CUSTOM_DIR / filename
    if not path.exists():
        return ""
    # utf-8-sig handles BOM in local files too
    return path.read_text("utf-8-sig").strip()


def apply_general_overrides(body: str) -> str:
    """Override key=value pairs in [General] section.

    Keys whose value is '__DELETE__' are removed from the upstream config
    entirely. All occurrences of a key are replaced/removed (not just the
    first), so duplicate upstream keys are handled correctly.
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
    seen_keys: set[str] = set()

    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in overrides:
                seen_keys.add(key)
                val = overrides[key]
                if val == _GENERAL_DELETE:
                    # Remove this key from the upstream config entirely
                    continue
                result_lines.append(f"{key} = {val}\n")
                continue
        result_lines.append(line)

    # Append overrides that had no matching upstream key (skip __DELETE__ entries)
    for key, val in overrides.items():
        if key not in seen_keys and val != _GENERAL_DELETE:
            result_lines.append(f"{key} = {val}\n")

    return "".join(result_lines)


def load_rules_conf() -> tuple[str, str]:
    """Load rules.conf and split into (top_rules, prefinal_rules).

    Splits on the first line whose stripped content is exactly
    '# --- pre-final ---'. A substring match is intentionally avoided
    to prevent false matches inside comment text that mentions the marker.

    Raises SystemExit if the marker appears more than once.
    Rules above the marker are inserted at the top of [Rule].
    Rules below are inserted before FINAL.
    Without the marker, all rules go before FINAL (backwards compatible).
    """
    text = load_custom("rules.conf")
    if not text:
        return "", ""

    lines = text.splitlines()
    marker_indexes = [
        i for i, line in enumerate(lines)
        if line.strip() == _RULES_SPLIT_MARKER
    ]

    if not marker_indexes:
        return "", text

    if len(marker_indexes) > 1:
        raise SystemExit(
            f"[merge] rules.conf contains {len(marker_indexes)} occurrences of "
            f"{_RULES_SPLIT_MARKER!r}; expected exactly one."
        )

    idx = marker_indexes[0]
    top = "\n".join(lines[:idx]).strip()
    prefinal = "\n".join(lines[idx + 1:]).strip()
    return top, prefinal


def insert_rules_at_top(body: str, top_rules: str) -> str:
    """Insert rules immediately after the first content line of the Rule section.

    Since merge() already knows this is the Rule section, we insert after the
    opening '[Rule]' header line without re-scanning for it, avoiding any
    mismatch between parse_sections's section-name normalisation and a
    string search inside the body.
    """
    if not top_rules:
        return body
    lines = body.splitlines(keepends=True)
    if not lines:
        # An empty Rule section body is an invariant violation — abort rather
        # than silently producing malformed output.
        raise SystemExit("[merge] insert_rules_at_top: Rule section body is empty.")
    # Invariant: lines[0] must be the section header (e.g. "[Rule]\n").
    # merge() only calls this function for the Rule section, so parse_sections()
    # guarantees lines[0] is the header. Assert here to catch future regressions.
    if not _SECTION_RE.match(lines[0].strip()):
        raise SystemExit(
            f"[merge] insert_rules_at_top: expected a section header as the first "
            f"line of the Rule body, got: {lines[0]!r}"
        )
    return (
        lines[0]
        + "\n# --- Top Custom Rules ---\n"
        + top_rules + "\n"
        + "\n"
        + "".join(lines[1:])
    )


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
    """Load group names to remove (case-insensitive).

    Inline comments are stripped: 'Amazon # legacy' → 'Amazon'.
    """
    text = load_custom("remove_groups.conf")
    if not text:
        return set()
    groups = set()
    for line in text.splitlines():
        # Strip inline comments before processing
        line = line.split("#", 1)[0].strip()
        if line:
            groups.add(line.casefold())
    return groups


def validate_remove_groups(groups: set[str]) -> None:
    """Raise SystemExit if remove_groups.conf contains a built-in policy name.

    Built-in policies (DIRECT, PROXY, REJECT, FINAL, MITM and REJECT-* variants)
    are not user-created proxy groups. Listing them in remove_groups.conf would
    silently delete every rule that references them, producing a broken config.
    """
    for group in groups:
        if group in _BUILTIN_POLICIES or any(
            group.startswith(prefix) for prefix in _BUILTIN_POLICY_PREFIXES
        ):
            raise SystemExit(
                f"[merge] remove_groups.conf contains built-in policy name "
                f"{group!r}. Built-in policies (DIRECT, PROXY, REJECT, FINAL, MITM) "
                f"cannot be removed — delete this entry from remove_groups.conf."
            )


def remove_proxy_groups(body: str, groups: set[str]) -> str:
    """Remove specified proxy group definitions from [Proxy Group] section.

    Uses partition("=") to tolerate upstream spacing variations like
    'YouTube=select,...' in addition to the standard 'YouTube = select,...'.
    """
    if not groups:
        return body
    lines = body.splitlines(keepends=True)
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.partition("=")[0].strip()
            if name.casefold() in groups:
                continue
        result.append(line)
    return "".join(result)


def _rule_policy(parts: list[str]) -> str:
    """Extract the policy name from a split rule line.

    Trailing options like 'no-resolve', 'pre-matching', 'extended-matching'
    are not policy names; skip them to find the actual policy field.
    Update _RULE_OPTIONS if Shadowrocket introduces new trailing options.
    """
    for part in reversed(parts):
        if part.strip().casefold() not in _RULE_OPTIONS:
            return part.strip()
    return parts[-1].strip()


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
            if len(parts) >= 2 and _rule_policy(parts).casefold() in groups:
                continue
        result.append(line)
    return "".join(result)


def _url_rewrite_raw_content() -> str:
    """Return url_rewrite.conf content if it has real (non-comment) lines, else ''."""
    raw = load_custom("url_rewrite.conf")
    if not raw:
        return ""
    has_content = any(
        line.strip() and not line.strip().startswith("#")
        for line in raw.splitlines()
    )
    return raw if has_content else ""


def append_url_rewrites(body: str) -> str:
    """Append custom URL rewrite rules to an existing [URL Rewrite] section.

    Silently skips when url_rewrite.conf contains only comments or blank lines.
    """
    raw = _url_rewrite_raw_content()
    if not raw:
        return body
    return body.rstrip("\n") + "\n\n# --- Custom URL Rewrites ---\n" + raw + "\n"


def synthesize_url_rewrite_section() -> str:
    """Build a new [URL Rewrite] section body from url_rewrite.conf.

    Called when the upstream config has no [URL Rewrite] section but custom
    rewrite content exists. Returns an empty string if there is nothing to add.
    """
    raw = _url_rewrite_raw_content()
    if not raw:
        return ""
    return "[URL Rewrite]\n# --- Custom URL Rewrites ---\n" + raw + "\n"


def make_header() -> str:
    """Build the config file header, substituting {date} with today's Beijing date.

    Uses str.replace instead of str.format so that literal braces in
    header.conf never cause a KeyError.
    """
    template = (CUSTOM_DIR / "header.conf").read_text("utf-8-sig")
    beijing = timezone(timedelta(hours=8))
    date = datetime.now(beijing).strftime("%Y-%m-%d")
    return template.replace("{date}", date)


def validate_custom_rules_groups(
    top_rules: str, prefinal_rules: str, remove_groups: set[str]
) -> None:
    """Raise SystemExit if any custom rule targets a group that is being removed.

    Custom rules are inserted AFTER remove_rules_for_groups() runs, so they
    would not be cleaned up automatically. Catch this early to prevent a rule
    referencing a non-existent group from silently ending up in the output.
    """
    if not remove_groups:
        return
    for label, text in [("top rules", top_rules), ("pre-final rules", prefinal_rules)]:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                parts = stripped.split(",")
                if len(parts) >= 2:
                    policy = _rule_policy(parts)
                    if policy.casefold() in remove_groups:
                        raise SystemExit(
                            f"[merge] Custom {label} contain a rule targeting "
                            f"removed group {policy!r}: {stripped!r}. "
                            f"Remove the rule or the group from remove_groups.conf."
                        )


def merge() -> str:
    upstream = download_upstream()
    sections = parse_sections(upstream)
    validate_sections(sections)
    remove_groups = load_remove_groups()
    validate_remove_groups(remove_groups)
    top_rules, prefinal_rules = load_rules_conf()
    validate_custom_rules_groups(top_rules, prefinal_rules, remove_groups)

    result_sections = []
    url_rewrite_handled = False
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
            url_rewrite_handled = True
        result_sections.append(body)

    # If upstream had no [URL Rewrite] section but custom content exists,
    # synthesize the section and insert it before [MITM] (the standard upstream
    # position) or append to EOF if [MITM] is absent.
    if not url_rewrite_handled:
        synthetic = synthesize_url_rewrite_section()
        if synthetic:
            mitm_idx = next(
                (i for i, body in enumerate(result_sections)
                 if body.lstrip().startswith("[MITM]")),
                None,
            )
            if mitm_idx is not None:
                result_sections.insert(mitm_idx, synthetic)
            else:
                result_sections.append(synthetic)

    return make_header() + "\n" + "".join(result_sections)


def main():
    merged = merge()
    # Write to a temp file in the same directory, then atomically replace
    # the output so a mid-write interruption never leaves a partial file.
    tmp_fd, tmp_path = tempfile.mkstemp(dir=OUTPUT.parent, prefix=".merge_tmp_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(merged)
        os.replace(tmp_path, OUTPUT)
    except Exception:
        os.unlink(tmp_path)
        raise
    print(f"Merged config written to {OUTPUT}")


if __name__ == "__main__":
    main()
