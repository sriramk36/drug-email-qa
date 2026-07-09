# Code Walkthrough — Pharma Marketing Draft Pipeline

This explains *why* each file exists and *how* the pieces fit together —
not just what the code does, but the reasoning behind each decision, so
you can defend every choice if your client or an interviewer asks.

---

## 1. The core idea: two loops, not one AI call

A single LLM call producing a "final" marketing email is a demo. What
makes this a *pipeline* is that the output is never trusted on the
first try — it's mechanically checked, and specific failures are fed
back for a second attempt. That's the whole concept from the LangChain
article you sent, reduced to its essence:

```
Loop 1 (generator/agent loop):  brief → LLM → HTML
Loop 2 (verification loop):     HTML → rule engine → pass/fail list
                                 fail? → feed failures back into Loop 1
```

Everything below is either building Loop 1, building Loop 2, or wiring
them together.

---

## 2. `schema.py` — the data contracts

```python
class CampaignBrief(BaseModel):
    channel: Channel
    email_type: Optional[EmailType] = None
    market: str          # free text now — was an enum, see §7
    audience: str         # free text now — was an enum
    brand: str
    objective: str
    classification: ContentClassification   # still a controlled enum, deliberately
```

**Why Pydantic:** it validates shape at the boundary (e.g. `channel`
must be `"email"` or `"web"`, nothing else) so nothing downstream has
to defensively check "did I get a sane object." One `BaseModel`
definition, and Streamlit's form, the CLI smoke test, and the grader
all agree on what a brief looks like.

**Why `classification` stayed an enum while market/audience didn't:**
`unbranded` vs `branded` isn't descriptive metadata — it's a fork in
the actual logic. `rule_brand_leak` and `rule_pi_link_if_branded`
branch on it directly. Market and audience, by contrast, only need to
be *interpreted* (which regulatory tag does "United Kingdom" imply?),
not branched on structurally — so they became strings, and
`regulatory.py` does the interpretation. If a field changes what code
path runs, keep it a closed enum. If a field only changes what content
gets checked for, free text plus a resolver is more flexible and just
as safe.

`GradeItem` / `GradeReport` — a rule produces a `GradeItem` (id, human
label, pass/fail, explanation, and a `severity` of `"blocking"` or
`"warning"`). `GradeReport.all_passed` only looks at blocking items —
this is what lets an unrecognized market produce an honest "I don't
know" warning instead of either a false pass or an unfair hard fail.

---

## 3. `brand_config.py` — visual + compliance tokens per brand

```python
BRAND_TOKENS = {
    "Dovato": { "primary": "#D4007A", "ae_report_line": "...", ... },
    ...
}
DEFAULT_TOKENS = { "ae_report_line": "[INSERT ... TBC ...]", ... }
```

Two things worth noticing:

1. **The AE reporting line is dictated, not generated.** The LLM is
   told to embed this string *verbatim*. That's the single most
   important design decision in the whole system — it means the
   Generator is never inventing a phone number or a reporting URL. It
   also means the Grader can check for an exact substring instead of
   asking "does this AE line sound plausible," which would be a much
   weaker check.
2. **`DEFAULT_TOKENS` uses `[TBC]`-style placeholders as the actual AE
   line.** For an unrecognized brand, the "real" AE line the LLM
   embeds verbatim literally says "TBC with local regulatory team."
   That's not a bug — an unknown brand *should* produce a visible TBC
   marker, not a confidently wrong guess.

---

## 4. `regulatory.py` — free-text interpretation layer

This is the file that exists specifically *because* you asked for text
inputs instead of dropdowns. Two functions:

```python
def resolve_market(market_text: str) -> dict:
    # "United Kingdom" → {"tags": ["ABPI"], "known": True, "aliases": [...]}
    # "Narnia"         → {"tags": [], "known": False, "aliases": [...]}

def is_hcp_audience(audience_text: str) -> bool:
    # "Prescribing nurses" → True (contains "nurse")
    # "Payers"             → False
```

**The word-boundary bug I caught and fixed while building this:** the
first version matched aliases with plain substring checks (`"us" in
text`). That's wrong — `"us"` is a substring of "foc**us**es" and
"disc**us**ses". Pharma copy about patient outcomes is full of words
like that. I switched every alias check to `\bword\b` regex matching.
I mention this because it's a good concrete example of why you test a
compliance tool against adversarial-ish input before trusting it — a
demo running only on the "happy path" (US market brief containing the
literal word "US") would never have surfaced this.

