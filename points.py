"""Point allocation shared by applicants and employers.

Both sides get POINT_BUDGET points to spread over ESCO skills:
  - applicant: "where am I strongest?"       (at most applicant.MAX_SKILLS skills)
  - employer:  "what matters most for this job?"
Skills with 0 points are dropped, so spending points is also how skills are chosen.
The same rules apply in the terminal and in the web API (via check_allocation).
"""

POINT_BUDGET = 10


def check_allocation(points, budget=POINT_BUDGET, max_skills=None):
    """points: list of ints, one per chosen skill. Raises ValueError with a readable message."""
    if not points:
        raise ValueError("put points on at least one skill")
    if any(p < 1 for p in points):
        raise ValueError("every chosen skill needs at least 1 point")
    if max_skills and len(points) > max_skills:
        raise ValueError(f"put points on at most {max_skills} skills (got {len(points)})")
    total = sum(points)
    if total != budget:
        raise ValueError(f"spend exactly {budget} points (got {total})")


def parse_allocation(text, n):
    """'1:4 3:3 5:2 8:1' -> {0: 4, 2: 3, 4: 2, 7: 1} (0-based index -> points)."""
    result = {}
    for part in text.replace(",", " ").split():
        if ":" not in part:
            raise ValueError(f"'{part}' is not in the form number:points")
        idx, pts = part.split(":", 1)
        if not (idx.isdigit() and pts.isdigit()):
            raise ValueError(f"'{part}' is not in the form number:points")
        i, p = int(idx) - 1, int(pts)
        if not 0 <= i < n:
            raise ValueError(f"there is no skill number {idx}")
        if i in result:
            raise ValueError(f"skill {idx} is listed twice")
        if p > 0:
            result[i] = p
    return result


def allocate_in_terminal(lines, budget=POINT_BUDGET, max_skills=None, intro=""):
    """Show numbered lines, ask for 'n:points' pairs until the allocation is valid.
    Returns {index: points}."""
    print(f"\n{intro}" if intro else "")
    for i, line in enumerate(lines, 1):
        print(f"  {i:>2}. {line}")
    limit = f" on at most {max_skills} skills" if max_skills else ""
    print(f"\nSpread exactly {budget} points{limit}. Skills you give 0 points are left out.")
    print("Write number:points pairs, e.g. 1:4 3:3 5:2 8:1")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            raise SystemExit("No allocation given.")
        try:
            allocation = parse_allocation(text, len(lines))
            check_allocation(list(allocation.values()), budget, max_skills)
            return allocation
        except ValueError as e:
            print(f"  {e}. Try again.")


def points_bar(points, budget=POINT_BUDGET):
    return "#" * points + "." * (budget - points)
