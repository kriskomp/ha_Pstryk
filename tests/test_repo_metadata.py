"""Repository metadata the release and validation workflows rely on.

Mirrors the rules hassfest and the HACS action apply, so a problem shows up
in the local test run and not only on GitHub.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "pstryk"
MANIFEST = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))

# hassfest CUSTOM_INTEGRATION_MANIFEST_SCHEMA (keys this manifest may use)
MANIFEST_KEYS = {
    "domain", "name", "after_dependencies", "codeowners", "config_flow",
    "dependencies", "documentation", "integration_type", "iot_class",
    "issue_tracker", "loggers", "requirements", "single_config_entry", "version",
}
# HACS HACS_MANIFEST_JSON_SCHEMA (extra keys are rejected)
HACS_KEYS = {
    "name", "content_in_root", "country", "filename", "hacs",
    "hide_default_branch", "homeassistant", "persistent_directory",
    "render_readme", "zip_release",
}
# Top-level translation sections hassfest accepts for this integration
TRANSLATION_SECTIONS = {"title", "config", "options", "issues", "exceptions", "entity", "services"}


def _changelog_section():
    spec = importlib.util.spec_from_file_location(
        "changelog_section", ROOT / "scripts" / "changelog_section.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.section


def test_manifest_uses_only_known_keys():
    assert set(MANIFEST) <= MANIFEST_KEYS, set(MANIFEST) - MANIFEST_KEYS


def test_manifest_keys_in_hassfest_order():
    keys = list(MANIFEST)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_hacs_json_uses_only_known_keys():
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert set(hacs) <= HACS_KEYS, set(hacs) - HACS_KEYS


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_translation_sections_are_known(lang):
    data = json.loads((INTEGRATION / "translations" / f"{lang}.json").read_text(encoding="utf-8"))
    assert set(data) <= TRANSLATION_SECTIONS, set(data) - TRANSLATION_SECTIONS


def test_moved_mqtt_texts_exist_in_both_languages():
    for lang in ("en", "pl"):
        data = json.loads((INTEGRATION / "translations" / f"{lang}.json").read_text(encoding="utf-8"))
        assert set(data["issues"]["mqtt_not_configured"]) == {"title", "description"}, lang


def test_mqtt_notification_reads_existing_translation_keys():
    code = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    en = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))
    issue = en["issues"]["mqtt_not_configured"]
    assert '"issues", [DOMAIN]' in code
    for field in ("title", "description"):
        assert f'.issues.mqtt_not_configured.{field}"' in code
        assert issue[field]


def test_changelog_has_notes_for_the_manifest_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert _changelog_section()(MANIFEST["version"], text)


def test_changelog_section_stops_at_the_next_version():
    text = "# Zmiany\n\n## 1.0.1\n\n- b\n\n## 1.0.0\n\n- a\n"
    section = _changelog_section()
    assert section("1.0.1", text) == "- b"
    assert section("1.0.0", text) == "- a"
    with pytest.raises(SystemExit):
        section("1.0.2", text)


def test_release_workflow_watches_this_manifest():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "custom_components/pstryk/manifest.json" in workflow
    assert "solaredge" not in workflow
