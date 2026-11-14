"""Terminal demo of the Business Developer Agent.

    .venv/bin/python -m bizdev --sample consulting               # demo company, interactive
    .venv/bin/python -m bizdev 1234560-4                         # PRH lookup (falls back to picking a sector)
    .venv/bin/python -m bizdev --sector retail --name "Shop Oy"
    .venv/bin/python -m bizdev --sample consulting --answers A,A --out needs.json       # non-interactive
    .venv/bin/python -m bizdev --sample consulting --answers neither \\
        --text "we can't find new customers" --remove no_sales_process.3 \\
        --add "Train the team in the new playbook" --priority company.1=learnable --out needs.json

With --answers the run is non-interactive: tasks are kept unless --remove / --edit / --add say otherwise."""

import argparse
import sys

from google.genai import errors as genai_errors

from .agent import BizDevAgent
from .sources import load_playbook, sample_companies


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def pick_number(prompt, n):
    while True:
        a = ask(prompt)
        if a.isdigit() and 1 <= int(a) <= n:
            return int(a) - 1
        print(f"  Enter a number from 1 to {n}.")


def warn(msg):
    print(f"! {msg}", file=sys.stderr)


# ---------- Steps ----------

def step_profile(agent, args, interactive):
    if args.sample is not None or args.sector or not args.business_id:
        if args.sample is None and not args.sector:
            args.sample = sample_companies()[0]["key"]
        return agent.profile(sample=args.sample, sector=args.sector, name=args.name, business_id=args.business_id)
    try:
        return agent.profile(business_id=args.business_id)
    except LookupError as e:
        warn(str(e))
        if not interactive:
            sys.exit("Give --sector to run without the registry.")
        sectors = list(load_playbook()["sectors"].items())
        for i, (_, label) in enumerate(sectors, 1):
            print(f"  {i}. {label}")
        sector = sectors[pick_number("Which sector are you in? ", len(sectors))][0]
        return agent.profile(business_id=args.business_id, sector=sector, name=args.name)


def step_diagnosis(agent, profile, args, interactive):
    d = agent.diagnose(profile)
    presets = [a for a in (args.answers or "").split(",") if a]
    while not d.done:
        if d.current_question:
            q = d.current_question
            print(f"\n{q.prompt}\n  A) {q.a.label}\n  B) {q.b.label}\n  N) Neither")
            if interactive:
                choice = ask("> ")
            elif presets:
                choice = presets.pop(0)
                print(f"> {choice}")
            else:
                sys.exit("--answers ran out while a question was open.")
            try:
                d = agent.answer(d, choice)
            except ValueError as e:
                print(f"  {e}")
        elif d.needs_text:
            print("\nIn one sentence, what is holding the business back?")
            text = ask("> ") if interactive else args.text
            if not text:
                sys.exit("No description given (use --text in non-interactive runs).")
            if not interactive:
                print(f"> {text}")
            d = agent.describe(d, text)
        elif d.needs_choice:
            print("\nWhich of these is closest?")
            for i, c in enumerate(d.choices, 1):
                print(f"  {i}. {c.name}: {c.current}")
            if interactive:
                d = agent.choose(d, d.choices[pick_number("> ", len(d.choices))].id)
            elif args.choose:
                d = agent.choose(d, args.choose)
            else:
                sys.exit("No single root cause matched the text; give --choose <root cause id>.")
    return d


def print_card(card):
    print()
    for i, t in enumerate(card.tasks, 1):
        tag = "" if t.origin == "playbook" else "  (your task)"
        print(f"  {i}. [{t.priority:<12}] {t.task}{tag}")


def edit_card_interactively(agent, card):
    help_text = ("Commands:  r N  remove task N   e N text  rewrite task N   a text  add a task\n"
                 "           p N must_have|learnable|nice_to_have   Enter = the tasks are right")
    print(help_text)
    while True:
        print_card(card)
        cmd = ask("> ")
        if not cmd:
            return card
        op, _, rest = cmd.partition(" ")
        num, _, text = rest.partition(" ")
        try:
            if op == "a":
                card = agent.edit(card, add=[rest])
                continue
            if not (num.isdigit() and 1 <= int(num) <= len(card.tasks)):
                print(help_text)
                continue
            task_id = card.tasks[int(num) - 1].id
            if op == "r":
                card = agent.edit(card, remove=[task_id])
            elif op == "e":
                card = agent.edit(card, edit={task_id: text})
            elif op == "p":
                card = agent.edit(card, priority={task_id: text.strip()})
            else:
                print(help_text)
        except ValueError as e:
            print(f"  {e}")


