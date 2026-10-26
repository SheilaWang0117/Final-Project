from fastapi.testclient import TestClient

from app.main import app


def test_demo_end_to_end_smoke():
    with TestClient(app) as c:
        st = c.get("/api/status").json()
        assert st["mode"] == "demo" and st["contains_synthetic_data"]
        progs = c.get("/api/programs").json()
        assert {p["code"] for p in progs} >= {"HX-101", "HX-205"}
        vx = next(p for p in progs if p["code"] == "HX-101")
        detail = c.get(f"/api/programs/{vx['id']}").json()
        assert len(detail["milestones"]) == 6
        s = c.get("/api/finance/summary").json()
        assert s["cash"]["complete"] is True and s["cash"]["available_cash_minor"] > 0
        assert s["forecast"]["months"]
        tl = c.get("/api/timeline").json()
        assert any(m.get("funding") for m in tl["milestones"])
        pilot = next(m for m in detail["milestones"] if m["name"].startswith("Pilot"))
        f = c.get(f"/api/finance/milestones/{pilot['id']}/funding").json()
        assert f["funded"] in (True, False)
        sc = c.get("/api/finance/scenarios").json()["scenarios"]
        cmp = c.get(f"/api/finance/scenarios/{sc[3]['id']}/compare").json()
        assert cmp["comparison"]["months"]
        r = c.post("/api/classify", json={"description": "We are developing an oral small-molecule kinase inhibitor for canine mast cell tumors and initially considering the US and EU."}).json()
        assert r["proposal"]["use_type"]["value"] == "veterinary" and set(r["proposal"]["jurisdictions"]["value"]) == {"US", "EU"}
        ans = c.post("/api/assistant/ask", json={"question": "Can we afford the next milestone?", "program_id": vx["id"]}).json()
        assert ans["method"] == "template_demo" and ans["key_figures"]
        csv_text = c.get("/api/finance/export/summary.csv").text
        assert "available_cash" in csv_text


def test_company_mission_and_chinese_answers():
    with TestClient(app) as c:
        co = c.get("/api/settings/company").json()
        assert co["values"] == ["All life matters"] and co["mission"] == ""
        saved = c.put("/api/settings/company", json={"mission": "Better cancer care for pets.", "values": ["All life matters", "Evidence first"]}).json()
        assert saved["mission"] == "Better cancer care for pets." and len(saved["values"]) == 2
        progs = c.get("/api/programs").json()
        vx = next(p for p in progs if p["code"] == "HX-101")
        ans = c.post("/api/assistant/ask", json={"question": "下一个里程碑资金够吗？", "program_id": vx["id"], "language": "zh"}).json()
        assert "里程碑" in ans["answer"] and ans["key_figures"]
        r = c.post("/api/classify", json={"description": "We are developing an oral small molecule for canine oncology.", "language": "zh"}).json()
        assert any("靶点" in q for q in r["proposal"]["follow_up_questions"])


def test_pipeline_spend_and_competitors_by_pipeline():
    with TestClient(app) as c:
        s = c.get("/api/finance/summary").json()
        pipes = {p["code"]: p for p in s["pipelines"]}
        assert set(pipes) == {"HX-101", "HX-205", "HX-310"}
        for p in pipes.values():
            # per-pipeline totals are the sum of the milestone rows; unbudgeted milestones are flagged, not zero-filled as budgeted
            assert p["spent_minor"] == sum(m["spent_minor"] for m in p["milestones"])
            assert p["to_spend_minor"] == sum(m["to_spend_minor"] for m in p["milestones"])
            for m in p["milestones"]:
                assert m["total_minor"] == m["spent_minor"] + m["to_spend_minor"]
                if not m["budgeted"]:
                    assert m["budget_minor"] is None and m["to_spend_minor"] == 0
        assert any(not m["budgeted"] for m in pipes["HX-310"]["milestones"])
        # pipeline totals plus company running costs equal the full budget status
        shared = next(p for p in s["budget_by_program"] if not p["program_id"])
        prog_spent = sum(p["actual_minor"] for p in s["budget_by_program"] if p["program_id"])
        assert sum(p["spent_minor"] for p in pipes.values()) == prog_spent
        assert shared["actual_minor"] >= 0
        comp = c.get("/api/competitors/by-pipeline").json()
        assert {p["code"] for p in comp} == {"HX-101", "HX-205", "HX-310"}
        assert all(p["competitors"] and "latest" in p["competitors"][0] for p in comp)


def test_phase_map_rows_and_gates():
    from app.phases import phase_of
    assert phase_of("Feline PK pilot", "Feasibility / pilot target-animal studies") == "preclin"  # name beats an older stage label
    assert phase_of("Anything", "GLP target animal safety (TAS)") == "tas"  # explicit phase wins
    with TestClient(app) as c:
        pm = c.get("/api/phase-map").json()
        assert [p["key"] for p in pm["phases"]][:3] == ["discovery", "lead", "ip"]
        rows = {r["code"]: r for r in pm["rows"]}
        assert set(rows) == {"HX-101", "HX-205", "HX-310"}
        hx101 = rows["HX-101"]
        assert hx101["current_phase"] == "tas"
        assert hx101["gates"]["ip"] == "passed" and hx101["gates"]["reg"] == "passed" and hx101["gates"]["tas"] == "next"
        assert hx101["gates"]["pilot"] == "ahead"
        # patent filed early, but candidate nomination (the earlier gate) is still open -> not passed yet
        assert rows["HX-205"]["gates"]["lead"] == "next" and rows["HX-205"]["gates"]["ip"] == "ready"
        for r in rows.values():  # gates are passed strictly in order
            states = [r["gates"][p["key"]] for p in pm["phases"] if p["gate"]]
            first_open = next((i for i, st in enumerate(states) if st != "passed"), len(states))
            assert all(st != "passed" for st in states[first_open:])
        assert sum(len(v) for v in hx101["cells"].values()) == 6
