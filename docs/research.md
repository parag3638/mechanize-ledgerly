# Research notes (2026-10-13)

Read before designing, as the brief required. Versions at the time: `inspect-ai` 0.3.279 (0.3.280 when locked on 2026-10-14), `inspect-swe` 0.2.71. Claims marked *(source)* were read from the library code because the docs don't state them; the rest come from the official docs. PROJECT.md §1 has the short version.

## 1. Inspect AI: what the design depends on

### Tasks and datasets
- `Task(dataset, setup, solver, cleanup, scorer, metrics, sandbox, epochs, fail_on_error, score_on_error, message_limit, token_limit, time_limit, working_limit, cost_limit, ...)`; `@task` turns function parameters into task args (`-T name=value`).
- `Sample(input, target, id, metadata, sandbox, files, setup)`. `files` maps a sandbox path to content, a path, a URL or a data URI. A destination may name a service (`"grader:/grader/tests"`). Directories copy recursively. `setup` is bash run in the default service after `files`, with a 5-minute timeout.
- `inspect eval file.py@task --model ... --limit --epochs --epochs-reducer --max-sandboxes --log-dir -T k=v`; Python `eval()` / `eval_set()`. A `.env` in the working directory is read automatically.

### Docker / Compose sandboxes (https://inspect.aisi.org.uk/sandboxing.html)
- `sandbox="docker"` picks up `compose.yaml` in the task directory; `("docker", "file.yaml")` names another file; `SandboxEnvironmentSpec("docker", ComposeConfig(...))` per sample.
- Multi-service: the default service must be named `default` or carry `x-default: true`. The "first service" fallback in the docs does not apply to the Docker provider *(source)*.
- A custom compose file **replaces** Inspect's generated one: you must set `network_mode: none` or an `internal: true` network yourself; Compose's default network has internet egress.
- Honoured: `init: true`, `command: tail -f /dev/null`, `cpus`, `mem_limit`, `deploy.resources.limits`, `healthcheck`, `depends_on: {condition: service_healthy}`, `privileged`, `cap_add/drop`, `read_only`, `tmpfs`, `ulimits`, `pids_limit`. **`container_name` is forbidden** (breaks epochs).
- Startup is `docker compose up --detach --wait`; timeout 600 s without healthchecks, otherwise 60 s plus the healthcheck budget *(source)*. One-shot containers that exit 0 are tolerated.
- One compose project per sample (`inspect-<task>-i<uuid>`); cleanup is `compose down --volumes`, so named volumes are per sample. `--no-sandbox-cleanup` keeps containers and prints the cleanup command; `inspect sandbox cleanup docker` cleans all.
- **Writable host bind mounts are blocked on `main`** (PR #5830, merged 2026-10-13, likely in 0.4.0); read-only binds need Docker Engine 25+. Use named volumes.
- `--max-sandboxes` defaults to 2 × CPUs. Give `build:` services an explicit `image:` so `--sandbox-prebuilt` can skip builds.
- Docker-in-Docker: only an example ("evals in eval") with a privileged rootless sidecar, explicitly unsuitable for adversarial agents. A docker socket mount is a writable host mount and is blocked by default.

### `sandbox()` API
- `exec(cmd, input, cwd, env, user, timeout, timeout_retry, concurrency)`, `read_file(file, text)`, `write_file(file, contents)` (creates parent dirs), `connection()`. `sandbox("svc")` targets any service, from solvers **and scorers**.
- `exec` output is silently front-truncated at 10 MB; `read_file` raises above 100 MB. Exec timeouts wrap `/usr/bin/timeout` *(source)*.

### Scorers
- `@scorer(metrics=...)` returning `async def score(state: TaskState, target: Target) -> Score`. `Score(value, answer, explanation, metadata)`; `value` may be a flat dict of scalars; metrics per key (`{"*": [mean()]}`), epoch reducers per key (`mean`, `median`, `max`, `pass_at_k`, ...). `Score.unscored()` gives NaN that metrics skip.
- Scorers run **inside the live sample's sandbox context**, in list order *(source)*; the docs confirm `sandbox().exec/read_file` from a scorer. Scoring time limit = `time_limit / 2` when set.
- `inspect score` re-scores a log **without a sandbox** (`sandbox()` raises) *(source)* → sandbox-based grading must happen during the eval.
- Errored samples are not scored unless `score_on_error=True`; `retry_on_error` re-runs with a fresh sandbox *(source)*.

### Model-graded scoring and caching
- `model_graded_qa/fact(template, instructions, grade_pattern, include_history, partial_credit, model, model_role="grader", reducer="majority")`. A list of models becomes a majority-vote panel. No `config` argument: configure the grader model itself.
- `get_model("openai/<id>", config=GenerateConfig(temperature=0, seed=N, cache=CachePolicy(expiry=None, per_epoch=False)))`. `seed` is honoured by OpenAI, Google, Mistral, Groq, HF, vLLM, **not Anthropic**. Temperature 0 reduces but does not remove grade variance.
- Cache key = md5 of config (minus retry/timeout fields), messages, tools, base_url, expiry, scopes, and epoch if `per_epoch`. Stored under `$INSPECT_CACHE_DIR/generate` or `~/Library/Caches/inspect_ai/generate`. `ModelEvent.cache` records read/write.

### Agents
- `react(prompt, tools=[bash(), python(), text_editor()], attempts, submit, compaction, approval)`; `human_cli()` for human baselines; `as_solver(agent)`.
- `sandbox_agent_bridge(state, model, model_aliases, port=13131, ...)`: a loopback proxy in the default service relays OpenAI Completions/Responses, Anthropic and Google API calls to Inspect's model; every call becomes a `ModelEvent`. Generation params from the agent are dropped unless `forward_generation_config=True`. Provider-side web search bypasses `network_mode: none` unless disabled.
- Limits (`message_limit`, `token_limit`, `time_limit`, `working_limit`, `cost_limit`) end the sample early; the sample is still scored.

### Logs and viewer
- `.eval` logs (zip). `read_eval_log`, `read_eval_log_samples`, `list_eval_logs`. `EvalSample.events` holds `ModelEvent`, `ToolEvent`, `SandboxEvent` (exec/read_file/write_file), `ScoreEvent`, `SampleLimitEvent` and more.
- `inspect view`; `inspect view bundle --log-dir logs --output-dir www` → static site; the host must support HTTP range requests (GitHub Pages, S3, Netlify; not `python -m http.server`).

## 2. Claude Code and Codex CLI inside Inspect (`inspect-swe`)

Source: https://meridianlabs-ai.github.io/inspect_swe/, https://github.com/meridianlabs-ai/inspect_swe

- **Available.** `inspect_swe` exports `claude_code`, `codex_cli`, `gemini_cli`, `kimi_code`, `opencode`, `mini_swe_agent`, `antigravity`, plus interactive variants. Verified importable here: `from inspect_swe import claude_code, codex_cli`.
- **Install path:** the host downloads the CLI binary and verifies its checksum, then copies it into the sandbox (`/var/tmp/...`). The sandbox needs **no internet and no vendor key**. Linux x64/arm64, glibc or musl; no Node needed for either.
- **Model routing:** both point at the bridge (`ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` on loopback). "Any model" per the docs; all calls logged and counted. Known issue #177: `claude_code()` on a non-Anthropic model can fail with `unrecognized_model`; a `model_config=` workaround is unconfirmed.
- **Options we use:** `user`, `cwd`, `version` (pin; default `"auto"` silently uses a CLI already on PATH), `system_prompt`, `disallowed_tools=["WebSearch","WebFetch"]` (Claude Code), `web_search="disabled"`, `approval_policy="never"`, `sandbox_mode="danger-full-access"` (Codex). `resolve_agent_version()` pins "stable"/"latest" once for all samples.
- **Side effects to exclude from diffs:** Codex writes `.codex/` and `AGENTS.md` into `cwd`; Claude Code writes `.claude/skills` and `~/.claude/settings.json`.
- **Host requirements:** `openai` and `anthropic` packages installed (else "Model proxy process exited unexpectedly"); `curl` in the sandbox only for bridged tools.
- **Transcripts:** tool calls appear inside model outputs; no Inspect `ToolEvent`s, because the CLI runs its own tools.
- **Fallbacks:** `react()` with `bash()` + `text_editor()`, `opencode()`, `mini_swe_agent()`.

## 3. Mechanize's public writing (style and task criteria)

Sources: https://mechanize.work/what-working-here-is-like, https://www.mechanize.work/blog/the-upcoming-gpt-3-moment-for-rl, https://www.mechanize.work/blog/cheap-rl-tasks-will-waste-compute, https://www.mechanize.work/blog/how-to-fully-automate-software-engineering

- A task is "the equivalent of a take-home assessment for a coding agent": a prompt, room for a complex solution, and a grader or rubric that returns a number.
- "The ideal task has multiple different sources of difficulty, not just one." It should expose a real capability gap in frontier models.
- Grading mixes procedural tests ("reliable but force prompts to be overly prescriptive") with LLM rubrics (flexible, nondeterministic).
- A task fails if the grader checks something the model couldn't know (their example: a required query-parameter name) or if the prompt is ambiguous. They don't use the word "knowable"; the concept is theirs, the word is ours.
- Most effort goes into QA: failure modes from many sampled transcripts, so failures reflect the model and not the designer.
- Style: medium-length declarative sentences, first-person plural, few headings in essays, evidence as back-of-envelope arithmetic and concrete failure examples. Vocabulary: task, environment, grader, rubric, procedural tests, transcript, failure mode, QA, frontier models, reference implementation.

## 4. Prior art

| Benchmark | What's notable for this project |
|---|---|
| SWE-bench Verified | hidden FAIL_TO_PASS / PASS_TO_PASS tests applied after the run; samples with over-specific tests removed |
| Terminal-Bench 2.0 | one container per task, final-state test script, an oracle solution per task; v2.1 added anti-reward-hacking fixes |
| METR task standard / RE-Bench | agents could usually see the scorer; o3 reward-hacked every run of one task |
| ITBench (IBM) / ITBench-AA | SRE scenarios on Kubernetes with chaos faults; top score 47 % on held-out tasks |
| AIOpsLab (Microsoft) | orchestrator validates each agent action; mitigation graded on system state |
| SREGym | live problems with noise and metastable faults; checklist LLM judge, κ = 0.90 with experts |
| SRE-World (NeurIPS 2026) | faults appear only under sustained load; best pass@1 29 % |

## 5. Reward-hacking patterns and the defence used here

| Pattern | Defence in this project |
|---|---|
| Editing, deleting or skipping tests | hidden tests copied fresh into a separate grader container; per-test junit parsing, not exit codes |
| `conftest.py` / `sitecustomize` / import-time patching | `env -i`, `PYTHONSAFEPATH=1`, grader-owned `pytest.ini`, agent tests run as an unprivileged user |
| Special-casing the grader, reading the scorer | grader, hidden tests and profiles never in the sandbox; replay uses a different seed from the public profile |
| Mining git history | sandbox repo is a single squashed commit |
| Tampering a sandbox shared with the verifier | separate `grader` service; the DB is replayed from a snapshot; DDL logged server-side |
| Masking fixes (bigger pools, timeouts, more workers) | hidden 2× replay with counts and invariants; probes for each in taskqa |

Sources: ImpossibleBench (https://arxiv.org/abs/2510.20270), EvilGenie (https://arxiv.org/abs/2511.21654), METR (https://metr.org/blog/2025-06-05-recent-reward-hacking), Claude 3.7 Sonnet system card, OpenAI CoT monitoring (https://arxiv.org/abs/2503.11926).