**Why unknown markets are `"warning"`, not silently `True` or a hard
`False`:** a silent pass would be actively dangerous (claiming ABPI
compliance for a market the tool has never heard of). A hard blocking
fail would punish the pipeline for something it's honestly uncertain
about, and would make "type a market not in the demo list" look like a
crash instead of a known limitation. Warning is the honest middle:
"I can't verify this — a human needs to look."

---

## 5. `llm_client.py` — provider-agnostic LLM wrapper

```python
class LLMClient:
    def __init__(self):
        if AZURE_AI_FOUNDRY_* env vars set: use openai.OpenAI(base_url=azure_endpoint)
        elif ANTHROPIC_API_KEY set: use anthropic.Anthropic()
```

Azure AI Foundry's chat completions endpoint speaks the same wire
protocol as OpenAI's API, so pointing the standard `openai` Python SDK
at your Azure endpoint just works — no Azure-specific SDK needed. This
is the same GPT-4o-mini deployment pattern from your Orbit SDR project.
Nothing else in the codebase imports `openai` or `anthropic` directly —
only this file does, which is what makes swapping providers a one-file
change.

---

## 6. `generator.py` — Loop 1

Two functions, `generate()` and `revise()`. The interesting part is
what `revise()` sends:

```python
def revise(brief, previous_html, grade_report, client):
    failed = grade_report.failed_items
    failure_list = "\n".join(f"- [{i.rule_id}] {i.label}: {i.detail}" for i in failed)
    # ...sends previous_html + failure_list, asks for a PATCH not a rewrite
```

It does **not** start from scratch on a failed attempt. It hands back
the exact previous draft plus only the specific rules that failed, and
asks for a patch. This matters for two reasons: it's cheaper (less to
regenerate), and it's more stable — a full regeneration risks fixing
the AE box while accidentally breaking the audience tag that passed
last time. Patch-not-rewrite is the same instinct as a real code
review: "fix these two comments" beats "rewrite the PR."

---

## 7. `grader.py` — Loop 2, and why it's not another LLM call

Nine rule functions, all with the identical signature
`(soup, raw_html, brief, tokens) -> GradeItem`, collected in
`ALL_RULES` and run in `grade()`. A few worth walking through:

**`_visible_body_text()`** — selects `.email-content`, then removes
any nested `.annotation-wrap` before extracting text. This is the
function that makes the branded/unbranded check meaningful: the brand
name is *allowed* to appear in the internal audit footer (production
team needs to know what they're building), just never in what a
recipient would actually read. I validated this against your real
`DOVATO-UK-EMAIL-2026-004.html` — it correctly found the file
unbranded (product name only in the annotation, never the visible
body) before I'd told it anything about that specific file.

**`rule_ae_box()`** checks three independent things — a real CSS
border, the phrase "adverse event," and the first 25 characters of the
brand's exact AE line — and only passes if all three hold. Checking
all three instead of just one avoids two failure modes: a model that
writes "please report adverse events" with no visible box (passes
text-search, fails visually), or a model that adds a border around
unrelated content (passes visually, says nothing useful).

**Why rules return an explanation string, not just a boolean.** A bare
`False` tells you something's wrong; `i.detail` tells a human
reviewer *what* and *where*, without them having to read the whole
HTML diff themselves. That detail string is also what gets fed back
into `revise()` — the Generator doesn't get "audience_tag: failed," it
gets "Body copy does not clearly state this is for UK healthcare
professionals only," which is specific enough to act on directly.

---

## 8. `pipeline.py` — wiring Loop 1 to Loop 2

```python
html = generate(brief, client)
report = grade(html, brief, tokens, iteration=1)
while not report.all_passed and iteration < MAX_ITERATIONS:
    iteration += 1
    html = revise(brief, html, report, client)
    report = grade(html, brief, tokens, iteration=iteration)
return PipelineResult(..., approved_for_production=False)
```

`MAX_ITERATIONS = 3` is a circuit breaker — without it, a
badly-specified brief (e.g. a brand token that contradicts the market)
could loop forever, burning API calls. Three is arbitrary but
reasonable: if a draft hasn't converged in three attempts, that's a
signal the *prompt* needs fixing, not that a fourth attempt would help
— which is exactly what `analyze_traces.py` is for.

`approved_for_production=False` is hard-coded, not computed from
`all_passed`. This is the one line in the whole codebase I'd flag as
non-negotiable: passing every structural check is not the same claim
as "an MLR reviewer signed off on the clinical accuracy and fair
balance of this specific copy." Never let a future version of this
script (or someone skimming it under deadline pressure) quietly wire
`all_passed` into an auto-send button.

---

## 9. `trace_logger.py` + `analyze_traces.py` — the lightweight Loop 4

Every grading pass appends one line of JSON — brand, market, audience,
iteration number, which rules failed — to `traces.jsonl`.
`analyze_traces.py` then aggregates: which rule fails most often on
*first* attempts, across every run you've ever done. That's a
prioritized, data-backed list of what to fix in
`prompts/generator_system.md` next, instead of guessing from the last
run you happened to look at. This is a lightweight version of what the
LangChain article calls the hill-climbing loop — real loop-engineering
setups usually pair this with an eval harness and scheduled re-runs;
this version is intentionally the minimum useful slice of that idea.

---

## 10. `app.py` — Streamlit UI

The only thing worth calling out here versus the pipeline files: it
doesn't call `run_pipeline()` as one opaque function anymore (an
earlier version did). It inlines the generate→grade→revise loop
directly so it can call `st.status()`/`ui_log()` after *every*
individual step — generation, each of the 9 rule results, each
revision — instead of only showing a result at the very end. That's
the same "detailed logs and steps" request you made for the browser
demo, applied to the Python side too.

