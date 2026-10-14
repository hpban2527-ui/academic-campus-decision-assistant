import json
import time
from collections import defaultdict, deque
from itertools import combinations
from copy import deepcopy


# ## 1. Load sample data

with open("sample_catalog.json", "r", encoding="utf-8") as f:
    CATALOG = json.load(f)["courses"]

print(f"Loaded {len(CATALOG)} courses.")
for code, info in list(CATALOG.items())[:5]:
    print(f"  {code} - {info['name']} | prereq={info['prereq']} | coreq={info['coreq']}")


# ## 2. Direction 1: Prerequisite Graph
#
# ### 2.1 Transcript model
# Each course in a student transcript has one of 5 statuses:
# - `passed`      : already passed (counts as satisfied)
# - `exempt`      : waived / transferred (counts as satisfied)
# - `in_progress` : currently taking (NOT satisfied yet)
# - `failed`      : failed before (NOT satisfied)
# - `not_taken`   : never taken (NOT satisfied)

SATISFIED = {"passed", "exempt"}


class PrereqGraph:
    """Directed graph of course prerequisites + corequisites."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.adj = defaultdict(list)      # prereq -> [courses that need it]
        self.prereq = {c: list(info["prereq"]) for c, info in catalog.items()}
        self.coreq  = {c: list(info.get("coreq", [])) for c, info in catalog.items()}

        # Build adjacency from prereq edges only (coreq is not a hard edge)
        for c, info in catalog.items():
            for p in info["prereq"]:
                self.adj[p].append(c)

    def has_cycle(self):
        """Kahn's algorithm: if topo-sort visits fewer nodes than total -> cycle."""
        indeg = defaultdict(int)
        nodes = set(self.catalog)
        for u in self.adj:
            for v in self.adj[u]:
                indeg[v] += 1
        q = deque([n for n in nodes if indeg[n] == 0])
        seen = 0
        while q:
            u = q.popleft()
            seen += 1
            for v in self.adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        return seen != len(nodes)

    def topo_order(self):
        """Return a valid learning order (topological sort)."""
        indeg = defaultdict(int)
        nodes = set(self.catalog)
        for u in self.adj:
            for v in self.adj[u]:
                indeg[v] += 1
        q = deque([n for n in nodes if indeg[n] == 0])
        order = []
        while q:
            u = q.popleft()
            order.append(u)
            for v in self.adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        return order if len(order) == len(nodes) else None

    def can_take(self, course, transcript):
        missing_prereq = [p for p in self.prereq.get(course, [])
                          if transcript.get(p, "not_taken") not in SATISFIED]
        missing_coreq  = [c for c in self.coreq.get(course, [])
                          if transcript.get(c, "not_taken") not in SATISFIED]
        ok = len(missing_prereq) == 0
        return ok, missing_prereq, missing_coreq
        """
        - missing_prereq: blocking (must be satisfied before).
        - missing_coreq : soft warning (can be taken in parallel).
        """

# ### 2.2 Demo

g = PrereqGraph(CATALOG)

print("Has cycle?", g.has_cycle())
print("Topo order:", g.topo_order())


# Example transcript (student "An")
transcript = {
    "CSC10012": "passed",
    "CSC10004": "passed",
    "CSC10003": "in_progress",
    "CSC14003": "passed",
    "CSC14005": "failed",
}

print(f"\n")
for course in ["CSC10006", "CSC13002", "CSC14005", "CSC18001", "CSC12105"]:
    ok, mp, mc = g.can_take(course, transcript)
    print(f"Course {course}:")
    print(f"  Can take? {ok}")
    if mp:
        print(f"  Missing prereq (BLOCKING): {mp}")
    if mc:
        print(f"  Missing coreq  (can be parallel): {mc}")

# ## 3. Direction 2: Schedule Conflict Detection

class Section:
    """A course section = one scheduled class meeting."""

    def __init__(self, course, day, start, end, room=None):
        self.course = course
        self.day = day
        self.start = start
        self.end = end
        self.room = room

    def __repr__(self):
        return f"{self.course} ({self.day} {self.start}-{self.end})"

    def overlaps(self, other):
        return (self.day == other.day
                and self.start < other.end
                and other.start < self.end)

def detect_conflicts_bruteforce(sections):
    """O(n^2)
    simple but slow for large n.
    """
    return [(a, b) for a, b in combinations(sections, 2) if a.overlaps(b)]

