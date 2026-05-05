# ⚀ Wumpus World: Knowledge-Based AI Solver

A self-contained, interactive simulation of the **Wumpus World**—a classic artificial intelligence benchmark for testing logical reasoning, navigation, and decision-making under uncertainty.

This project implements a fully autonomous agent that uses a **Knowledge Base (KB)** and **Breadth-First Search (BFS)** to explore a $4 \times 4$ grid, locate gold, and return safely while avoiding deadly pits and the "Wumpus."

---

## 🚀 Key Features

*   **Integrated Simulation**: A single Python file that bundles the AI logic, game engine, and a Flask-based web dashboard.
*   **Logical Deduction Engine**: The agent processes "percepts" (Breeze, Stench, Glitter) to dynamically update its Knowledge Base, marking cells as `SAFE`, `PIT?`, or `WUMPUS?`.
*   **Pathfinding & Navigation**: 
    *   **BFS**: Plans the most efficient path back to the start or to the next known safe cell.
    *   **Risk Assessment**: The agent identifies "stuck" scenarios and takes calculated risks when no safe moves are left.
*   **Cyberpunk UI**: A modern, responsive dashboard built with a dark "Amber/Ember" aesthetic, featuring:
    *   **Real-time Inference Log**: Watch the agent "think" in plain English.
    *   **Telemetry Grid**: Visual feedback on the agent's "mental map" vs. the actual world state.
    *   **Speed Control**: Adjust simulation speed from 150ms to 2000ms.

---

## 🛠️ Tech Stack & Logic

### Core Technology
*   **Language**: Python 3.x
*   **Backend Framework**: Flask (for the interactive web server)
*   **Frontend**: Vanilla JavaScript (ES6+), Modern CSS (Grid/Flexbox)

### AI Logic Components
1.  **WumpusWorld Class**: Manages the environment, object placement (Pits, Wumpus, Gold), and percept generation.
2.  **KnowledgeBase Class**: Acts as the agent's memory. It uses propositional logic to confirm safe zones based on the absence of Breezes and Stenches.
3.  **WumpusAgent Class**: The "brain" that executes the **Sense-Think-Act** cycle.
    *   **Sense**: Check for `Breeze`, `Stench`, `Glitter`, and `Scream`.
    *   **Think**: Update the KB and calculate the next move.
    *   **Act**: Move, turn, shoot the arrow, or grab the gold.

---

## 📦 Getting Started

### Prerequisites
Ensure you have Python installed. You only need the `flask` library:
```bash
pip install flask
