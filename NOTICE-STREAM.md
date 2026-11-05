# GUKO v0.7.0 — modified integration

Original GUKO portions retain the MIT LICENSE and existing notices. The unified
integration (stream_unified.py, stream_terminal.py, kat_proxy.py, tool_sources.py and modified
orchestration/packaging) is AGPL-3.0-only; see LICENSES/AGPL-3.0.txt. The combined
image is NOT MIT-only. Explicit platform identities/terminal interpretation are
adapted from Service Unlock v0.5.6's MIT renderer, Copyright 2026 Remnawave.
Other upstream source notices and third-party licenses remain applicable.

New stream tasks resolve the official Service Unlock stable latest release at
https://github.com/shui1iao/service-unlock . Binary, SHA256SUMS and complete
Corresponding Source ZIP (including vendor/licenses) must belong to that SAME
release and match GitHub asset digests and SUMS. Immutable download URLs, exact
release tag/commit, architecture and hashes are recorded in task/history
`tool_source`; the exact source ZIP is retained in the content-addressed local
download cache and its immutable official URL is the task's source offer.
No fixed v0.5.4 binary, old cache or historical source ZIP is a fallback.
The local adapter supports the explicit v0.5.6 raw168/platform145 contract;
unknown schema/directory/terminal semantics are rejected, not silently ignored.

Historical reports and their original version/source evidence are not rerun or
relabelled. Old reports without version evidence remain without such evidence.
The legacy stream-unified files in Git are historical v0.5.4 artifacts only;
they are not copied by the normal Dockerfile or used by any new task. A local
overlay based on the exact deployed image can inherit those unreachable files.

The exact public Corresponding Source is the matching release source ZIP and
SHA256SUMS identified below. Operators modifying this version must offer their
actual modified source, not claim an older public tag is its corresponding source.
Inventories, keys, private fonts, tokens and historical results are excluded.

Kat integration only interprets the documented SS/AnyTLS configuration identity
contract. It does not embed or alter Kat-Server / Kat-Manager code or licences.
An authorized future install downloads the complete official Manager helper set
at a single recorded commit and retains its upstream notices unchanged. The
source offer is that immutable repository tree plus the actual Server evidence;
existing-node reads do not run or download a manager. Original GUKO MIT portions,
AGPL integration obligations and all third-party notices remain preserved.

## Public v0.7.0 source offer

This release supersedes the preceding local-only delivery status. Exact full
Corresponding Source: https://github.com/shui1iao/GUKO/releases/download/v0.7.0/guko-v0.7.0-source.zip
with SHA256SUMS from the same release. Public image OCI version/revision identify
this release commit. The private local overlay Dockerfile is historical operator
material, not a public build input. The public Dockerfile builds independently;
no private tags, fonts, inventories or generated local source are required.