def edit_card_from_args(agent, card, args):
    priority = dict(p.split("=", 1) for p in args.priority)
    edit = dict(e.split("=", 1) for e in args.edit)
    # Priorities for added tasks (company.N) apply after they exist.
    known = {t.id for t in card.tasks}
    card = agent.edit(card, remove=args.remove, edit=edit, add=args.add,
                      priority={k: v for k, v in priority.items() if k in known})
    later = {k: v for k, v in priority.items() if k not in known}
    return agent.edit(card, priority=later) if later else card


def print_output(needs):
    print(f"\n=== Skills needed: {needs.need.name} ===")
    for t in needs.tasks:
        status = "" if t.status == "mapped" else f"  [{t.status}]"
        print(f"  [{t.priority:<12}] {t.task}{status}")
    print()
    for s in needs.skills:
        print(f"  [{s.priority:<12}] {s.label}  ({s.skillType}, {s.confidence})")
    if not needs.skills:
        print("  No ESCO skills yet.")


def main():
    parser = argparse.ArgumentParser(prog="python -m bizdev", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("business_id", nargs="?", help="Finnish Business ID, looked up in the PRH registry")
    parser.add_argument("--sample", nargs="?", const=sample_companies()[0]["key"],
                        help=f"demo company: {', '.join(s['key'] for s in sample_companies())}")
    parser.add_argument("--sector", help=f"skip the lookup: {', '.join(load_playbook()['sectors'])}")
    parser.add_argument("--name", help="company name (with --sector)")
    parser.add_argument("--answers", help="non-interactive A/B answers, e.g. A or neither,B")
    parser.add_argument("--text", help="non-interactive: the problem in one sentence, if no A/B option fits")
    parser.add_argument("--choose", help="non-interactive: root cause id if the text matches none clearly")
    parser.add_argument("--remove", action="append", default=[], help="task id to remove (repeatable)")
    parser.add_argument("--edit", action="append", default=[], help="TASK_ID=new text (repeatable)")
    parser.add_argument("--add", action="append", default=[], help="a task of your own (repeatable)")
    parser.add_argument("--priority", action="append", default=[], help="TASK_ID=must_have|learnable|nice_to_have")
    parser.add_argument("--offline", action="store_true", help="never map live; company tasks stay unmapped")
    parser.add_argument("--out", help="write the output (SkillRequirements JSON) here")
    args = parser.parse_args()
    interactive = not args.answers

    agent = BizDevAgent(live=not args.offline)
    for w in agent.warnings():  # before the company does any work
        warn(w)

    try:
        profile = step_profile(agent, args, interactive)
    except ValueError as e:
        sys.exit(str(e))
    print(f"\n{profile.name or 'Your company'} ({profile.business_id or 'no business ID'}), "
          f"sector: {load_playbook()['sectors'][profile.sector_family]}"
          + (f", {profile.age_band} old" if profile.age_band else ""))

    d = step_diagnosis(agent, profile, args, interactive)

    shift, ideas = agent.ideas(d)
    print(f"\n=== {shift.name} ===\nNow:    {shift.current}\nTarget: {shift.target}")
    if shift.benefit:
        print(f"Why:    {shift.benefit}")
    print()
    for i, idea in enumerate(ideas, 1):
        print(f"{i}. {idea.title}: {idea.why}\n   First step: {idea.first_step}")

    print("\nThe work this takes. Keep, remove, rewrite or add tasks.")
    if agent.live_reason():
        warn(f"Live mapping is off ({agent.live_reason()}): tasks you add or rewrite get no ESCO skills yet.")
    card = agent.task_card(d)
    try:
        card = edit_card_interactively(agent, card) if interactive else edit_card_from_args(agent, card, args)
    except ValueError as e:
        sys.exit(str(e))
    print_card(card)

    try:
        per_task = agent.map_tasks(card)
    except genai_errors.APIError as e:
        warn(f"Gemini request failed ({e}); continuing offline, your own tasks stay unmapped.")
        per_task = BizDevAgent(live=False).map_tasks(card)
    needs = agent.build_output(profile, d, card, per_task)
    print_output(needs)
    if args.out:
        needs.save(args.out)
        print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
