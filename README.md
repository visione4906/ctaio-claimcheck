# claimcheck

**Your agent wrote your README. Who checked it?**

Agentic coding has a quiet failure mode. The agent ships the code, then writes the
docs, then writes the release notes, and somewhere in there it starts describing
the system it *meant* to build. Nobody greps. The claim survives. It ends up in your
README, your changelog, your pitch, your CV.

`claimcheck` is the guardrail: it takes a document full of claims and a codebase, and
makes an **independent** agent prove each claim against the source, with file:line
citations, or refuse.

```bash
python claimcheck.py --claims example/claims.md --repo ../horror-shorts-pipeline
echo $?   # non-zero if anything is an OVERCLAIM -> drop it in CI and it becomes a gate
```

---

## Why it exists

This week an independent reviewer caught five overclaims in **my own CV**, including
a line saying a product had a paying customer when that product had exactly zero. I'd
written it. I'd read it a dozen times. It took a second agent, one that hadn't written
it and owed it nothing, to grep the repo and say: *no.*

The rule I now can't work without: **never let the thing that wrote the claim be the
thing that checks it.** `claimcheck` is that rule as a CLI.

---

## The five design decisions

These are the interesting part. The code is 150 lines; the decisions are the tool.

**1. No self-grading.** A *fresh* `claude -p` is spawned per claim, with no memory of
the authoring context and no sight of the other claims. Independence isn't a nice-to-have
here, it's the entire product. An agent grading its own output is a rubber stamp.

**2. Deterministic retrieval, LLM only for judgement.** `ripgrep` gathers the evidence:
fast, exhaustive, free, reproducible. The model never chooses what it gets to look at;
it only adjudicates claim-vs-evidence. Keeping the LLM on the one job it's actually
good at is the difference between a pipeline and a vibe.

**3. Fail closed.** No file:line evidence -> the verdict **cannot** be `TRUE`. If the
model returns `TRUE` with an empty evidence array, `claimcheck` overrides it to
`UNVERIFIABLE`. The model does not get the last word on that one. A false `TRUE` is
the only failure that actually costs you anything. It is the one that survives into
production prose.

**4. Zero credentials.** It shells out to the already-authenticated **Claude Code CLI**
instead of taking an `ANTHROPIC_API_KEY`. Nothing to configure, nothing to leak, no key
in a `.env` waiting to be committed. This started as a constraint (no local API key)
and ended up the better architecture, and the one that matches how this audience already
works.

**5. Machine-readable, exit-coded.** JSON out, non-zero exit on any overclaim. A report
you read once is a blog post. An exit code is a gate.

---

## What a real run looks like

Eight claims about [`horror-shorts-pipeline`](https://github.com/visione4906/horror-shorts-pipeline)
(a public repo of mine). Some true, some are the kind of thing an agent writes when it's
being helpful rather than correct. `claimcheck` isn't told which is which.

```
OVERCLAIM     The pipeline uses a Postgres database for job state
              why: The only database evidence points to SQLite (`jobs.sqlite`), and there
                   is not a single line mentioning Postgres, psycopg, or a Postgres
                   connection string.
              ref: tests/test_yt_upload.py:30
              say: The pipeline stores job state in a SQLite database (`jobs.sqlite`).

UNVERIFIABLE  The project includes a RAG pipeline over a vector store for script retrieval
              why: No line mentions a vector store, embeddings, retrieval, or RAG.
              say: The project includes a script-generation pipeline that prompts Claude
                   from seed titles; no retrieval-augmented generation is evidenced.

TRUE          Jobs move through a state machine with named states like scripted and posted
              ref: tests/test_db.py:23

1 true | 1 OVERCLAIM | 6 unverifiable
```

Full output: [`sample-run.txt`](sample-run.txt).

**Read that scoreboard carefully. It is the most honest thing here.** Only one claim
came back `TRUE`. Several claims that *are* actually true (SQLite, FFmpeg) came back
`UNVERIFIABLE`, because the grep evidence showed them in tests and docs but not in the
pipeline's own source. That's not a bug I'd paper over. A tool like this is only worth
running if it is **more willing to say "I can't prove that" than to say "looks fine"**.
The day it starts flattering you is the day it's useless.

---

## Limitations (the honest list)

- **Retrieval is lexical.** ripgrep on content-words. A claim phrased in words that
  don't appear in the code will come back `UNVERIFIABLE` even if it's true. Fixing this
  properly means embeddings, which means an API key, which kills decision #4, so it
  stays lexical, and it stays conservative. That trade is deliberate.
- **It is conservative by construction.** Expect `UNVERIFIABLE` a lot. That's the point.
- **One process per claim.** Fine for a README. Slow for a book.

## Install

Needs Python 3.9+, [`ripgrep`](https://github.com/BurntSushi/ripgrep), and the
[Claude Code CLI](https://claude.com/claude-code) already logged in. No API key.

```bash
git clone https://github.com/visione4906/ctaio-claimcheck
cd ctaio-claimcheck
python claimcheck.py --claims example/claims.md --repo /path/to/any/repo
```

MIT.
