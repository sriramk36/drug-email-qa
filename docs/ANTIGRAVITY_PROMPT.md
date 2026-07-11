# Antigravity task prompt

Paste the block below into Antigravity's Agent Manager as a new task,
pointed at a project folder containing the `mlr-pipeline/` files
(schema.py, brand_config.py, regulatory.py, llm_client.py,
generator.py, grader.py, pipeline.py, trace_logger.py,
analyze_traces.py, app.py, prompts/generator_system.md,
live-loop-demo.html, README.md, PRD.md, CODE_WALKTHROUGH.md).

This is written the way Antigravity expects a task brief: a concrete
goal, explicit context instead of assuming the agent will infer it,
and acceptance criteria the agent can verify itself across the editor,
terminal, and browser — producing an Artifact (walkthrough +
screenshots) as proof, rather than just claiming it's done. Run it in
**Agent-assisted** or **Review-driven** mode, not full autopilot, given
this touches a compliance-adjacent prototype.

---

```
GOAL
Extend the existing MLR draft pipeline in mlr-pipeline/ with an
event-driven trigger (Loop 3, in loop-engineering terms) so a brief
submission can kick off a pipeline run over HTTP instead of only via
the Streamlit form or the CLI smoke test — and get it running behind a
minimal deployment setup suitable for a DigitalOcean droplet.

CONTEXT — READ FIRST
- Read README.md, PRD.md, and CODE_WALKTHROUGH.md in this folder
  before writing any code. They explain the existing architecture and
  the reasoning behind specific decisions (e.g. why the grader is
  deterministic and not a second LLM call, why
  PipelineResult.approved_for_production is hard-coded False, why
  market/audience are free text resolved through regulatory.py).
  Preserve those decisions — don't "simplify" them away.
- The pipeline is: schema.py (data contracts) -> generator.py (LLM
  call, Loop 1) -> grader.py (9 deterministic rules, Loop 2) ->
  pipeline.py (orchestrates generate/grade/revise, max 3 iterations).
- Do not modify grader.py's rule logic or regulatory.py's word-boundary
  matching without flagging why in your plan first — that matching was
  fixed once already for a real substring false-positive bug (see
  CODE_WALKTHROUGH.md §4), don't reintroduce naive substring checks.

TASKS
1. Add a FastAPI app (new file: api.py) exposing:
   - POST /briefs -> accepts the same fields as CampaignBrief, runs
     run_pipeline() from pipeline.py, returns the PipelineResult as
     JSON (final_html, grade_report, iterations_used,
     approved_for_production — which must always be false).
   - GET /health -> basic liveness check.
   Use Pydantic's existing CampaignBrief model directly as the request
   body schema — do not redefine the fields.
2. Add a Dockerfile suitable for a small DigitalOcean droplet
   deployment: Python slim base image, install requirements.txt,
   expose the FastAPI port, run via uvicorn. Keep it minimal — this is
   a student prototype, not a production hardened image.
3. Add pytest tests under tests/ covering:
   - Each of the 9 grader rules, at least one passing and one failing
     case per rule.
   - The word-boundary regression case specifically: a market of "US"
     should NOT be satisfied by body text containing "focuses" or
     "discusses" (this exact bug was caught and fixed once — write the
     test so it can't silently regress).
   - An unrecognized market (e.g. "Narnia") producing a "warning"
     severity on reg_footer, not a blocking failure and not a pass.
   - pipeline.py's revision loop actually calling generator.revise()
     with only the failed items, using a fake/mock LLMClient (do not
     call a real API in tests).
4. Update README.md with instructions for running api.py locally and
   building/running the Docker image.

ACCEPTANCE CRITERIA — VERIFY THESE YOURSELF BEFORE REPORTING DONE
- `pytest` passes with zero failures. Show the terminal output.
- Start the API locally (uvicorn api:app), then from the browser or
  terminal actually POST a sample brief to /briefs (use the same
  sample as pipeline.py's __main__ block: UK, HCP, Dovato, "Pre-launch
  HIV treatment awareness", unbranded) against a mocked/fake LLM
  client if no real API key is configured in this environment — do not
  skip verification just because a real key isn't available; wire in
  a fake client the same way CODE_WALKTHROUGH.md and the existing
  tests do, so the endpoint's request/response shape is still proven
  end to end.
- Confirm the JSON response's approved_for_production field is false.
- `docker build` succeeds without errors.
- Produce a short walkthrough artifact summarizing what you built, any
  deviations from this brief and why, and the exact commands to run
  everything.

DO NOT
- Do not add LangChain, LangGraph, or any agent framework — the
  existing orchestration is a deliberately plain bounded loop
  (see CODE_WALKTHROUGH.md §8 for why). If you think a framework would
  genuinely help here, say so in your plan and wait for confirmation
  before adding a new dependency of that weight.
- Do not change approved_for_production to be computed from
  all_passed, or add any code path that could mark output as approved
  automatically. This must stay a human-only decision.
- Do not add real destination URLs, real logo image assets, or invent
  AE reporting details anywhere in generator.py or prompts/
  generator_system.md.
```

---

### Why this prompt is written this way

- **Front-loads context instead of letting the agent infer it.**
  Antigravity's own docs describe agents that "autonomously plan,
  execute, and verify" — that autonomy is only as good as the context
  you hand it. Pointing it at README/PRD/CODE_WALKTHROUGH first means
  its plan will reflect *your* architecture decisions, not its own
  defaults.
- **Verification is explicit and self-contained.** Antigravity's
  differentiator is agents that test their own work across editor,
  terminal, and browser before reporting back — so the acceptance
  criteria are written as things the agent can literally run and
  observe (pytest output, a live POST request, a successful docker
  build), not vague requirements it would have to interpret.
- **A "DO NOT" section, deliberately.** Agent-first tools are good at
  filling gaps you didn't specify — sometimes with a framework or
  abstraction you didn't want. Given this project's explicit
  no-LangChain/LangGraph stance and the hard-coded
  `approved_for_production=False` guardrail, it's worth being just as
  explicit about what *not* to change as what to build.
