import random
import webbrowser
import threading
from collections import deque
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

GRID_SIZE  = 4
START_POS  = (4, 1)
DIRECTIONS = [(-1, 0), (0, 1), (1, 0), (0, -1)]
DIR_NAMES  = ["North", "East", "South", "West"]
DIR_ARROWS = ["↑", "→", "↓", "←"]

class WumpusWorld:
    def __init__(self, seed=None):
        if seed is not None:
            random.seed(seed)
        self._place_objects()
        self._build_percept_maps()
        self._init_agent_state()

    def _place_objects(self):
        all_cells = [(r, c) for r in range(1, GRID_SIZE+1) for c in range(1, GRID_SIZE+1)]
        non_start = [cell for cell in all_cells if cell != START_POS]
        self.wumpus_pos   = random.choice(non_start)
        self.wumpus_alive = True
        gold_choices = [c for c in non_start if c != self.wumpus_pos]
        self.gold_pos = random.choice(gold_choices)
        self.pits = set()
        for cell in all_cells:
            if cell in (START_POS, self.wumpus_pos, self.gold_pos):
                continue
            if random.random() < 0.20:
                self.pits.add(cell)

    def _build_percept_maps(self):
        self.breezes = set()
        self.stenches = set()
        for (r, c) in self.pits:
            for dr, dc in DIRECTIONS:
                nb = (r + dr, c + dc)
                if self._in_bounds(nb):
                    self.breezes.add(nb)
        wr, wc = self.wumpus_pos
        for dr, dc in DIRECTIONS:
            nb = (wr + dr, wc + dc)
            if self._in_bounds(nb):
                self.stenches.add(nb)

    def _init_agent_state(self):
        self.agent_pos    = START_POS
        self.agent_dir    = 1
        self.has_arrow    = True
        self.has_gold     = False
        self.score        = 0
        self.alive        = True
        self.won          = False
        self.visited      = {START_POS}
        self.step_count   = 0
        self.scream_heard = False

    def _in_bounds(self, pos):
        r, c = pos
        return 1 <= r <= GRID_SIZE and 1 <= c <= GRID_SIZE

    def get_neighbors(self, pos):
        r, c = pos
        return [(r+dr, c+dc) for dr, dc in DIRECTIONS
                if self._in_bounds((r+dr, c+dc))]

    def get_percepts(self, pos=None):
        if pos is None:
            pos = self.agent_pos
        return {
            "breeze":  pos in self.breezes,
            "stench":  pos in self.stenches,
            "glitter": (pos == self.gold_pos and not self.has_gold),
            "scream":  self.scream_heard,
            "bump":    False,
        }

    def action_move_forward(self):
        self.score -= 1
        self.step_count += 1
        dr, dc = DIRECTIONS[self.agent_dir]
        nr, nc = self.agent_pos[0] + dr, self.agent_pos[1] + dc
        if not self._in_bounds((nr, nc)):
            return {**self.get_percepts(), "bump": True, "event": "bump"}
        self.agent_pos = (nr, nc)
        self.visited.add(self.agent_pos)
        self.scream_heard = False
        if self.agent_pos in self.pits:
            self.alive = False
            self.score -= 1000
            return {**self.get_percepts(), "event": "fell_in_pit"}
        if self.wumpus_alive and self.agent_pos == self.wumpus_pos:
            self.alive = False
            self.score -= 1000
            return {**self.get_percepts(), "event": "eaten_by_wumpus"}
        return {**self.get_percepts(), "event": "moved"}

    def action_turn_left(self):
        self.score -= 1
        self.step_count += 1
        self.agent_dir = (self.agent_dir - 1) % 4
        return {**self.get_percepts(), "event": "turned_left"}

    def action_turn_right(self):
        self.score -= 1
        self.step_count += 1
        self.agent_dir = (self.agent_dir + 1) % 4
        return {**self.get_percepts(), "event": "turned_right"}

    def action_grab(self):
        self.score -= 1
        self.step_count += 1
        if self.agent_pos == self.gold_pos and not self.has_gold:
            self.has_gold = True
            self.score += 1000
            return {**self.get_percepts(), "event": "gold_grabbed"}
        return {**self.get_percepts(), "event": "grab_failed"}

    def action_shoot(self):
        self.score -= 10
        self.step_count += 1
        if not self.has_arrow:
            return {**self.get_percepts(), "event": "no_arrow"}
        self.has_arrow = False
        dr, dc = DIRECTIONS[self.agent_dir]
        r, c = self.agent_pos
        while True:
            r += dr; c += dc
            if not self._in_bounds((r, c)):
                break
            if (r, c) == self.wumpus_pos and self.wumpus_alive:
                self.wumpus_alive = False
                self.scream_heard = True
                self.stenches.clear()
                return {**self.get_percepts(), "event": "wumpus_killed"}
        return {**self.get_percepts(), "event": "arrow_missed"}

    def action_climb(self):
        self.step_count += 1
        if self.agent_pos == START_POS and self.has_gold:
            self.won = True
            self.score += 500
            return {**self.get_percepts(), "event": "won"}
        return {**self.get_percepts(), "event": "climb_failed"}


