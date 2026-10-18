# OFFLINE MOCK — never real unlock or account-registration results

Generated from exact Service Unlock v0.5.4 source by a temporary Go test in its
own source checkout, using real runCLI/runWithClients/core35/extra.Run and HTTP
mock transports. No region override, account identity, live platform or SSH call.
`generate_fixture.go.txt` is the generator (copy as a *_test.go only into a task
copy of that source and run TestTaskGukoFixtures with GUKO_FIXTURE_DIR set).
The fixed CLI source+vendor ZIP is included in stream-unified/source.

JP/NA/EU/SEA and other supported groups are selected by the actual mocked
Cloudflare trace country. global-failed gives two HTTP500 country replies;
global-unsupported gives valid CN. jp-unknown has complete67 Unknown rows.
Normal Spotify fixture311 with country/launch and field errors MUST be Unknown;
jp-denied uses the exact previously captured status320 proxy-refusal shape,
not a real registration. No account was created to obtain a fixture.

Additional same-code mocks: global-no-route (actualfamily0), jp-ipv6 (auto
route selector injected family6 without changing native35 strategy), and
sea-fallback (primary HTTP500, fixed ip.sb country_code SG). No IPv6 or country
source was contacted on the network.
