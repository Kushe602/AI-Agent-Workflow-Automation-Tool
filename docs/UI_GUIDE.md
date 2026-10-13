# AgentFlow UI guide

## Design direction

The interface uses a modern dark workspace theme: deep navy backgrounds, restrained violet accents, soft surface borders, clear hierarchy, and responsive layouts. Shared presentation lives in `app/templates/base.html`; page templates continue to use the existing Jinja variables and server routes.

## Main screens

- **Dashboard** (`app/templates/index.html`): goal input, selectable tools, run creation, and recent run history.
- **Run details** (`app/templates/run.html`): live/replayed step timeline, cancellation, and artifacts.
- **Landing and authentication** (`landing.html`, `login.html`, `register.html`): introduction and existing account flows.

## Interaction principles

- The run form still posts to `/runs`; logout still posts to `/logout`.
- The tool selection checkboxes retain their `tools` field name and tool values.
- Run history links continue to use `/runs/{id}`.
- Focus indicators and reduced-motion handling are included in shared styling.
- Prompt examples are suggestions only; outputs depend on the selected tools and active model/demo configuration.

## Verify locally

1. Follow the root README quickstart.
2. Check registration, login, run creation, selecting/deselecting tools, live step streaming, cancellation, replay, and artifact downloads.
3. Test narrow and wide viewports and keyboard navigation.
4. Run the existing test suite and lint commands from the README.

## Scope

This guide documents the UI structure and verification checklist. It does not claim that the app has been run or browser-tested as part of this update.