class KnowledgeBase:
    def __init__(self):
        self.kb_safe    = {START_POS}
        self.kb_pit     = set()
        self.kb_wumpus  = set()
        self.log        = []

    def add_log(self, msg):
        self.log.append(msg)
        if len(self.log) > 300:
            self.log.pop(0)

    def update(self, pos, percepts, neighbors):
        no_breeze = not percepts["breeze"]
        no_stench = not percepts["stench"]
        unknown = [nb for nb in neighbors
                   if nb not in self.kb_safe
                   and nb not in self.kb_pit
                   and nb not in self.kb_wumpus]
        if no_breeze and no_stench:
            for nb in neighbors:
                if nb not in self.kb_safe:
                    self.kb_safe.add(nb)
                    self.add_log(f"✓ SAFE: {nb} (no percepts at {pos})")
        if percepts["breeze"]:
            pit_candidates = [nb for nb in neighbors
                              if nb not in self.kb_safe and nb not in self.kb_pit]
            if len(pit_candidates) == 1:
                cell = pit_candidates[0]
                self.kb_pit.add(cell)
                self.kb_safe.discard(cell)
                self.add_log(f"🕳 PIT confirmed: {cell}")
        if percepts["stench"]:
            wumpus_candidates = [nb for nb in neighbors
                                 if nb not in self.kb_safe and nb not in self.kb_wumpus]
            if len(wumpus_candidates) == 1:
                cell = wumpus_candidates[0]
                self.kb_wumpus.add(cell)
                self.kb_safe.discard(cell)
                self.add_log(f"👾 WUMPUS confirmed: {cell}")
        if percepts["scream"]:
            self.kb_wumpus.clear()
            self.add_log("📢 Scream heard — Wumpus is dead!")

    def is_safe(self, cell):
        return cell in self.kb_safe and cell not in self.kb_pit and cell not in self.kb_wumpus

    def is_deadly(self, cell):
        return cell in self.kb_pit or cell in self.kb_wumpus


class WumpusAgent:
    def __init__(self, world: WumpusWorld):
        self.world   = world
        self.kb      = KnowledgeBase()
        self.path    = deque()
        self.returning = False
        self._sense_and_update(START_POS)

    def _sense_and_update(self, pos):
        w = self.world
        percepts  = w.get_percepts(pos)
        neighbors = w.get_neighbors(pos)
        self.kb.update(pos, percepts, neighbors)
        info = []
        if percepts["breeze"]:  info.append("BREEZE")
        if percepts["stench"]:  info.append("STENCH")
        if percepts["glitter"]: info.append("GLITTER")
        if percepts["scream"]:  info.append("SCREAM")
        if not info:            info.append("silence")
        self.kb.add_log(f"📍 At {pos}: [{', '.join(info)}]")

    def _bfs_path(self, start, goal):
        queue   = deque([[start]])
        visited = {start}
        while queue:
            path = queue.popleft()
            curr = path[-1]
            if curr == goal:
                return path[1:]
            for nb in self.world.get_neighbors(curr):
                if nb not in visited and self.kb.is_safe(nb):
                    visited.add(nb)
                    queue.append(path + [nb])
        return []

    def _nearest_unvisited_safe(self):
        pos     = self.world.agent_pos
        visited = self.world.visited
        candidates = [
            c for c in self.kb.kb_safe
            if c not in visited
            and not self.kb.is_deadly(c)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda c: abs(c[0]-pos[0]) + abs(c[1]-pos[1]))
        return candidates[0]

    def _teleport_move(self, target):
        w = self.world
        w.agent_pos = target
        w.visited.add(target)
        w.score -= 1
        w.step_count += 1
        if target in w.pits:
            w.alive = False
            w.score -= 1000
            self.kb.add_log(f"💀 Agent fell into PIT at {target}!")
        elif w.wumpus_alive and target == w.wumpus_pos:
            w.alive = False
            w.score -= 1000
            self.kb.add_log(f"💀 Agent eaten by WUMPUS at {target}!")
        else:
            self._sense_and_update(target)

    def step(self):
        w  = self.world
        kb = self.kb
        pos = w.agent_pos
        if not w.alive or w.won:
            return None, "Game over."
        percepts = w.get_percepts(pos)
        if percepts["glitter"] and not w.has_gold:
            w.action_grab()
            self.returning = True
            self.path = deque(self._bfs_path(pos, START_POS))
            kb.add_log("🥇 Gold grabbed! Planning return path.")
            return "grab", f"Grabbed GOLD at {pos}!"
        if w.has_gold and pos == START_POS:
            w.action_climb()
            kb.add_log("🏆 Climbed out of cave — VICTORY!")
            return "climb", "Climbed out with Gold — WON!"
        if self.path:
            next_cell = self.path.popleft()
            self._teleport_move(next_cell)
            return "move", f"Path step → {next_cell}"
        goal = self._nearest_unvisited_safe()
        if goal:
            path = self._bfs_path(pos, goal)
            if path:
                self.path = deque(path)
                next_cell = self.path.popleft()
                self._teleport_move(next_cell)
                return "move", f"Exploring safe cell → {next_cell}"
        if w.has_arrow and kb.kb_wumpus:
            w_target = list(kb.kb_wumpus)[0]
            kb.add_log(f"🏹 Shooting at confirmed Wumpus {w_target}")
            result = w.action_shoot()
            if result["event"] == "wumpus_killed":
                kb.kb_wumpus.clear()
                for nb in w.get_neighbors(w_target):
                    kb.kb_safe.add(nb)
                return "shoot", f"Arrow hit! Wumpus at {w_target} killed!"
            return "shoot", "Arrow missed."
        risky = [nb for nb in w.get_neighbors(pos)
                 if nb not in kb.kb_pit
                 and nb not in kb.kb_wumpus
                 and nb not in w.visited]
        if risky:
            next_cell = random.choice(risky)
            kb.add_log(f"⚠️ No safe moves — taking risk to {next_cell}")
            self._teleport_move(next_cell)
            return "risky", f"⚠️ Risky move → {next_cell}"
        kb.add_log("🚩 Agent stuck — returning to start.")
        self.returning = True
        path = self._bfs_path(pos, START_POS)
        if path:
            self.path = deque(path)
            next_cell = self.path.popleft()
            self._teleport_move(next_cell)
            return "move", f"Stuck — returning → {next_cell}"
        return None, "Completely stuck. No moves possible."


