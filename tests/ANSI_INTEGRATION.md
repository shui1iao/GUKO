# ANSI terminal integration (offline acceptance)

- Standalone IP retains its existing `IP.Check.Place -y`/`TERM=xterm-256color` command and first-report completion boundary. Upstream `check_IP` prints the entire ANSI report before its SVG URL; `run_until_report` decodes bytes without stripping ANSI. `extract_ip_ansi_report` slices the matching final title and preceding `####` separator through that URL. It excludes preceding download/clear controls and subsequent dual-stack reports. LFCR and SGR are preserved, not reconstructed. A complete report remains usable even with nonzero upstream exit.
- NQ creates a bot-generated `/root/guko-nodequality-<32 hex>` directory (0700, umask 077), passes official `-d`, and patches the known upstream cleanup line to copy the four allowlisted `.log` files out of `BenchOs/result` before BenchOs removal. Reads use existing SSH arguments/credentials with a 2MiB+1 bound and dedicated stdout/stderr pipes (SSH warnings never enter ANSI), not the public API or a latest-directory scan. No path parsed from remote output is executed. In task `finally`, only these four copied logs are removed; existing official nested result ZIP/workdir retention remains unchanged. Cleanup never recursively deletes the parent or mounted directories.
- Full NQ sends only its combined link and never reads/renders component logs. Partial/single selections use `hardware`, `ip`, `net`, `backroute` with their corresponding official logs. Missing logs/rendering failure keeps available report links and explicitly reports PNG failure; no SVG fallback or JSON re-upload recovery is invoked. Legacy SVG helper and cached history remain unchanged.
- `render_ansi_png` invokes `node /app/render_ansi.js input.log output.png --kind KIND` (adjacent source fallback). It inherits `CHECKPLACE_TERMINAL_FONT`; no font download. Input limit 2MiB, semaphore 1, temporary input 0600 and automatic cleanup, timeout 120 seconds, output PNG signature check. The dedicated process runner owns a new session and kills/reaps the process group on completion/timeout/cancellation so Node failure cannot leave Chromium behind.

## Tests

```sh
docker run --rm --network none \
  -v /root/guko-render-fix:/work -w /work --entrypoint python \
  guko-local:render-fidelity -m unittest discover -s tests -v
```

`test_ansi_integration.py` covers ANSI-preserving IP handoff, first-report dual-stack isolation, each NQ kind, full-selection suppression, read/render/timeout failure links, hostile paths, bounded transport, private temporary input, subprocess timeout/cancellation group cleanup, and actual generated-shell cleanup/copy behavior using a local fixture instead of network/benchmarks. Original new behavior tests were run failing before implementation; timeout/cancellation and explicit timeout notices likewise received separate RED/GREEN cycles.

For private real fixtures use `Path(...).read_bytes().decode()` rather than universal-newline `read_text()`. Parent acceptance used `/root/nq-render-audit/standalone-live.stdout` and the real standalone-IP report; do not commit private fixture/font data. No live NQ benchmark or Telegram delivery is part of these offline tests. Deployment and final image/runtime acceptance belong to the parent task.