def detect_conflicts_sweepline(sections):
    """
    O(n log n) 
    group by day, sort by start time, keep only active intervals while scanning.
    """
    conflicts = []
    by_day = defaultdict(list)
    for s in sections:
        by_day[s.day].append(s)
    for day, items in by_day.items():
        items.sort(key=lambda x: x.start)
        active = []
        for cur in items:
            active = [x for x in active if x.end > cur.start]
            for x in active:
                conflicts.append((x, cur))
            active.append(cur)
    return conflicts

SECTIONS = [
    Section("CSC10012", "Mon", 7, 9),
    Section("CSC10004", "Mon", 8, 11),
    Section("CSC10006", "Mon", 10, 12),
    Section("CSC14003", "Tue", 7, 10),
    Section("CSC14005", "Tue", 9, 11),
    Section("CSC18001", "Wed", 7, 9),
]

print("\n=== Brute-force conflicts ===")
for a, b in detect_conflicts_bruteforce(SECTIONS):
    print(f"  {a} <-> {b}")

print("=== Sweep-line conflicts ===")
for a, b in detect_conflicts_sweepline(SECTIONS):
    print(f"  {a} <-> {b}")

# Quick benchmark with 2000 random sections
import random
random.seed(0)
big = []
for i in range(2000):
    d = random.choice(["Mon", "Tue", "Wed", "Thu", "Fri"])
    s = random.randint(7, 15)
    e = s + random.randint(1, 3)
    big.append(Section(f"C{i}", d, s, e))

t0 = time.time(); detect_conflicts_bruteforce(big); t1 = time.time()
t2 = time.time(); detect_conflicts_sweepline(big);    t3 = time.time()
print(f"Brute-force: {t1-t0:.4f}s")
print(f"Sweep-line : {t3-t2:.4f}s")

# ## 4. Direction 3: What-if Simulation
# For this simulation, I design a simple rule-based system to check for violations of academic policies.:
#       (credit <=18, gpa >= 2.0, prereq satisfied)

RULES = {"max_credits": 18, "min_gpa": 2.0}

class Student:
    def __init__(self, name, gpa, transcript, planned):
        self.name = name
        self.gpa = gpa
        self.transcript = dict(transcript)  # {course_code: status}
        self.planned = list(planned)        # [course_code]

def check_constraints(student, catalog, graph):
    """Return list of violations for the given student state."""
    violations = []

    credits = sum(catalog[c]["credits"] for c in student.planned)
    if credits > RULES["max_credits"]:
        violations.append(f"Credit overload: {credits} > {RULES['max_credits']}")

    if student.gpa < RULES["min_gpa"]:
        violations.append(f"GPA too low: {student.gpa} < {RULES['min_gpa']}")

    # Prereq check — use transcript as if all planned courses are 'in_progress'
    simulated = dict(student.transcript)
    for c in student.planned:
        ok, mp, mc = graph.can_take(c, simulated)
        if not ok:
            violations.append(f"{c}: missing prereq {mp}")
        if mc:
            violations.append(f"{c}: coreq {mc} (can be parallel)")
        simulated[c] = "in_progress"

    return violations


def what_if(student, scenario_fn, catalog, graph):
    """Apply scenario on a copy of student, return (simulated_student, violations)."""
    sim = deepcopy(student)
    scenario_fn(sim)
    return sim, check_constraints(sim, catalog, graph)

base = Student(
    name="An",
    gpa=2.5,
    transcript={"CSC10012": "passed", "CSC10004": "passed", "CSC14003": "passed"},
    planned=["CSC10006"],
)


def sc_add_heavy(s):
    """Add 4 more courses — expect credit overload."""
    s.planned += ["CSC13002", "CSC14005", "CSC18001", "CSC10008"]


def sc_missing_prereq(s):
    """Try to take a course without its prereq."""
    s.planned.append("CSC18001")   # needs CSC14005 (which is not passed)


def sc_gpa_drop(s):
    """Simulate GPA dropping below threshold."""
    s.gpa = 1.8
    s.planned.append("CSC10006")


for i, sc in enumerate([sc_add_heavy, sc_missing_prereq, sc_gpa_drop], 1):
    sim, v = what_if(base, sc, CATALOG, g)
    print(f"--- Scenario {i}: {sc.__name__} ---")
    print("  Planned:", sim.planned, "| GPA:", sim.gpa)
    print("  Violations:", v or "None")
    print()