world = None
agent = None

def new_game(seed=None):
    global world, agent
    world = WumpusWorld(seed=seed)
    agent = WumpusAgent(world)

new_game()


def get_state():
    w  = world
    kb = agent.kb
    grid = []
    for r in range(1, GRID_SIZE+1):
        row = []
        for c in range(1, GRID_SIZE+1):
            pos     = (r, c)
            visited = pos in w.visited
            cell = {
                "pos":          [r, c],
                "visited":      visited,
                "is_agent":     pos == w.agent_pos,
                "is_wumpus":    pos == w.wumpus_pos,
                "wumpus_alive": w.wumpus_alive,
                "is_gold":      pos == w.gold_pos and not w.has_gold,
                "is_pit":       pos in w.pits,
                "has_breeze":   pos in w.breezes,
                "has_stench":   pos in w.stenches,
                "kb_safe":      pos in kb.kb_safe,
                "kb_pit":       pos in kb.kb_pit,
                "kb_wumpus":    pos in kb.kb_wumpus,
            }
            row.append(cell)
        grid.append(row)
    return {
        "grid":           grid,
        "agent_pos":      list(w.agent_pos),
        "agent_dir":      DIR_ARROWS[w.agent_dir],
        "agent_dir_name": DIR_NAMES[w.agent_dir],
        "score":          w.score,
        "step_count":     w.step_count,
        "has_arrow":      w.has_arrow,
        "has_gold":       w.has_gold,
        "wumpus_alive":   w.wumpus_alive,
        "alive":          w.alive,
        "won":            w.won,
        "percepts":       w.get_percepts(),
        "kb_log":         kb.log[-60:],
    }


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)

@app.route("/state")
def state():
    return jsonify(get_state())

@app.route("/step", methods=["POST"])
def step():
    action, desc = agent.step()
    s = get_state()
    s["last_action"] = action
    s["last_desc"]   = desc
    return jsonify(s)

@app.route("/new_game", methods=["POST"])
def reset():
    new_game()
    return jsonify(get_state())

@app.route("/reveal", methods=["POST"])
def reveal():
    for r in range(1, GRID_SIZE+1):
        for c in range(1, GRID_SIZE+1):
            world.visited.add((r, c))
    return jsonify(get_state())


HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Wumpus World — AI Solver</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=JetBrains+Mono:wght@400;600;700&family=Rajdhani:wght@400;600;700&display=swap" rel="stylesheet"/>
<style>
/* ══════════════════════════════════════════════
   RESET & ROOT VARIABLES
══════════════════════════════════════════════ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  /* Core palette — amber/ember theme */
  --bg:       #0c0b08;
  --bg2:      #11100c;
  --panel:    #141210;
  --panel2:   #1a1714;
  --border:   #2a2520;
  --border2:  #3a3028;

  /* Accent colors */
  --amber:    #f59e0b;
  --amber2:   #fbbf24;
  --amber3:   #fde68a;
  --ember:    #ef4444;
  --teal:     #14b8a6;
  --teal2:    #2dd4bf;
  --lime:     #84cc16;
  --lime2:    #a3e635;
  --violet:   #8b5cf6;
  --violet2:  #a78bfa;
  --rose:     #f43f5e;
  --sky:      #0ea5e9;

  /* Text */
  --text:     #e8dcc8;
  --text2:    #9a8870;
  --text3:    #5a4e3a;

  /* Fonts */
  --display:  'Bebas Neue', sans-serif;
  --ui:       'Rajdhani', sans-serif;
  --mono:     'JetBrains Mono', monospace;

  /* Cell size — updated by JS */
  --cw: 140px;
  --ch: 140px;
}

html, body {
  height: 100%;
  background: var(--bg);
  color: var(--text);
  font-family: var(--ui);
  overflow: hidden;
}

body {
  display: grid;
  grid-template-rows: auto auto 1fr auto;
  height: 100vh;
}

/* ══════════════════════════════════════════════
   SCROLLBAR GLOBAL
══════════════════════════════════════════════ */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

/* ══════════════════════════════════════════════
   HEADER
══════════════════════════════════════════════ */
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 58px;
  background: linear-gradient(180deg, #1a1510 0%, var(--bg) 100%);
  border-bottom: 2px solid #2a2010;
  position: relative;
  overflow: hidden;
}
header::before {
  content: '';
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    90deg,
    transparent,
    transparent 120px,
    rgba(245,158,11,0.02) 120px,
    rgba(245,158,11,0.02) 121px
  );
  pointer-events: none;
}

