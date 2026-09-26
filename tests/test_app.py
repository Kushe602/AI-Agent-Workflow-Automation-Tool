"""HTTP-level tests: auth, ownership, and a full run streamed to completion."""


async def _register(client, email="user@test.dev", password="password123"):
    return await client.post(
        "/register", data={"email": email, "password": password}, follow_redirects=False
    )


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
