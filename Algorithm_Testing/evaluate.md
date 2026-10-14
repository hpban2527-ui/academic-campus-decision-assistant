# Feasibility Notes — 3 Directions

## 1. Prerequisite Graph

**Algorithm chosen:** Topological sort (Kahn's algorithm) — O(V + E).

**Alternatives:**
| Algorithm | Pros | Cons |
|---|---|---|
| Kahn (BFS-based) | Easy to detect cycles, iterative | Needs indegree array |
| DFS-based topo sort | Short code | Cycle detection less obvious |

**Chosen because:** Kahn’s algorithm can detect cycles and produce a topological order; this prototype implements them as two separate methods. Easy to explain and debug.

**Feasibility:** HIGH.
- Data available (official prereq list exists).
- Visualization can be added later with NetworkX / Graphviz.

**Limitations & future work:**
- Transcript model uses 5 statuses (`passed / exempt / in_progress / failed / not_taken`)
  mapped into 2 groups (satisfied / not satisfied). This is enough to test
  logic but ignores minimum grade requirements (e.g. must score ≥ 5.0).
- **Corequisite** is modelled as a soft warning (can be taken in parallel),
  but the prototype does not enforce "must be registered in the same term".
- No priority / recommendation logic — only yes/no.

---

## 2. Schedule Conflict Detection

**Algorithm chosen:** Sweep line per day — O(n log n).

**Alternatives:**
| Algorithm | Pros | Cons |
|---|---|---|
| Brute-force O(n²) | Trivial to write | Slow when n > few hundred |
| Sweep line O(n log n + k) (k is the number of conflicting pairs) | Fast, simple enough | Needs sorting per day |
| Interval tree | O(log n + k) query | Overkill for this size |

**Chosen because:** with ~2000 sections the sweep line is noticeably faster
than brute-force (see benchmark cell). Code is still short.

**Feasibility:** HIGH.
- Simple interval overlap condition.
- No external library needed.
- Can be integrated directly into a registration UI.

**Limitations:**
- Only detects pairwise overlap. Does not optimize the whole timetable
  (that would need ILP / CP-SAT / graph coloring).
- Does not account for travel time between rooms or exam schedules.

---

## 3. What-if Simulation

**Algorithm chosen:** Constraint checking — O(n) per scenario.

**Alternatives:**
| Algorithm | Pros | Cons |
|---|---|---|
| Constraint checking | Simple, fast for few rules | Doesn't scale with complex rules |
| CP-SAT (OR-Tools) | Handles complex constraints | Heavy dependency, slower setup |
| Rule engine (Drools) | Declarative, extensible | Overkill for prototype |

**Chosen because:** rules in this prototype are simple (credits, GPA,
prereq). Constraint checking is enough to demonstrate the idea.

**Feasibility:** MEDIUM.
- Depends on Directions 1 already working (reuses their logic).
- Needs a clear rule design before scaling.
- Copy-on-write via `deepcopy` keeps the original state intact.

**Limitations:**
- No probabilistic simulation (e.g. chance of passing a course).
- No optimization (e.g. "find the best plan") — only validation.

**Future direction: AI-based optimization**

Current `what_if()` only validates constraints (yes/no).
To make it "smart", 3 options:

| Approach | Pros | Cons | Fits prototype? |
|---|---|---|---|
| CP-SAT (OR-Tools) | Optimal plan, explainable | Extra dependency | ⚠️ Needs setup |
| ML recommender | Personalized | Needs large historical data | ❌ No data yet |
| LLM interface | Natural language UX | Cost, latency, not deterministic | ⚠️ Nice to have |

Recommendation: start with CP-SAT if optimization is needed,
add LLM later for UX. ML recommender requires data collection first.

---

## Overall Conclusion

| Direction | Difficulty | Feasibility | Priority |
|---|---|---|---|
| Prerequisite Graph | ⭐⭐ | HIGH | 1 |
| Schedule Conflict | ⭐ | HIGH | 1 |
| What-if Simulation | ⭐⭐⭐ | MEDIUM | 2 |

**Recommended order:**
1. Build Prerequisite Graph + Schedule Conflict first (MVP).
2. Layer What-if Simulation on top once the prerequisite checks are stable.