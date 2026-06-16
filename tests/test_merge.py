import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MERGE_PATH = ROOT / "scripts" / "merge.py"


def load_merge_module():
    spec = importlib.util.spec_from_file_location("merge_under_test", MERGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UPSTREAM = """# upstream header
[General]
ipv6 = true
fallback-dns-server = system
dns-server = system

[Proxy Group]
YouTube = select,Proxy
Global = select,Proxy

[Rule]
DOMAIN-SUFFIX,youtube.com,YouTube
DOMAIN-SUFFIX,example.com,Global
FINAL,Global

[MITM]
hostname = google.cn
"""


class MergeScriptTests(unittest.TestCase):
    def merge_with_custom(self, upstream, custom_files):
        module = load_merge_module()
        with tempfile.TemporaryDirectory() as tmp:
            custom_dir = Path(tmp) / "custom"
            custom_dir.mkdir()
            files = {
                "header.conf": "# generated {date}\n",
                "general.conf": "",
                "rules.conf": "",
                "url_rewrite.conf": "",
                "mitm.conf": "",
                "remove_groups.conf": "",
            }
            files.update(custom_files)
            for name, content in files.items():
                (custom_dir / name).write_text(content, encoding="utf-8")

            module.CUSTOM_DIR = custom_dir
            module.download_upstream = lambda: upstream
            return module.merge()

    def test_applies_overrides_rules_group_removal_and_mitm_delete(self):
        output = self.merge_with_custom(
            UPSTREAM,
            {
                "general.conf": "ipv6 = false\nfallback-dns-server = __DELETE__\n",
                "rules.conf": (
                    "DOMAIN-SUFFIX,cn,DIRECT\n"
                    "# --- pre-final ---\n"
                    "DOMAIN-SUFFIX,late.example,DIRECT\n"
                ),
                "remove_groups.conf": "YouTube\n",
                "mitm.conf": "hostname = __DELETE__\n",
            },
        )

        self.assertIn("ipv6 = false", output)
        self.assertNotIn("fallback-dns-server", output)
        self.assertNotIn("YouTube = select", output)
        self.assertNotIn("DOMAIN-SUFFIX,youtube.com,YouTube", output)
        self.assertNotIn("hostname = google.cn", output)
        self.assertLess(
            output.index("DOMAIN-SUFFIX,cn,DIRECT"),
            output.index("DOMAIN-SUFFIX,example.com,Global"),
        )
        self.assertLess(
            output.index("DOMAIN-SUFFIX,late.example,DIRECT"),
            output.index("FINAL,Global"),
        )

    def test_synthesizes_url_rewrite_section_when_upstream_lacks_one(self):
        output = self.merge_with_custom(
            UPSTREAM,
            {"url_rewrite.conf": "^https://example.com/old https://example.com/new 302\n"},
        )

        self.assertIn("[URL Rewrite]", output)
        self.assertIn("^https://example.com/old https://example.com/new 302", output)
        self.assertLess(output.index("[URL Rewrite]"), output.index("[MITM]"))

    def test_rejects_removed_builtin_policy(self):
        with self.assertRaises(SystemExit) as ctx:
            self.merge_with_custom(UPSTREAM, {"remove_groups.conf": "DIRECT\n"})

        self.assertIn("built-in policy name", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
