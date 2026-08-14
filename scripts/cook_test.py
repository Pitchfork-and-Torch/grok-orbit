"""Unattended COOK tests. No live grok spawn. No tokens."""

from __future__ import annotations

from pathlib import Path

from cook import (
    build_board,
    cook_prompt,
    cursor_cook_prompt,
    next_wave_names,
    order_wells,
    prior_sent_ids,
    roster,
    skip_label,
    skip_reason,
    tick,
    well_title,
)

HOME = str(Path.home())


def main() -> int:
    prompt = cook_prompt("VELA", str(Path(HOME) / "vela"))
    assert "Orbit COOK" in prompt
    assert "free-coding" in prompt
    assert "Do not inject" in prompt
    assert "\u2014" not in prompt
    assert "\u2013" not in prompt
    cur = cursor_cook_prompt("land")
    assert "COOK" in cur
    assert "\u2014" not in cur

    leftover = skip_reason({"id": "loose", "paths": [HOME]}, [])
    assert leftover == "leftover"
    assert "next wave" in skip_label("cap")
    assert well_title("vela") == "VELA"
    rows = build_board(
        [{"id": "vela", "name": "VELA"}, {"id": "axiom", "name": "AXIOM"}],
        [{"id": "vela", "via": "grok"}],
        [{"id": "axiom", "reason": "cap"}],
        [],
    )
    assert rows[0]["state"] == "sent"
    assert rows[1]["state"] == "waiting"
    missing = skip_reason({"id": "vela", "paths": [str(Path(HOME) / "no-such-orbit-well")]}, [])
    assert missing == "no-clone"
    live = skip_reason(
        {"id": "fake", "paths": [HOME]},
        [HOME],
    )
    assert live == "live-pager"

    rotated = order_wells(
        [{"id": "vela", "name": "VELA"}, {"id": "axiom", "name": "AXIOM"}, {"id": "orbitstack", "name": "orbitstack"}],
        ["vela"],
    )
    assert [w["id"] for w in rotated] == ["axiom", "orbitstack", "vela"]
    assert order_wells(rotated, [])[0]["id"] == "axiom"
    sent = prior_sent_ids(
        {
            "last_board": [
                {"id": "vela", "state": "sent"},
                {"id": "cursor", "state": "sent"},
                {"id": "axiom", "state": "waiting"},
            ]
        }
    )
    assert sent == ["vela"]
    nxt = next_wave_names(
        [{"id": "axiom", "name": "AXIOM", "state": "waiting"}, {"id": "vela", "name": "VELA", "state": "sent"}]
    )
    assert nxt == ["AXIOM"]

    wells = roster()
    ids = {w["id"] for w in wells}
    assert "loose" not in ids
    assert "grok.com" not in ids
    dry = tick(dry_run=True)
    assert dry["ok"] is True
    assert dry["dry_run"] is True
    assert "dispatched" in dry
    assert isinstance(dry.get("board"), list)
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
    print("OK cook prompt roster skip dry", len(wells), "wells", dry["detail"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
