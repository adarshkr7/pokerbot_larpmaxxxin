"""Run one Codex review round on a feature plan and save the bug list next to the plan.

Run by whoever has Codex (needs the `codex` CLI, logged in):

    git pull
    python scripts/review.py agents/plans/F01_engine_skeleton.md
    git add agents/plans/reviews && git commit -m "F01 review round N" && git push

Codex runs read-only (it cannot change the repo) with the model and effort below, follows
agents/prompts/plan_review.md, and its final answer is written to
agents/plans/reviews/<plan>.round<N>.md, where N is the plan's next round number. Claude then pulls,
answers every bug in the plan's review log, and pushes the revised plan for the next round.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEWS = ROOT / "agents" / "plans" / "reviews"
MODEL = "gpt-6-astra"
EFFORT = "medium"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("plan", type=Path, help="path to agents/plans/Fnn_*.md")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--effort", default=EFFORT)
    args = p.parse_args()

    plan = args.plan.resolve()
    if not plan.is_file():
        raise SystemExit(f"no such plan: {plan}")
    codex = shutil.which("codex")
    if not codex:
        raise SystemExit("codex CLI not found on PATH")
    REVIEWS.mkdir(parents=True, exist_ok=True)
    done = [int(m.group(1)) for f in REVIEWS.glob(f"{plan.stem}.round*.md")
            if (m := re.search(r"\.round(\d+)\.md$", f.name))]
    rnd = max(done, default=0) + 1
    out = REVIEWS / f"{plan.stem}.round{rnd}.md"
    rel = plan.relative_to(ROOT).as_posix()
    prompt = (f"You are the reviewer in our plan review loop. Read agents/prompts/plan_review.md and follow it "
              f"exactly to review {rel}. This is ROUND {rnd}. Do not modify any files. Reply only in the "
              f"format the prompt specifies.")
    cmd = [codex, "exec", "-m", args.model, "-c", f'model_reasoning_effort="{args.effort}"',
           "-s", "read-only", "-C", str(ROOT), "--color", "never", "-o", str(out), prompt]
    print(f"reviewing {rel} (round {rnd}) with {args.model} / {args.effort} ...", flush=True)
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not out.exists() or not out.read_text(encoding="utf-8").strip():
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])
        out.unlink(missing_ok=True)
        raise SystemExit(f"codex failed (exit {proc.returncode}); nothing saved.\n{tail}")
    text = out.read_text(encoding="utf-8")
    verdict = re.search(r"VERDICT:\s*(.+)", text)
    print(f"saved {out.relative_to(ROOT).as_posix()}  ->  {verdict.group(1).strip() if verdict else 'no VERDICT line!'}")
    print("next: git add agents/plans/reviews && git commit -m \"review round\" && git push")


if __name__ == "__main__":
    sys.exit(main())
