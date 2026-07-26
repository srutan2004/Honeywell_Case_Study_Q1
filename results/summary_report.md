# Eco-Loop Building Agents -- Summary Report

## Simulation Details
- **Period:** 6/25 - 7/1 (168 hours / 7.0 days, Chicago IL)
- **Building:** 5-Zone Air-Cooled Office (5ZoneAirCooled.idf)
- **Target Zone:** SPACE1-1 (south-facing, highest cooling load)
- **Timesteps:** 672 (4 per hour)
- **LLM:** Ollama llama3:8b (avg latency: 788ms)

---

## Energy Results

| Metric | Baseline | Heuristic | AI-Controlled | Savings vs Baseline |
|--------|----------|-----------|---------------|---------------------|
| **Total Energy** | 938.23 kWh | - kWh | 906.62 kWh | **3.4%** |
| **HVAC Energy** | 251.86 kWh | 232.98 kWh | 220.25 kWh | **12.6%** (Heuristic: 7.5%) |
| Peak HVAC Power | 6239.9 W | - | 6989.3 W | - |

---

## Comfort Results

| Metric | Baseline | Heuristic | AI-Controlled |
|--------|----------|-----------|---------------|
| **Comfort Maintained** | 98.2% | 98.2 | **97.7%** |
| Avg PMV (Occupied) | -0.4 | - | **-0.26** |
| Worst PMV (Occupied) | -1.54 | - | **-1.54** |
| PPD (Dissatisfied) | 9.9% | - | **9.6%** |

---

## LLM Observability & Reliability
- **Total Decisions:** 672
- **Avg Prompt Tokens:** 557
- **Avg Completion Tokens:** 24
- **Heuristic Fallbacks:** 0
- **Regex Fallbacks:** 0
- **Clamp Events:** 0
- **Recovery Spikes (Δ ≥ 1.5°C):** 15

---

## Key Findings

1. **HVAC energy savings of 12.6%** achieved by raising the average cooling setpoint from 23.9 C to 26.3 C
2. **Heuristic alone saves 7.5%** — but the LLM adds an additional **5.05%** incremental improvement over simple rules
3. **Comfort maintained at 97.7%** during occupied hours — AI runs closer to the comfort ceiling during peak heat but stays within bounds
4. **LLM inference is fast enough** for real-time control at 788ms average latency
5. **Zero LLM failures** — the structured JSON output format with Ollama worked perfectly across all 672 timesteps over 7.0 days
6. **Validated over extended 7.0-day period** — savings improved from initial 48-hour window, demonstrating sustained benefit across varying weather conditions
7. **Peak Demand Overshoot (Recurring Prompt Rule Conflict)** — The AI successfully sheds load most of the time but produced a single-timestep peak of 6,989W (exceeding baseline). This is a recurring prompt rule conflict where the AI prioritizes comfort recovery over gradual change rules, issuing a sudden 1.5-2.5°C setpoint drop that forces a maximum HVAC power spike. Future versions should enforce strict rate-limiting on setpoint deltas.
