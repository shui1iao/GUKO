# CLI v0.5.7 offline fixtures

Generated from this release's exact service-unlock v0.5.7 source through the actual runCLI --machine, injected HTTPmock transports and unchanged original renderer. Native22 + selected extras. No real platform/Spotify/signup requests, accounts or现场结果. All regions, auto errors/fallback/IPv6/no-route/denied/Unknown retained. jp-narrow uses the same actual mock measurement and renderer Width40. Generator scripts are included and run in the CLI root as temporary *_test.go files; do not publish them as production probes. Exact commit/source identity is recorded in the release handoff after the CLI commit is frozen.

Historical fixture generation notes below are from v0.5.6, not current directory counts.

# OFFLINE MOCK — never live unlock or account-registration results

Regenerated for GUKO v0.7.0 from the **exact official Service Unlock v0.5.6**
complete source ZIP, release commit 53e7e8f1bfc9fe0cd9513dd78638d513a7aea257.
Source asset SHA256: 8d1c25c4b78eb6b5536f18b782d6b9f7b96d06fe41506a1842dcd67e3279c22d.

The generator `generate_fixture.go.txt` is copied as task_guko_fixture_test.go
into a task-local extraction of that source root. Run `go test -mod=vendor -run
^TestTaskGukoFixtures$ -count=1 .` with GUKO_FIXTURE_DIR targeting this folder.
This was executed in an existing Go1.26 container **with --network none** and
vendor dependencies. No product/upstream source modifications or live HTTP.

This is the real CLI runCLI/runWithClients path and its current renderer using
existing HTTP mocks, 34 native +134 extra catalogue, platform single logical row,
six presentation groups, same measurement JSON and ANSI. Fixture counts differ
by actual mocked exit-country selection; no inventory region override.

Spotify status311 errors remain Unknown; jp-denied uses the previously captured
status320 refusal **mock** shape, not a new registration. No account, login,
Spotify request, SSH or live service scan was made. No fixture is field evidence.

global-failed/global-unsupported/global-no-route, jp-ipv6 and sea-fallback retain
their documented failure/family/country-source scenarios. Full protocol/security
mutations continue to test rejection, not rewritten to arbitrary success text.

`jp-narrow.json` uses the same captured JP mock measurement and the official
NewMachineOutput/PrintAccess renderer with Width=40. The companion
`generate_narrow_fixture.go.txt` is run instead of the base generator in a separate
output directory; only jp-narrow.json is copied. It tests real lossless wraps and
independent ANSI fragments, not invented successful platform responses.
