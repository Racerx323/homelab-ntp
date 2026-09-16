## vexp context tools

For a broad task, call `run_pipeline` once to find relevant files. Skip that
orientation call when the task names the files or symbols to inspect. Use
ordinary file tools for exact text searches, reading, and editing. Call
`run_pipeline` again only when the task moves to another area.

The NTP repository belongs to the shared `/home/aaron/code` vexp workspace.
The optional project Codex configuration targets this Git checkout. Start a
fresh Codex session with `homelab-ntp` as its trusted working root so Codex
can load that setting.
A session started from `/home/aaron/code` can query NTP files, but its
`verify_done` call cannot verify this repo's Git diff. Use
`VEXP_NO_AUTOSTART=1 vexp verify --json` from this repo as a fallback and run
the tests it names. Do not count an unavailable verifier result as a pass.
