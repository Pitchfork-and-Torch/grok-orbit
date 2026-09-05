"""Unattended COOK tests. No live grok spawn. No tokens."""

from __future__ import annotations

from pathlib import Path

from cook import (
    build_board,
    cook_prompt,
    cursor_cook_prompt,
    decorate_board,
    is_fresh_proof,
    next_interval,
    next_wave_names,
    order_wells,
    prior_sent_ids,
    roster,
    safe_text,
    skip_label,
    skip_reason,
    tick,
    well_title,
)

HOME = str(Path.home())


def main() -> int:
    prompt = cook_prompt("VELA", str(Path(HOME) / "vela"))
    assert "Orbit COOK" in prompt
    assert "If the tree is occupied, stop." in prompt
    assert "Do not inject" in prompt
    assert "cook-receipt.json" in prompt
    assert "Do not commit .orbit/" in prompt
    assert "\u2014" not in prompt
    assert "\u2013" not in prompt
    rich = cook_prompt(
        "VELA",
        str(Path(HOME) / "vela"),
        proof={"ok": True, "shipped": "dual-gate eval", "next": "interval n"},
        mission="NEXT.md: land public means note",
        dirty=0,
    )
    assert "dual-gate eval" in rich
    assert "interval n" in rich
    assert "Git: clean" in rich
    cur = cursor_cook_prompt("land", "open PR")
    assert "COOK" in cur
    assert "open PR" in cur
    assert "\u2014" not in cur
    assert "ghp_" not in safe_text("token ghp_exampleplaceholder000000 x")

    leftover = skip_reason({"id": "loose", "paths": [HOME]}, [])
    assert leftover == "leftover"
    assert "next wave" in skip_label("cap")
    assert well_title("vela") == "VELA"
    rows = build_board(
        [{"id": "vela", "name": "VELA"}, {"id": "axiom", "name": "AXIOM"}],
        [{"id": "vela", "via": "grok"}],
        [{"id": "axiom", "reason": "cap"}],
        [],
        {"vela": {"ok": True, "shipped": "receipt line", "next": "more"}},
    )
    assert rows[0]["state"] == "sent"
    assert "receipt line" in (rows[0].get("note") or "")
    assert rows[1]["state"] == "waiting"
    missing = skip_reason({"id": "vela", "paths": [str(Path(HOME) / "no-such-orbit-well")]}, [])
    assert missing == "no-clone"
    live = skip_reason(
        {"id": "fake", "paths": [HOME]},
        [HOME],
    )
    assert live == "live-pager"
    cooled = skip_reason(
        {"id": "vela", "paths": [str(Path(HOME) / "no-such-orbit-well")]},
        [],
        {"vela": {"fresh": True, "shipped": "x"}},
    )
    assert cooled == "no-clone"
    cooled_ok = skip_reason(
        {"id": "demo", "paths": [HOME]},
        [],
        {"demo": {"fresh": True, "shipped": "x"}},
    )
    assert cooled_ok in {"fresh-ship", "desk-occupied", "live-pager"}

    rotated = order_wells(
        [{"id": "vela", "name": "VELA"}, {"id": "axiom", "name": "AXIOM"}, {"id": "orbitstack", "name": "orbitstack"}],
        ["vela"],
    )
    assert [w["id"] for w in rotated] == ["axiom", "orbitstack", "vela"]
    proof_last = order_wells(
        [{"id": "vela"}, {"id": "axiom"}, {"id": "orbitstack"}],
        ["axiom"],
        ["vela"],
    )
    assert [w["id"] for w in proof_last] == ["orbitstack", "axiom", "vela"]
    assert order_wells(rotated, [])[0]["id"] == "axiom"
    sent = prior_sent_ids(
        {
            "last_board": [
                {"id": "vela", "state": "sent", "shipped": "ok"},
                {"id": "cursor", "state": "sent"},
                {"id": "axiom", "state": "waiting"},
                {"id": "ghost", "state": "empty"},
            ]
        }
    )
    assert sent == ["vela"]
    nxt = next_wave_names(
        [
            {"id": "axiom", "name": "AXIOM", "state": "waiting"},
            {"id": "ghost", "name": "Ghost", "state": "empty"},
            {"id": "vela", "name": "VELA", "state": "sent"},
        ]
    )
    assert nxt == ["AXIOM", "Ghost"]
    assert next_interval(0) == 90
    assert next_interval(2) == 300
    assert is_fresh_proof({"ok": True, "shipped": "x", "ticked_at": "2099-01-01T00:00:00Z"})
    assert not is_fresh_proof({"ok": False, "shipped": "x", "ticked_at": "2099-01-01T00:00:00Z"})
    assert not is_fresh_proof({"ok": True, "shipped": "", "ticked_at": "2099-01-01T00:00:00Z"})
    painted = decorate_board(
        [{"id": "vela", "name": "VELA", "state": "sent", "note": "waiting receipt"}],
        {"vela": {"ok": True, "shipped": "landed", "next": "more"}},
        [],
    )
    assert painted[0]["state"] == "sent"
    assert "landed" in (painted[0].get("note") or "")
    empty = decorate_board(
        [{"id": "vela", "name": "VELA", "state": "sent", "note": "waiting receipt"}],
        {"vela": {"ok": False, "age": 400}},
        [],
    )
    assert empty[0]["state"] == "empty"

    wells = roster()
    ids = {w["id"] for w in wells}
    assert "loose" not in ids
    assert "grok.com" not in ids
    dry = tick(dry_run=True)
    assert dry["ok"] is True
    assert dry["dry_run"] is True
    assert "dispatched" in dry
    assert isinstance(dry.get("board"), list)
    assert isinstance(dry.get("ships"), list)
    assert dry.get("interval_sec") in {90, 300}
    assert "Grok finished" in dry["detail"] or dry["detail"] == "roster empty"
    assert "\u2014" not in dry["detail"]
    assert "\u00b7" not in dry["detail"]
    if any(w["id"] == "grok-orbit" for w in wells):
        ours = skip_reason(
            next(w for w in wells if w["id"] == "grok-orbit"),
            [],
        )
        if ours == "desk-occupied":
            assert all(d.get("id") != "grok-orbit" for d in dry.get("dispatched") or [])
    print("OK cook harvest prompt roster skip dry", len(wells), "wells", dry["detail"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