.logo-group {
  display: flex;
  align-items: baseline;
  gap: 16px;
}
.logo {
  font-family: var(--display);
  font-size: 2rem;
  letter-spacing: 6px;
  color: var(--amber);
  text-shadow: 0 0 40px rgba(245,158,11,0.4), 0 2px 0 rgba(0,0,0,0.8);
  line-height: 1;
}
.logo em {
  color: var(--teal2);
  font-style: normal;
}
.logo-sub {
  font-family: var(--mono);
  font-size: 0.65rem;
  color: var(--amber2);
  letter-spacing: 3px;
  text-transform: uppercase;
  text-shadow: 0 0 18px rgba(245,158,11,0.45);
  opacity: 0.9;
}
.header-badge {
  display: flex;
  gap: 8px;
  align-items: center;
}
.badge {
  font-family: var(--mono);
  font-size: 0.58rem;
  padding: 4px 10px;
  border-radius: 2px;
  letter-spacing: 1px;
  background: var(--panel2);
  border: 1px solid var(--border2);
  color: var(--text2);
}
.badge.highlight {
  border-color: var(--amber);
  color: var(--amber);
  background: rgba(245,158,11,0.08);
}

/* ══════════════════════════════════════════════
   STATUS BANNER
══════════════════════════════════════════════ */
#statusBanner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 40px;
  font-family: var(--display);
  font-size: 1.1rem;
  letter-spacing: 8px;
  border-bottom: 1px solid var(--border);
  transition: all 0.4s ease;
  position: relative;
  overflow: hidden;
}
#statusBanner::before {
  content: '';
  position: absolute;
  inset: 0;
  opacity: 0.06;
  background: linear-gradient(90deg, transparent 0%, currentColor 50%, transparent 100%);
  animation: shimmer 3s ease-in-out infinite;
}
@keyframes shimmer { 0%,100% { opacity: 0.03; } 50% { opacity: 0.08; } }

.sb-exploring { background: #0d0f0b; color: var(--teal2); border-color: #1a3028; }
.sb-returning { background: #0f0d07; color: var(--amber2); border-color: #3a2808; }
.sb-won       { background: #0f0d04; color: var(--amber3); border-color: #5a4400;
                animation: wonPulse 1.2s ease-in-out infinite; }
.sb-dead      { background: #0f0808; color: var(--rose); border-color: #5a1820; }
@keyframes wonPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }

/* ══════════════════════════════════════════════
   WORKSPACE — 3 COLUMNS
══════════════════════════════════════════════ */
.workspace {
  display: grid;
  grid-template-columns: 230px 1fr 300px;
  overflow: hidden;
  min-height: 0;
}

/* ══════════════════════════════════════════════
   LEFT PANEL
══════════════════════════════════════════════ */
.col-left {
  background: var(--panel);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
}

/* ══════════════════════════════════════════════
   CENTER — GRID AREA
══════════════════════════════════════════════ */
.col-center {
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(ellipse 60% 60% at 50% 50%, #1a1408 0%, var(--bg) 100%);
  padding: 12px;
  position: relative;
  overflow: hidden;
}
.col-center::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(245,158,11,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(245,158,11,0.03) 1px, transparent 1px);
  background-size: 30px 30px;
  pointer-events: none;
}

/* ══════════════════════════════════════════════
   RIGHT PANEL
══════════════════════════════════════════════ */
.col-right {
  background: var(--panel);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ══════════════════════════════════════════════
   SECTION BLOCKS
══════════════════════════════════════════════ */
.sec {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.sec-title {
  font-family: var(--display);
  font-size: 0.85rem;
  letter-spacing: 4px;
  color: var(--amber);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sec-title::before {
  content: '';
  width: 3px;
  height: 14px;
  background: var(--amber);
  border-radius: 2px;
  flex-shrink: 0;
}
.sec-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--border2) 0%, transparent 100%);
}

/* ══════════════════════════════════════════════
   STATS GRID
══════════════════════════════════════════════ */
.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}
.stat-box {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px 10px;
  position: relative;
  overflow: hidden;
}
.stat-box::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 2px;
  background: var(--amber);
  opacity: 0.2;
}
.stat-label {
  font-family: var(--mono);
  font-size: 0.5rem;
  color: var(--text3);
  letter-spacing: 2px;
  margin-bottom: 3px;
}
.stat-value {
  font-family: var(--display);
  font-size: 1.1rem;
  letter-spacing: 2px;
  line-height: 1;
}
.sv-amber  { color: var(--amber2); }
.sv-teal   { color: var(--teal2); }
.sv-lime   { color: var(--lime2); }
.sv-rose   { color: var(--rose); }
.sv-violet { color: var(--violet2); }
.sv-dim    { color: var(--text2); }

.stat-full { grid-column: span 2; }

