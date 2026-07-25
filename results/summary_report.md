# Eco-Loop Building Agents -- Summary Report

## Simulation Details
- **Period:** July 1-2 (48 hours, Chicago IL summer)
- **Building:** 5-Zone Air-Cooled Office (5ZoneAirCooled.idf)
- **Target Zone:** SPACE1-1 (south-facing, highest cooling load)
- **Timesteps:** 192 (4 per hour)
- **LLM:** Ollama llama3:8b (avg latency: 754ms)

---

## Energy Results

| Metric | Baseline | AI-Controlled | Savings |
|--------|----------|--------------|---------|
| **Total Energy** | 324.76 kWh | 319.4 kWh | **1.65%** |
| **HVAC Energy** | 76.61 kWh | 71.25 kWh | **7.0%** |
| Peak HVAC Power | 4262.2 W | 4684.5 W | - |

---

## Comfort Results

| Metric | Baseline | AI-Controlled |
|--------|----------|--------------|
| **Comfort %** (occupied hours) | 98.2% | 98.2% |
| Too Hot violations | 0 | 0 |
| Too Cold violations | 2 | 2 |
| Avg Occupied Temp | 23.36 C | 23.69 C |
| Max Hot Excursion | +0.0 C | +0.0 C |
| Max Cold Excursion | -0.6 C | -0.6 C |

---

## AI Agent Performance

| Metric | Value |
|--------|-------|
| Average Setpoint | 25.73 C (vs baseline 23.9 C) |
| Average Latency | 754 ms |
| LLM Failures | 0 |
| Heuristic Fallbacks | 0 |

---

## Key Findings

1. **HVAC energy savings of 7.0%** achieved by raising the average cooling setpoint from 23.9 C to 25.73 C
2. **No comfort degradation** -- both runs achieved 98.2% comfort during occupied hours
3. **LLM inference is fast enough** for real-time control at 754ms average latency
4. **Zero LLM failures** -- the structured JSON output format with Ollama worked perfectly across all 192 timesteps
