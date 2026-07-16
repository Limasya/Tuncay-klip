"""
platform_eng.flags testleri (IP_PART6 Bölüm 37.1-37.3).

Kapsam:
  - Aç/kapa (kill switch)
  - Kademeli açılım (percentage rollout) — deterministik ve stabil
  - Hedefleme: plan / region / allowlist / blocklist
  - Bilinmeyen flag => default (fail-safe)
"""
import json

from platform_eng.flags import FeatureFlagClient, FlagRule, FlagType


def test_disabled_flag_is_off():
    rule = FlagRule(key="f", enabled=False)
    assert rule.evaluate({"targetingKey": "u1"}) is False


def test_full_rollout_is_on():
    rule = FlagRule(key="f", enabled=True, rollout_percentage=100)
    assert rule.evaluate({"targetingKey": "u1"}) is True


def test_blocklist_overrides_everything():
    rule = FlagRule(
        key="f", enabled=True, rollout_percentage=100,
        disabled_targets=frozenset({"u-blocked"}),
    )
    assert rule.evaluate({"targetingKey": "u-blocked"}) is False


def test_allowlist_opens_even_when_disabled():
    rule = FlagRule(
        key="f", enabled=False,
        enabled_targets=frozenset({"u-beta"}),
    )
    assert rule.evaluate({"targetingKey": "u-beta"}) is True


def test_plan_targeting():
    rule = FlagRule(
        key="f", enabled=True, rollout_percentage=100,
        enabled_plans=frozenset({"pro"}),
    )
    assert rule.evaluate({"targetingKey": "u1", "plan": "pro"}) is True
    assert rule.evaluate({"targetingKey": "u1", "plan": "free"}) is False


def test_region_targeting():
    rule = FlagRule(
        key="f", enabled=True, rollout_percentage=100,
        enabled_regions=frozenset({"eu"}),
    )
    assert rule.evaluate({"targetingKey": "u1", "region": "eu"}) is True
    assert rule.evaluate({"targetingKey": "u1", "region": "us"}) is False


def test_rollout_is_deterministic_and_stable():
    rule = FlagRule(key="f", enabled=True, rollout_percentage=50)
    first = rule.evaluate({"targetingKey": "stable-user"})
    for _ in range(20):
        assert rule.evaluate({"targetingKey": "stable-user"}) == first


def test_rollout_distribution_roughly_matches_percentage():
    rule = FlagRule(key="dist", enabled=True, rollout_percentage=30)
    on = sum(rule.evaluate({"targetingKey": f"user-{i}"}) for i in range(2000))
    ratio = on / 2000
    assert 0.25 < ratio < 0.35  # ~%30 civarı


def test_rollout_without_targeting_key_is_off():
    rule = FlagRule(key="f", enabled=True, rollout_percentage=50)
    assert rule.evaluate({}) is False


def test_client_unknown_flag_returns_default():
    client = FeatureFlagClient()
    assert client.get_boolean_value("missing", default=True) is True
    assert client.get_boolean_value("missing", default=False) is False


def test_client_from_dict_and_all_flags():
    client = FeatureFlagClient.from_dict({
        "a": {"enabled": True, "type": "ops"},
        "b": {"enabled": False, "type": "release"},
    })
    assert client.get_boolean_value("a") is True
    assert client.get_boolean_value("b") is False
    assert set(client.all_flags().keys()) == {"a", "b"}
    assert client.all_flags()["a"].flag_type is FlagType.OPS


def test_client_from_file(tmp_path):
    p = tmp_path / "flags.json"
    p.write_text(json.dumps({"x": {"enabled": True}}), encoding="utf-8")
    client = FeatureFlagClient.from_file(p)
    assert client.get_boolean_value("x") is True


def test_flag_rule_from_dict_parses_targeting():
    rule = FlagRule.from_dict("f", {
        "enabled": True,
        "type": "permission",
        "rollout_percentage": 100,
        "enabled_targets": ["a", "b"],
        "disabled_targets": ["c"],
    })
    assert rule.flag_type is FlagType.PERMISSION
    assert rule.enabled_targets == frozenset({"a", "b"})
    assert rule.disabled_targets == frozenset({"c"})
