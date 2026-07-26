/**
 * Eco-Loop Building Agents — Dashboard App
 * Fetches comparison_data.json and renders interactive charts + stats.
 */

(function () {
  'use strict';

  const DATA_URL = '../results/comparison_data.json';

  // ─── DOM Refs ─────────────────────────────────────────
  const $loading = document.getElementById('loading-state');
  const $error = document.getElementById('error-state');
  const $errorMsg = document.getElementById('error-message');
  const $main = document.getElementById('main-content');

  // ─── Chart.js Global Defaults ─────────────────────────
  Chart.defaults.color = '#94a3b8';
  Chart.defaults.borderColor = 'rgba(255,255,255,0.06)';
  Chart.defaults.font.family = "'Inter', sans-serif";
  Chart.defaults.font.size = 11;
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.animation.duration = 1200;

  // ─── Helpers ──────────────────────────────────────────
  function animateNumber(el, target, suffix, duration) {
    const start = performance.now();
    const from = 0;
    function step(now) {
      const t = Math.min((now - start) / duration, 1);
      const ease = 1 - Math.pow(1 - t, 3); // easeOutCubic
      const val = from + (target - from) * ease;
      el.textContent = val.toFixed(target % 1 === 0 ? 0 : 1) + (suffix || '');
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  // Sample every Nth point for smoother charts
  function sampleEvery(arr, n) {
    return arr.filter((_, i) => i % n === 0);
  }

  // ─── Load Data ────────────────────────────────────────
  fetch(DATA_URL)
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
      return r.json();
    })
    .then(render)
    .catch(err => {
      $loading.style.display = 'none';
      $error.style.display = 'block';
      $errorMsg.textContent = err.message;
    });

  // ─── Render ───────────────────────────────────────────
  function render(data) {
    $loading.style.display = 'none';
    $main.style.display = 'block';

    const s = data.summary;
    const ts = data.timeseries;

    // Hero
    animateNumber(document.getElementById('hero-savings'), s.hvac_savings_pct, '', 2000);
    document.getElementById('hero-baseline-kwh').textContent = s.baseline_hvac_kwh.toFixed(1);
    document.getElementById('hero-ai-kwh').textContent = s.ai_hvac_kwh.toFixed(1);
    document.getElementById('hero-comfort').textContent = s.ai_comfort_pct + '%';
    document.getElementById('hero-detail').textContent =
      `Baseline vs AI-Controlled (${s.simulation_hours}h / ${Math.round(s.simulation_hours/24)} days)`;

    // Stat cards
    animateNumber(document.getElementById('stat-total-savings'), s.total_savings_pct, '%', 1500);
    document.getElementById('stat-total-detail').textContent =
      `${s.baseline_total_kwh} -> ${s.ai_total_kwh} kWh`;

    const heuristicEl = document.getElementById('stat-heuristic-savings');
    if (heuristicEl && s.heuristic_hvac_savings_pct !== undefined) {
      animateNumber(heuristicEl, s.heuristic_hvac_savings_pct, '% (HVAC)', 1500);
      document.getElementById('stat-heuristic-detail').textContent =
        `LLM Incremental: ${s.llm_incremental_savings_pct}%`;
    }

    // Cost savings
    const costEl = document.getElementById('stat-cost');
    if (costEl && s.cost_savings_usd !== undefined) {
      costEl.textContent = '$' + s.cost_savings_usd.toFixed(2);
      document.getElementById('stat-cost-detail').textContent =
        `$${s.baseline_cost_usd.toFixed(2)} -> $${s.ai_cost_usd.toFixed(2)}`;
    }

    // Carbon savings
    const carbonEl = document.getElementById('stat-carbon');
    if (carbonEl && s.carbon_savings_kg !== undefined) {
      animateNumber(carbonEl, s.carbon_savings_kg, ' kg', 1500);
      document.getElementById('stat-carbon-detail').textContent =
        `${s.baseline_carbon_kg} -> ${s.ai_carbon_kg} kgCO2`;
    }

    document.getElementById('stat-setpoint').textContent = s.ai_avg_setpoint + '\u00B0C';

    // PMV — show average as headline, worst-case in subtext
    const pmvEl = document.getElementById('stat-pmv');
    if (pmvEl && s.ai_avg_pmv !== undefined) {
      pmvEl.textContent = s.ai_avg_pmv + ' (Avg)';
      document.getElementById('stat-pmv-detail').textContent =
        `Worst: ${s.ai_max_pmv_occ} | All-hrs: ${s.ai_max_pmv_all} | Baseline: ${s.baseline_max_pmv_occ}`;
    }

    // MCP tools / latency
    const latEl = document.getElementById('stat-latency-detail');
    if (latEl) {
      latEl.textContent = `avg ${Math.round(s.ai_avg_latency_ms)}ms latency`;
    }

    // LLM Observability
    if (document.getElementById('stat-prompt-tokens')) {
      document.getElementById('stat-prompt-tokens').textContent = s.ai_avg_prompt_tokens || 0;
      document.getElementById('stat-completion-tokens').textContent = s.ai_avg_completion_tokens || 0;
      document.getElementById('stat-spikes').textContent = s.ai_recovery_spikes || 0;
      document.getElementById('stat-clamps').textContent = s.ai_total_clamp_events || 0;
      document.getElementById('stat-regex-fb').textContent = s.ai_regex_fallbacks || 0;
      document.getElementById('stat-heuristic-fb').textContent = s.ai_heuristic_fallbacks || 0;
      document.getElementById('stat-latency-new').textContent = Math.round(s.ai_avg_latency_ms || 0);
      document.getElementById('stat-decisions').textContent = s.timesteps || 672;
    }

    // Prepare sampled data (show every point for 192 steps)
    const N = 1; // show all points
    const labels = sampleEvery(ts.timestamps, N);

    // ─── Chart 1: HVAC Power ────────────────────────────
    new Chart(document.getElementById('chart-energy'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Baseline HVAC (W)',
            data: sampleEvery(ts.baseline_hvac_power, N),
            borderColor: '#ef4444',
            backgroundColor: 'rgba(239,68,68,0.08)',
            borderWidth: 1.5,
            fill: true,
            tension: 0.3,
            pointRadius: 0,
          },
          {
            label: 'Heuristic HVAC (W)',
            data: sampleEvery(ts.heuristic_hvac_power || [], N),
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245,158,11,0.08)',
            borderWidth: 1.5,
            borderDash: [5, 5],
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            hidden: !(ts.heuristic_hvac_power && ts.heuristic_hvac_power.length > 0)
          },
          {
            label: 'AI HVAC (W)',
            data: sampleEvery(ts.ai_hvac_power, N),
            borderColor: '#10b981',
            backgroundColor: 'rgba(16,185,129,0.08)',
            borderWidth: 1.5,
            fill: true,
            tension: 0.3,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            ticks: { maxTicksLimit: 12, maxRotation: 45 },
            grid: { display: false },
          },
          y: {
            title: { display: true, text: 'Power (W)' },
            beginAtZero: true,
          },
        },
        plugins: {
          tooltip: {
            backgroundColor: 'rgba(17,24,39,0.95)',
            borderColor: 'rgba(255,255,255,0.1)',
            borderWidth: 1,
            titleFont: { weight: 600 },
          },
        },
      },
    });

    // ─── Chart 2: Zone Temperature ──────────────────────
    new Chart(document.getElementById('chart-temp'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Baseline Zone Temp',
            data: sampleEvery(ts.baseline_temp, N),
            borderColor: '#ef4444',
            borderWidth: 1.5,
            tension: 0.3,
            pointRadius: 0,
          },
          {
            label: 'Heuristic Zone Temp',
            data: sampleEvery(ts.heuristic_temp || [], N),
            borderColor: '#f59e0b',
            borderWidth: 1.5,
            borderDash: [5, 5],
            tension: 0.3,
            pointRadius: 0,
            hidden: !(ts.heuristic_temp && ts.heuristic_temp.length > 0)
          },
          {
            label: 'AI Zone Temp',
            data: sampleEvery(ts.ai_temp, N),
            borderColor: '#10b981',
            borderWidth: 1.5,
            tension: 0.3,
            pointRadius: 0,
          },
          {
            label: 'Outdoor Temp',
            data: sampleEvery(ts.outdoor_temp, N),
            borderColor: '#3b82f6',
            borderWidth: 1,
            borderDash: [4, 3],
            tension: 0.3,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            ticks: { maxTicksLimit: 12, maxRotation: 45 },
            grid: { display: false },
          },
          y: {
            title: { display: true, text: 'Temperature (\u00B0C)' },
            min: 14,
            max: 30,
          },
        },
        plugins: {
          tooltip: {
            backgroundColor: 'rgba(17,24,39,0.95)',
            borderColor: 'rgba(255,255,255,0.1)',
            borderWidth: 1,
          },
          annotation: {
            annotations: {
              comfortBand: {
                type: 'box',
                yMin: 21,
                yMax: 26,
                backgroundColor: 'rgba(245,158,11,0.06)',
                borderColor: 'rgba(245,158,11,0.2)',
                borderWidth: 1,
                label: {
                  display: true,
                  content: 'Comfort Band',
                  position: 'start',
                  color: 'rgba(245,158,11,0.5)',
                  font: { size: 10 },
                },
              },
            },
          },
        },
      },
    });

    // ─── Chart 3: Setpoint Decisions ────────────────────
    new Chart(document.getElementById('chart-setpoint'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Baseline Setpoint',
            data: sampleEvery(ts.baseline_setpoint, N),
            borderColor: 'rgba(239,68,68,0.7)',
            borderWidth: 2,
            stepped: 'before',
            pointRadius: 0,
          },
          {
            label: 'Heuristic Setpoint',
            data: sampleEvery(ts.heuristic_setpoint || [], N),
            borderColor: '#f59e0b',
            borderWidth: 2,
            borderDash: [5, 5],
            stepped: 'before',
            pointRadius: 0,
            hidden: !(ts.heuristic_setpoint && ts.heuristic_setpoint.length > 0)
          },
          {
            label: 'AI Setpoint',
            data: sampleEvery(ts.ai_setpoint, N),
            borderColor: '#10b981',
            backgroundColor: 'rgba(16,185,129,0.1)',
            borderWidth: 2,
            fill: true,
            stepped: 'before',
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            ticks: { maxTicksLimit: 16, maxRotation: 45 },
            grid: { display: false },
          },
          y: {
            title: { display: true, text: 'Setpoint (\u00B0C)' },
            min: 20,
            max: 30,
          },
        },
        plugins: {
          tooltip: {
            backgroundColor: 'rgba(17,24,39,0.95)',
            borderColor: 'rgba(255,255,255,0.1)',
            borderWidth: 1,
          },
          annotation: {
            annotations: {
              comfortBand: {
                type: 'box',
                yMin: 21,
                yMax: 26,
                backgroundColor: 'rgba(245,158,11,0.06)',
                borderColor: 'rgba(245,158,11,0.15)',
                borderWidth: 1,
              },
            },
          },
        },
      },
    });

    // ─── Chart 4: Histogram ────────────────────
    if (document.getElementById('chart-histogram') && s.setpoint_delta_histogram) {
      const hist = s.setpoint_delta_histogram;
      const histLabels = Object.keys(hist);
      const histData = Object.values(hist);
      const bgColors = histLabels.map(l => (l === '1.5-2.0' || l === '2.0-2.5') ? 'rgba(239,68,68,0.8)' : 'rgba(59,130,246,0.6)');
      
      new Chart(document.getElementById('chart-histogram'), {
        type: 'bar',
        data: {
          labels: histLabels,
          datasets: [{
            label: 'Decision Count',
            data: histData,
            backgroundColor: bgColors,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
          },
          scales: {
            y: { title: { display: true, text: 'Number of Decisions' } },
            x: { title: { display: true, text: 'Absolute Setpoint Delta (°C)' } }
          }
        }
      });
    }

  }

})();
