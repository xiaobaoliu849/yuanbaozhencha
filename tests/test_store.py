from backend.services import store


def new_watch(verdict: str = "true") -> str:
    claim = {"claim": "某地下月起限行", "verdict": verdict, "confidence": 80, "explanation": "",
             "evidence": [], "searched": ["某地 限行"], "checked_at": store.now()}
    return store.add_watch("owner-12345678", "rid", claim, [])["id"]


def check(wid: str, verdict: str, confidence: int) -> dict:
    return store.record_check(wid, {"verdict": verdict, "confidence": confidence, "explanation": "",
                                    "evidence": []}, [])


def test_confident_new_verdict_counts_as_change():
    wid = new_watch("true")
    w = check(wid, "false", 80)
    assert w["just_changed"]
    assert w["verdict"] == "false"
    assert w["changed"]
    assert w["previous_verdict"] == "true"


def test_unsure_new_verdict_needs_to_repeat():
    wid = new_watch("true")
    w = check(wid, "false", 40)
    assert not w["just_changed"]
    assert w["verdict"] == "true"
    w = check(wid, "false", 40)
    assert w["just_changed"]
    assert w["verdict"] == "false"


def test_unknown_never_counts_as_change():
    # What a search outage or a spent quota looks like: no sources, so 「查不到」, possibly with high confidence.
    wid = new_watch("true")
    for _ in range(3):
        w = check(wid, "unknown", 90)
        assert not w["just_changed"]
        assert not w["changed"]
        assert w["verdict"] == "true"
    assert [h["verdict"] for h in w["history"]] == ["true", "unknown", "unknown", "unknown"]


def test_leaving_unknown_still_counts():
    wid = new_watch("unknown")
    w = check(wid, "true", 80)
    assert w["just_changed"]
    assert w["verdict"] == "true"


def test_same_verdict_is_not_a_change():
    wid = new_watch("false")
    w = check(wid, "false", 90)
    assert not w["just_changed"]
    assert not w["changed"]


def test_ack_and_stop_only_for_owner():
    wid = new_watch("true")
    check(wid, "false", 80)
    store.ack_watch(wid, "someone-else")
    assert store.get_watch(wid)["changed"]
    store.ack_watch(wid, "owner-12345678")
    assert not store.get_watch(wid)["changed"]
    store.stop_watch(wid, "owner-12345678")
    assert wid not in {w["id"] for w in store.list_watches("owner-12345678")}