/* ══════════════════════════════════════════════
   PERCEPTS
══════════════════════════════════════════════ */
.percept-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}
.percept {
  font-family: var(--ui);
  font-size: 0.78rem;
  font-weight: 700;
  padding: 8px 6px;
  border-radius: 4px;
  text-align: center;
  letter-spacing: 1px;
  border: 1px solid transparent;
  transition: all 0.25s;
}
.percept.off    { background: var(--bg2); color: var(--text3); border-color: var(--border); }
.on-breeze      { background: rgba(14,165,233,0.12); color: #38bdf8; border-color: rgba(14,165,233,0.3); box-shadow: 0 0 10px rgba(14,165,233,0.1); }
.on-stench      { background: rgba(239,68,68,0.12); color: #f87171; border-color: rgba(239,68,68,0.3); box-shadow: 0 0 10px rgba(239,68,68,0.1); }
.on-glitter     { background: rgba(245,158,11,0.15); color: var(--amber2); border-color: rgba(245,158,11,0.4); box-shadow: 0 0 10px rgba(245,158,11,0.15); }
.on-scream      { background: rgba(139,92,246,0.15); color: var(--violet2); border-color: rgba(139,92,246,0.4); box-shadow: 0 0 10px rgba(139,92,246,0.15); }

/* ══════════════════════════════════════════════
   LEGEND
══════════════════════════════════════════════ */
.legend-items {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 5px 10px;
}
.leg {
  display: flex;
  align-items: center;
  gap: 7px;
  font-family: var(--ui);
  font-size: 0.75rem;
  color: var(--text2);
  font-weight: 600;
}
.leg-icon { font-size: 1.1rem; width: 22px; text-align: center; }
.leg-dot {
  width: 10px; height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}

/* ══════════════════════════════════════════════
   BUTTONS
══════════════════════════════════════════════ */
.btn-stack { display: flex; flex-direction: column; gap: 8px; }

button {
  font-family: var(--display);
  font-size: 0.95rem;
  letter-spacing: 3px;
  padding: 11px 14px;
  border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  width: 100%;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 10px;
  position: relative;
  overflow: hidden;
}
button::after {
  content: '';
  position: absolute;
  inset: 0;
  background: rgba(255,255,255,0);
  transition: background 0.15s;
}
button:hover::after { background: rgba(255,255,255,0.04); }
button:active { transform: scale(0.98); }

.btn-step {
  background: rgba(14,165,233,0.1);
  color: #38bdf8;
  border-color: rgba(14,165,233,0.25);
}
.btn-step:hover { background: rgba(14,165,233,0.18); border-color: rgba(14,165,233,0.5); }

.btn-auto {
  background: rgba(132,204,22,0.1);
  color: var(--lime2);
  border-color: rgba(132,204,22,0.25);
}
.btn-auto:hover { background: rgba(132,204,22,0.18); border-color: rgba(132,204,22,0.5); }

.btn-stop {
  background: rgba(244,63,94,0.1);
  color: var(--rose);
  border-color: rgba(244,63,94,0.25);
}

.btn-reveal {
  background: rgba(245,158,11,0.08);
  color: var(--amber2);
  border-color: rgba(245,158,11,0.2);
}
.btn-reveal:hover { background: rgba(245,158,11,0.14); }

.btn-new {
  background: rgba(139,92,246,0.1);
  color: var(--violet2);
  border-color: rgba(139,92,246,0.25);
}
.btn-new:hover { background: rgba(139,92,246,0.18); }

.speed-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  font-family: var(--mono);
  font-size: 0.62rem;
  color: var(--text3);
}
input[type=range] {
  flex: 1;
  accent-color: var(--amber);
  height: 3px;
  cursor: pointer;
}
.speed-val {
  color: var(--amber2);
  font-weight: 700;
  min-width: 44px;
}

/* ══════════════════════════════════════════════
   LOG
══════════════════════════════════════════════ */
.log-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 14px 18px 12px;
  min-height: 0;
}
.log-inner {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 10px 12px;
  font-family: var(--mono);
  font-size: 0.68rem;
  line-height: 1.9;
  min-height: 0;
}
.log-line { padding: 0; }
.log-line.safe    { color: var(--lime2); }
.log-line.pit     { color: var(--violet2); }
.log-line.wumpus  { color: #fb923c; }
.log-line.move    { color: var(--teal2); }
.log-line.warn    { color: var(--rose); }
.log-line.win     { color: var(--amber2); font-weight: 700; }
.log-line.info    { color: var(--text2); }

/* ══════════════════════════════════════════════
   GRID
══════════════════════════════════════════════ */
.grid-outer {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  position: relative;
  z-index: 1;
}

.grid-label-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.axis-spacer { width: 28px; }
.axis-lbl {
  width: var(--cw);
  text-align: center;
  font-family: var(--display);
  font-size: 1rem;
  letter-spacing: 4px;
  color: #8a7a60;
  text-shadow: 0 0 10px rgba(245,158,11,0.2);
  font-weight: 700;
}

.grid-body { display: flex; flex-direction: column; gap: 4px; }
.grid-row-wrap { display: flex; align-items: center; gap: 4px; }
.row-lbl {
  width: 34px;
  text-align: right;
  font-family: var(--display);
  font-size: 1rem;
  letter-spacing: 2px;
  color: #8a7a60;
  text-shadow: 0 0 10px rgba(245,158,11,0.2);
  font-weight: 700;
  padding-right: 5px;
}
.grid-row { display: flex; gap: 4px; }

/* ── Individual Cells ── */
.cell {
  width: var(--cw);
  height: var(--ch);
  position: relative;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  transition: all 0.3s ease;
  border: 1px solid var(--border);
  cursor: default;
}

/* Fog */
.cell.fog {
  background: #0d0c09;
  border-color: #1a1810;
}
.cell.fog:hover { background: #121108; }
.fog-mark {
  font-size: 1.6rem;
  color: #1e1c14;
}

/* Visited states */
.cell.c-visited  { background: #131108; border-color: #2a2818; }
.cell.c-safe     { background: #0c1408; border-color: #1a2a10; }
.cell.c-agent {
  background: #0d1a22;
  border: 2px solid var(--teal2);
  box-shadow: 0 0 20px rgba(20,184,166,0.25), inset 0 0 20px rgba(20,184,166,0.08);
}
.cell.c-dead {
  background: #1a0808;
  border-color: #5a1010;
  box-shadow: inset 0 0 20px rgba(239,68,68,0.1);
}

/* Percept overlays */
.cell.has-breeze::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at 50% 50%, rgba(56,189,248,0.07) 0%, transparent 70%);
  pointer-events: none;
}
.cell.has-stench::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at 50% 50%, rgba(248,113,113,0.08) 0%, transparent 70%);
  pointer-events: none;
}

