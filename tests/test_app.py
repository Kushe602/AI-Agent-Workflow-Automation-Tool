"""HTTP-level tests: auth, ownership, and a full run streamed to completion."""


async def _register(client, email="user@test.dev", password="password123"):
    return await client.post(
        "/register", data={"email": email, "password": password}, follow_redirects=False
    )


async def _run_to_done(client, goal, tools=None):
    """Create a run, drive its SSE stream to completion, and return the run id."""
    data = {"goal": goal}
    if tools is not None:
        data["tools"] = tools
    resp = await client.post("/runs", data=data, follow_redirects=False)
    assert resp.status_code == 303
    run_id = resp.headers["location"].rsplit("/", 1)[-1]
    stream = await client.get(f"/runs/{run_id}/stream")
    assert stream.status_code == 200
    assert "event: done" in stream.text
    return run_id


async def test_register_sets_session_and_shows_dashboard(client):
    resp = await _register(client)
    assert resp.status_code == 303
    home = await client.get("/")
    assert home.status_code == 200
    assert "New run" in home.text


async def test_create_run_requires_auth(client):
    resp = await client.post("/runs", data={"goal": "hi"}, follow_redirects=False)
    assert resp.status_code == 401


async def test_full_run_streams_to_completion(client):
    await _register(client, email="flow@test.dev")
    resp = await client.post(
        "/runs", data={"goal": "What is 21 * 2?"}, follow_redirects=False
    )
    assert resp.status_code == 303
    run_id = resp.headers["location"].rsplit("/", 1)[-1]

    stream = await client.get(f"/runs/{run_id}/stream")
    assert stream.status_code == 200
    assert "event: done" in stream.text
    assert "succeeded" in stream.text

    page = await client.get(f"/runs/{run_id}")
    assert "42" in page.text


async def test_dashboard_shows_tool_checkboxes(client):
    await _register(client, email="tools@test.dev")
    home = await client.get("/")
    assert 'name="tools"' in home.text
    assert 'value="calculator"' in home.text
    assert 'value="uuid_generate"' in home.text


async def test_run_persists_selected_tools(client):
    await _register(client, email="select@test.dev")
    run_id = await _run_to_done(client, "What is 21 * 2?", tools=["calculator"])
    md = await client.get(f"/runs/{run_id}/export.md")
    assert md.status_code == 200
    assert "**Tools enabled:** calculator" in md.text
    assert "**Tools enabled:** all" not in md.text


async def test_export_markdown_has_goal_and_final(client):
    await _register(client, email="export@test.dev")
    run_id = await _run_to_done(client, "What is 21 * 2?")
    md = await client.get(f"/runs/{run_id}/export.md")
    assert md.status_code == 200
    assert "markdown" in md.headers["content-type"]
    assert "attachment" in md.headers["content-disposition"]
    assert "# AgentFlow run" in md.text
    assert "What is 21 * 2?" in md.text
    assert "### Final answer" in md.text
    assert "42" in md.text


async def test_workspace_artifacts_browser(client):
    await _register(client, email="files@test.dev")
    run_id = await _run_to_done(client, "Please write a note about cats")

    listing = await client.get(f"/runs/{run_id}/files")
    assert listing.status_code == 200
    paths = [f["path"] for f in listing.json()["files"]]
    assert "note.txt" in paths

    raw = await client.get(f"/runs/{run_id}/files/raw", params={"path": "note.txt"})
    assert raw.status_code == 200
    assert "cats" in raw.text

    traversal = await client.get(
        f"/runs/{run_id}/files/raw", params={"path": "../../etc/passwd"}
    )
    assert traversal.status_code == 400


async def test_run_files_require_ownership(client):
    await _register(client, email="owner@test.dev")
    run_id = await _run_to_done(client, "Please write a note about dogs")
    await _register(client, email="intruder@test.dev")
    resp = await client.get(f"/runs/{run_id}/files")
    assert resp.status_code == 404


async def test_stop_endpoint_ownership(client):
    await _register(client, email="stopper@test.dev")
    run_id = await _run_to_done(client, "What is 21 * 2?")
    owned = await client.post(f"/runs/{run_id}/stop")
    assert owned.status_code == 204

    await _register(client, email="other@test.dev")
    unowned = await client.post(f"/runs/{run_id}/stop")
    assert unowned.status_code == 404
