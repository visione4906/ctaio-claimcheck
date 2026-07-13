#!/usr/bin/env python3
"""claimcheck - verify the claims in a doc against the code that is supposed to back them.

Agents write confident READMEs. The claims drift from the code, and nobody notices
until a user (or an interviewer) checks. claimcheck is the guardrail:

  1. ripgrep finds the evidence           (deterministic, exhaustive, free)
  2. a FRESH `claude -p` adjudicates      (never saw the claim being written)
  3. no file:line evidence -> not TRUE    (fail closed)

Usage:
  python claimcheck.py --claims example/claims.md --repo /path/to/repo
  echo $?   # non-zero if any OVERCLAIM -> use it as a CI gate
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# On Windows `claude` is an npm .cmd shim, and CreateProcess will not resolve it from
# a bare name the way a shell would. Resolve it once, explicitly, and fail loudly if
# it is missing - rather than shelling out with shell=True and inheriting that whole
# class of quoting bugs.
CLAUDE_BIN = shutil.which("claude") or shutil.which("claude.cmd")

# Words that carry no search signal. Keeping this list short and dumb on purpose:
# the LLM is not doing retrieval, ripgrep is, and ripgrep does not need to be clever.
STOP = set("""a an the is are was were be been has have had it its this that these those
of in on at to for with and or but if then than as by from we our you your i my
use uses used using it's dont don't can could would should will shall may might
system code project repo repository runs run running built build builds""".split())

RUBRIC = """You are an INDEPENDENT verifier. You did NOT write this claim and you owe it nothing.

CLAIM:
{claim}

EVIDENCE (every line ripgrep found in the codebase for this claim's keywords):
{evidence}

Decide, using ONLY the evidence above:
- TRUE          the evidence directly supports the claim
- OVERCLAIM     the evidence contradicts it, or supports something materially weaker
- UNVERIFIABLE  the evidence does not settle it either way

RULES (these are the whole point of this tool):
- If there is no file:line evidence for it, you CANNOT return TRUE. Fail closed.
- If you are unsure, you are NOT sure. Return UNVERIFIABLE or OVERCLAIM, never TRUE.
- A false TRUE is the only failure that actually costs the user something, because
  it is the one that survives into their README, their CV, or a customer call.
- Cite file:line. An assertion with no citation is not evidence.

Reply with ONLY a JSON object, no prose, no fences:
{{"verdict":"TRUE|OVERCLAIM|UNVERIFIABLE","evidence":["path:line"],"reason":"one sentence","honest_rewrite":"the claim as it could HONESTLY be stated, or null if TRUE"}}"""


def parse_claims(path: Path) -> list[str]:
    """One claim per bullet or non-empty line. Headings and fences are not claims."""
    claims = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("```"):
            continue
        claims.append(re.sub(r"^[-*+]\s+", "", s))
    return claims


def keywords(claim: str) -> list[str]:
    """Content words only. Longest first - the rare word is the one worth grepping."""
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_.\-]{2,}", claim.lower())
    seen, out = set(), []
    for w in sorted(words, key=len, reverse=True):
        if w in STOP or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out[:6]


def gather_evidence(claim: str, repo: Path, per_kw: int = 4) -> str:
    """DETERMINISTIC retrieval. The model does not get to decide what it looked at."""
    hits: list[str] = []
    for kw in keywords(claim):
        try:
            r = subprocess.run(
                ["rg", "-i", "--no-heading", "--line-number", "--max-count", str(per_kw),
                 "--glob", "!node_modules", "--glob", "!.git", "--glob", "!*.lock", kw, str(repo)],
                capture_output=True, text=True, timeout=20,
                # Windows defaults to cp1252 here and dies on the first UTF-8 byte a
                # repo happens to contain. Decode explicitly; never let a stray byte
                # take the whole run down.
                encoding="utf-8", errors="replace",
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        for line in (r.stdout or "").splitlines()[:per_kw]:
            line = line.strip()
            if not line:
                continue
            try:  # rg prints ABSOLUTE path here; make it repo-relative and readable
                p, ln, text = line.split(":", 2)
                line = f"{Path(p).relative_to(repo).as_posix()}:{ln}: {text.strip()[:160]}"
            except (ValueError, TypeError):
                line = line[:200]
            if line not in hits:
                hits.append(line)
    return "\n".join(hits[:40]) if hits else "(ripgrep found nothing for this claim's keywords)"


def adjudicate(claim: str, evidence: str) -> dict:
    """A FRESH agent per claim. No shared context, no memory of the other claims,
    and critically: not the agent that wrote the claim. Independence is the feature."""
    prompt = RUBRIC.format(claim=claim, evidence=evidence)
    try:
        r = subprocess.run([CLAUDE_BIN, "-p"], input=prompt, capture_output=True,
                           text=True, timeout=180, shell=False,
                           encoding="utf-8", errors="replace")
        raw = (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return {"verdict": "UNVERIFIABLE", "evidence": [], "reason": "verifier timed out", "honest_rewrite": None}

    m = re.search(r"\{.*\}", raw, re.S)  # models garnish. take the object, ignore the garnish.
    if not m:
        return {"verdict": "UNVERIFIABLE", "evidence": [], "reason": "verifier returned no JSON", "honest_rewrite": None}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"verdict": "UNVERIFIABLE", "evidence": [], "reason": "verifier returned malformed JSON", "honest_rewrite": None}

    # FAIL CLOSED. The model does not get the last word on this one.
    if d.get("verdict") == "TRUE" and not d.get("evidence"):
        d["verdict"] = "UNVERIFIABLE"
        d["reason"] = "claimed TRUE with no file:line evidence - downgraded by claimcheck"
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify a doc's claims against the code that backs them.")
    ap.add_argument("--claims", required=True, type=Path)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--json", type=Path, default=Path("claimcheck.json"))
    a = ap.parse_args()

    if not CLAUDE_BIN:
        print("claimcheck: `claude` not on PATH. This tool uses the Claude Code CLI as the\n"
              "verifier on purpose - no API key to configure, nothing to leak.", file=sys.stderr)
        return 2

    claims = parse_claims(a.claims)
    print(f"claimcheck: {len(claims)} claims against {a.repo}\n", flush=True)

    results = []
    for i, claim in enumerate(claims, 1):
        print(f"[{i}/{len(claims)}] {claim[:70]}...", flush=True)
        d = adjudicate(claim, gather_evidence(claim, a.repo))
        d["claim"] = claim
        results.append(d)

    print("\n" + "=" * 78)
    for r in results:
        print(f"\n{r['verdict']:<13} {r['claim']}")
        print(f"              why: {r.get('reason','')}")
        for e in (r.get("evidence") or [])[:3]:
            print(f"              ref: {e}")
        if r.get("honest_rewrite"):
            print(f"              say: {r['honest_rewrite']}")

    bad = [r for r in results if r["verdict"] == "OVERCLAIM"]
    unv = [r for r in results if r["verdict"] == "UNVERIFIABLE"]
    print("\n" + "=" * 78)
    print(f"{len(results)-len(bad)-len(unv)} true | {len(bad)} OVERCLAIM | {len(unv)} unverifiable")
    a.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {a.json}")
    return 1 if bad else 0  # non-zero on overclaim -> drop it in CI and it becomes a gate


if __name__ == "__main__":
    sys.exit(main())