/* Cell coordinate */
.coord {
  position: absolute;
  top: 6px; left: 7px;
  font-family: var(--mono);
  font-size: 0.72rem;
  font-weight: 700;
  color: #887a62;
  line-height: 1;
  letter-spacing: 0.5px;
  text-shadow: 0 1px 4px rgba(0,0,0,0.8);
}

/* Cell icons */
.cell-icons {
  font-size: 2rem;
  line-height: 1;
  z-index: 2;
  filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5));
}

/* KB tags */
.cell-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  justify-content: center;
  margin-top: 4px;
  z-index: 2;
}
.ctag {
  font-family: var(--mono);
  font-size: 0.52rem;
  padding: 2px 5px;
  border-radius: 2px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.ct-breeze  { background: rgba(56,189,248,0.15); color: #38bdf8; }
.ct-stench  { background: rgba(248,113,113,0.15); color: #f87171; }
.ct-safe    { background: rgba(132,204,22,0.15);  color: var(--lime2); }
.ct-pit     { background: rgba(139,92,246,0.15);  color: var(--violet2); }
.ct-wumpus  { background: rgba(249,115,22,0.15);  color: #fb923c; }

/* Agent direction indicator */
.agent-dir-badge {
  position: absolute;
  bottom: 5px; right: 6px;
  font-size: 1.1rem;
  color: var(--teal2);
  text-shadow: 0 0 8px rgba(20,184,166,0.5);
}

/* START cell marker */
.start-badge {
  position: absolute;
  top: 5px; right: 6px;
  font-family: var(--display);
  font-size: 0.52rem;
  color: var(--amber);
  letter-spacing: 1px;
  opacity: 0.6;
}

/* ══════════════════════════════════════════════
   FOOTER
══════════════════════════════════════════════ */
footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  height: 34px;
  border-top: 1px solid var(--border);
  background: var(--panel);
  flex-shrink: 0;
  overflow: hidden;
}
.member {
  font-family: var(--mono);
  font-size: 0.58rem;
  color: var(--text3);
  padding: 0 14px;
  border-right: 1px solid var(--border);
  white-space: nowrap;
  line-height: 1;
}
.member:last-child { border-right: none; }
.member b { color: var(--text2); }
.member.lead b { color: var(--amber); }
</style>
</head>
<body>

<!-- ══ HEADER ══ -->
<header>
  <div class="logo-group">
    <div class="logo">⚀ WUMPUS <em>WORLD</em></div>
    <div class="logo-sub">4×4 GRID · KNOWLEDGE-BASED AI SOLVER</div>
  </div>
</header>

<!-- ══ STATUS BANNER ══ -->
<div id="statusBanner" class="sb-exploring">
  <span id="statusDot">◈</span>
  <span id="statusText">EXPLORING</span>
</div>

<!-- ══ WORKSPACE ══ -->
<div class="workspace">

  <!-- LEFT -->
  <div class="col-left">

    <div class="sec">
      <div class="sec-title">GAME STATUS</div>
      <div class="stat-grid">
        <div class="stat-box">
          <div class="stat-label">SCORE</div>
          <div class="stat-value sv-amber" id="score">0</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">STEPS</div>
          <div class="stat-value sv-dim" id="steps">0</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">POSITION</div>
          <div class="stat-value sv-teal" id="pos">(4,1)</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">FACING</div>
          <div class="stat-value sv-teal" id="facing">→ E</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">ARROW</div>
          <div class="stat-value sv-lime" id="arrow">READY</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">GOLD</div>
          <div class="stat-value sv-amber" id="gold">NO</div>
        </div>
        <div class="stat-box stat-full">
          <div class="stat-label">WUMPUS</div>
          <div class="stat-value sv-rose" id="wumpus">⚠ ALIVE</div>
        </div>
      </div>
    </div>

    <div class="sec">
      <div class="sec-title">PERCEPTS</div>
      <div class="percept-grid">
        <div class="percept off" id="p-breeze">🌬 BREEZE</div>
        <div class="percept off" id="p-stench">🔴 STENCH</div>
        <div class="percept off" id="p-glitter">✨ GLITTER</div>
        <div class="percept off" id="p-scream">📢 SCREAM</div>
      </div>
    </div>

    <div class="sec">
      <div class="sec-title">LEGEND</div>
      <div class="legend-items">
        <div class="leg"><span class="leg-icon">🤖</span>Agent</div>
        <div class="leg"><span class="leg-icon">👾</span>Wumpus</div>
        <div class="leg"><span class="leg-icon">🕳</span>Pit</div>
        <div class="leg"><span class="leg-icon">✨</span>Gold</div>
        <div class="leg"><span class="leg-dot" style="background:#38bdf8"></span><span style="color:#38bdf8">Breeze</span></div>
        <div class="leg"><span class="leg-dot" style="background:#f87171"></span><span style="color:#f87171">Stench</span></div>
        <div class="leg"><span class="leg-dot" style="background:#a3e635"></span><span style="color:#a3e635">KB Safe</span></div>
        <div class="leg"><span class="leg-dot" style="background:#a78bfa"></span><span style="color:#a78bfa">KB Pit?</span></div>
        <div class="leg"><span class="leg-dot" style="background:#fb923c"></span><span style="color:#fb923c">KB Wumpus?</span></div>
        <div class="leg"><span class="leg-dot" style="background:#2a2520"></span><span style="color:#5a4e3a">Unknown</span></div>
      </div>
    </div>

  </div>

  <!-- CENTER — GRID -->
  <div class="col-center">
    <div class="grid-outer" id="gridOuter">
      <!-- injected by JS -->
    </div>
  </div>

  <!-- RIGHT — Controls + Log -->
  <div class="col-right">

    <div class="sec">
      <div class="sec-title">CONTROLS</div>
      <div class="btn-stack">
        <button class="btn-step"   onclick="doStep()"><span>▶</span>STEP ONCE</button>
        <button class="btn-auto"   onclick="toggleAuto()" id="autoBtn"><span>⏩</span>AUTO-PLAY</button>
        <button class="btn-reveal" onclick="doReveal()"><span>👁</span>REVEAL MAP</button>
        <button class="btn-new"    onclick="doNew()"><span>↺</span>NEW GAME</button>
      </div>
      <div class="speed-row">
        <span>SPEED</span>
        <input type="range" id="speedSlider" min="150" max="2000" value="700" step="50"/>
        <span class="speed-val" id="speedLabel">700ms</span>
      </div>
    </div>

    <div class="log-wrap">
      <div class="sec-title">INFERENCE LOG</div>
      <div class="log-inner" id="logBox"></div>
    </div>

  </div>
</div>

<!-- ══ FOOTER ══ -->
<footer>
  <div class="member lead"><b>LEAD: Tejas H</b> · 24BCS155</div>
  <div class="member"><b>Shubham Ramesh Vaddar</b> · 24BCS143</div>
  <div class="member"><b>Goutam Shankar Rathod</b> · 24BCS167</div>
  <div class="member"><b>Ramesh Kumar</b> · 24BCS168</div>
  <div class="member"><b>SAMPATH S KORALLI</b> · 24BCS129</div>
</footer>

<script>
let autoTimer   = null;
let autoRunning = false;
let lastLog     = [];

// ── Calculate optimal cell size ────────────────────────────
function calcCellSize() {
  const headerH = document.querySelector('header').offsetHeight;
  const bannerH = document.getElementById('statusBanner').offsetHeight;
  const footerH = document.querySelector('footer').offsetHeight;
  const avH = window.innerHeight - headerH - bannerH - footerH - 40;
  const avW = window.innerWidth - 230 - 300 - 40;
  const sz  = Math.floor(Math.min(avH, avW) / 4) - 4;
  return Math.max(100, Math.min(sz, 170));
}

// ── Fetch helpers ───────────────────────────────────────────
async function fetchJSON(url, method='GET') {
  const res = await fetch(url, { method });
  return res.json();
}

// ── Build grid ──────────────────────────────────────────────
function renderGrid(state) {
  const cw   = calcCellSize();
  const root = document.documentElement;
  root.style.setProperty('--cw', cw + 'px');
  root.style.setProperty('--ch', cw + 'px');

  const outer = document.getElementById('gridOuter');
  let html = '';

  // Column headers
  html += '<div class="grid-label-row"><div class="axis-spacer"></div>';
  for (let c = 1; c <= 4; c++)
    html += `<div class="axis-lbl">COL ${c}</div>`;
  html += '</div>';

  html += '<div class="grid-body">';
  state.grid.forEach((row, r) => {
    html += `<div class="grid-row-wrap"><div class="row-lbl">R${r+1}</div><div class="grid-row">`;
    row.forEach(cell => {
      const vis = cell.visited;
      let cls = 'cell ';
      if (!vis) {
        cls += 'fog';
      } else if (!state.alive) {
        cls += 'c-dead';
      } else if (cell.is_agent) {
        cls += 'c-agent';
      } else if (cell.kb_safe) {
        cls += 'c-safe';
      } else {
        cls += 'c-visited';
      }
      if (vis && cell.has_breeze && !cell.is_pit) cls += ' has-breeze';
      if (vis && cell.has_stench && !cell.is_wumpus) cls += ' has-stench';

      html += `<div class="${cls}">`;
      html += `<span class="coord">(${cell.pos[0]},${cell.pos[1]})</span>`;

      // Start position badge
      if (cell.pos[0] === 4 && cell.pos[1] === 1 && vis)
        html += `<span class="start-badge">START</span>`;

      if (!vis) {
        html += `<span class="fog-mark">?</span>`;
      } else {
        // Icons
        let icons = '';
        if (cell.is_agent)                        icons += '🤖';
        if (cell.is_wumpus && cell.wumpus_alive)  icons += '👾';
        if (cell.is_wumpus && !cell.wumpus_alive) icons += '💀';
        if (cell.is_gold)                         icons += '✨';
        if (cell.is_pit)                          icons += '🕳';
        if (icons) html += `<div class="cell-icons">${icons}</div>`;

        // KB / percept tags
        let tags = '';
        if (cell.has_breeze && !cell.is_agent) tags += `<span class="ctag ct-breeze">BREEZE</span>`;
        if (cell.has_stench && !cell.is_agent) tags += `<span class="ctag ct-stench">STENCH</span>`;
        if (cell.kb_safe)    tags += `<span class="ctag ct-safe">SAFE ✓</span>`;
        if (cell.kb_pit)     tags += `<span class="ctag ct-pit">PIT?</span>`;
        if (cell.kb_wumpus)  tags += `<span class="ctag ct-wumpus">W?</span>`;
        if (tags) html += `<div class="cell-tags">${tags}</div>`;

        // Agent direction arrow
        if (cell.is_agent)
          html += `<div class="agent-dir-badge">${state.agent_dir}</div>`;
      }

      html += '</div>'; // .cell
    });
    html += '</div></div>';
  });
  html += '</div>';
  outer.innerHTML = html;
}

// ── Stats ───────────────────────────────────────────────────
function updateStats(state) {
  document.getElementById('score').textContent = state.score;
  document.getElementById('steps').textContent = state.step_count;
  document.getElementById('pos').textContent   = `(${state.agent_pos[0]},${state.agent_pos[1]})`;
  document.getElementById('facing').textContent= `${state.agent_dir} ${state.agent_dir_name[0]}`;

  const arrowEl = document.getElementById('arrow');
  arrowEl.textContent = state.has_arrow ? 'READY' : 'USED';
  arrowEl.className   = 'stat-value ' + (state.has_arrow ? 'sv-lime' : 'sv-rose');

  const goldEl = document.getElementById('gold');
  goldEl.textContent = state.has_gold ? 'HELD ✓' : 'NO';
  goldEl.className   = 'stat-value ' + (state.has_gold ? 'sv-amber' : 'sv-dim');

  const wEl = document.getElementById('wumpus');
  wEl.textContent = state.wumpus_alive ? '⚠ ALIVE' : '☠ DEAD';
  wEl.className   = 'stat-value ' + (state.wumpus_alive ? 'sv-rose' : 'sv-lime');

  // Percepts
  const pMap = {
    breeze:  ['on-breeze',  '🌬 BREEZE'],
    stench:  ['on-stench',  '🔴 STENCH'],
    glitter: ['on-glitter', '✨ GLITTER'],
    scream:  ['on-scream',  '📢 SCREAM'],
  };
  Object.entries(pMap).forEach(([k, [cls, lbl]]) => {
    const el = document.getElementById('p-' + k);
    el.className  = 'percept ' + (state.percepts[k] ? cls : 'off');
    el.textContent = lbl;
  });

  // Status banner
  const banner = document.getElementById('statusBanner');
  const dot    = document.getElementById('statusDot');
  const txt    = document.getElementById('statusText');

  if (state.won) {
    banner.className = 'sb-won';
    dot.textContent  = '🏆';
    txt.textContent  = 'VICTORY — GOLD RETRIEVED!';
  } else if (!state.alive) {
    banner.className = 'sb-dead';
    dot.textContent  = '💀';
    txt.textContent  = 'AGENT TERMINATED';
  } else if (state.has_gold) {
    banner.className = 'sb-returning';
    dot.textContent  = '◈';
    txt.textContent  = 'RETURNING WITH GOLD';
  } else {
    banner.className = 'sb-exploring';
    dot.textContent  = '◈';
    txt.textContent  = 'EXPLORING';
  }
}

// ── Log ─────────────────────────────────────────────────────
function updateLog(state) {
  const box = document.getElementById('logBox');
  if (JSON.stringify(state.kb_log) === JSON.stringify(lastLog)) return;
  lastLog = state.kb_log;
  box.innerHTML = state.kb_log.map(l => {
    let cls = 'log-line info';
    if (l.includes('SAFE'))                                     cls = 'log-line safe';
    else if (l.includes('PIT'))                                 cls = 'log-line pit';
    else if (l.includes('WUMPUS') || l.includes('Wumpus'))      cls = 'log-line wumpus';
    else if (l.includes('→') || l.includes('step'))            cls = 'log-line move';
    else if (l.includes('⚠') || l.includes('stuck') || l.includes('💀')) cls = 'log-line warn';
    else if (l.includes('🏆') || l.includes('WON') || l.includes('Gold')) cls = 'log-line win';
    return `<div class="${cls}">${l}</div>`;
  }).join('');
  box.scrollTop = box.scrollHeight;
}

// ── Full render ──────────────────────────────────────────────
function render(state) {
  renderGrid(state);
  updateStats(state);
  updateLog(state);
  if (!state.alive || state.won) stopAuto();
}

// ── Actions ──────────────────────────────────────────────────
async function doStep()   { render(await fetchJSON('/step','POST')); }
async function doNew()    { stopAuto(); render(await fetchJSON('/new_game','POST')); }
async function doReveal() { render(await fetchJSON('/reveal','POST')); }

function toggleAuto() {
  if (autoRunning) { stopAuto(); return; }
  autoRunning = true;
  const b = document.getElementById('autoBtn');
  b.innerHTML = '<span>⏹</span>STOP';
  b.className = 'btn-stop';
  autoLoop();
}
function autoLoop() {
  if (!autoRunning) return;
  const ms = parseInt(document.getElementById('speedSlider').value);
  doStep().then(() => { if (autoRunning) autoTimer = setTimeout(autoLoop, ms); });
}
function stopAuto() {
  autoRunning = false;
  clearTimeout(autoTimer);
  const b = document.getElementById('autoBtn');
  b.innerHTML = '<span>⏩</span>AUTO-PLAY';
  b.className = 'btn-auto';
}

document.getElementById('speedSlider').addEventListener('input', e => {
  document.getElementById('speedLabel').textContent = e.target.value + 'ms';
});
window.addEventListener('resize', () => { fetchJSON('/state').then(render); });

// Initial load
fetchJSON('/state').then(render);
</script>
</body>
</html>
"""

def open_browser():
    import time
    time.sleep(1.2)
    webbrowser.open("http://localhost:5000")

if __name__ == "__main__":
    print("=" * 60)
    print("  WUMPUS WORLD — Starting server...")
    print("  Open your browser at:  http://localhost:5000")
    print("  Press  Ctrl+C  to stop.")
    print("=" * 60)
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(debug=False, port=5000)