---

## 11. `live-loop-demo.html` — the browser version, and where it differs from Python

This exists to prove the loop is real without you needing to export
credentials or run anything locally. It's a **faithful but scoped-down
port**, not a separate implementation:

| | Python (`grader.py`, `regulatory.py`) | Browser (`live-loop-demo.html`) |
|---|---|---|
| Grading logic | `BeautifulSoup` + regex | `DOMParser` + regex — same 9 rules, same word-boundary alias matching, ported 1:1 |
| Generator output | Full desktop+mobile split mockup, unbounded length | Compact single-column draft, hard-capped at 1000 output tokens (artifact sandbox limit) |
| LLM call | Your Azure AI Foundry / Anthropic key, server-side | Anthropic API, browser-side, handled automatically by the artifact runtime — no key needed from you |
| Persistence | `traces.jsonl` on disk | None — resets on refresh |
| UI feedback | Terminal `print()` / Streamlit `st.status()` | Live stepper (5 pipeline stages) + scrolling log with real token counts per call |

The reason the two can't be fully identical: an artifact-embedded API
call is capped at 1000 output tokens by the platform, and your actual
templates run 20–28KB of HTML. Cramming a full split-screen
desktop/mobile mockup into that budget isn't possible — so the
in-browser system prompt explicitly asks for a compact single view
instead. The *loop mechanics* (generate → grade → feed back specific
failures → regenerate) are identical; only the fidelity of what gets
generated differs.

**What "detailed logs" means in the updated version specifically:**
- A 5-stage stepper (`resolve → generate → grade → revise → verdict`)
  that highlights the currently-running stage.
- Every log line is timestamped, and includes real numbers from the
  API response (`input_tokens`/`output_tokens`/`stop_reason`) — those
  numbers don't exist unless a real model call happened.
- Brand-token and market resolution are logged explicitly *before* the
  first generation call, so you can see "Dovato → known token set" or
  "Narnia → unrecognized, reg_footer will be a warning" up front,
  rather than only finding out when a check fails later.
- The full system + user prompt sent on the final call is available in
  a collapsible panel, so you can see exactly what the model was asked
  for, not just what it returned.

---

## 12. Why free text instead of dropdowns changes more than the UI

Converting market/audience/brand from `<select>`/enum to `<input
type="text">`/`str` looks like a UI change but touches four files:
`schema.py` (type change), `regulatory.py` (new — the resolution
layer didn't need to exist when inputs were closed enums),
`grader.py` (two rules rewritten to use the resolver instead of enum
equality), and `trace_logger.py` (dropped `.value` calls on fields
that are no longer enums). That cascade is normal — a closed set of
inputs lets you skip writing an interpretation layer; opening the
input back up means something has to do that interpretation, and it's
better for that something to be one small, testable module
(`regulatory.py`) than scattered `if "uk" in text.lower()` checks
throughout the codebase.
