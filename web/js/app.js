/* global PyBridge, Chart */

let stateValidationTimer = null;
let currentStateDict = null;
let stateIsValid = false;

let modelValidationTimer = null;
let modelIsValid = false;

let lastResult = null;
let tierChartInstance = null;
let spiceChartInstance = null;

// --- Initialization ---

document.addEventListener("DOMContentLoaded", async () => {
    const loadingStatus = document.getElementById("loading-status");

    await PyBridge.init((msg) => {
        loadingStatus.textContent = msg;
    });

    document.getElementById("loading-screen").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");

    const defaultState = PyBridge.getDefaultState();
    document.getElementById("state-textarea").value = JSON.stringify(defaultState, null, 2);
    const defaultModel = PyBridge.getDefaultModelConfig();
    document.getElementById("model-textarea").value = JSON.stringify(defaultModel, null, 2);

    validateState();
    validateModel();
    updateRunButtons();
    setupEventHandlers();
});

// --- State Validation ---

function validateState() {
    const textarea = document.getElementById("state-textarea");
    const statusEl = document.getElementById("state-status");
    const errorEl = document.getElementById("state-error");
    const summaryEl = document.getElementById("state-summary");

    let parsed;
    try {
        parsed = JSON.parse(textarea.value);
    } catch (e) {
        statusEl.className = "status invalid";
        statusEl.textContent = "Invalid JSON";
        errorEl.textContent = e.message;
        errorEl.classList.remove("hidden");
        summaryEl.classList.add("hidden");
        stateIsValid = false;
        currentStateDict = null;
        updateRunButtons();
        return;
    }

    const result = PyBridge.validateState(parsed);

    if (result.ok) {
        statusEl.className = "status valid";
        statusEl.textContent = "Valid";
        errorEl.classList.add("hidden");
        currentStateDict = parsed;
        stateIsValid = true;
        renderStateSummary(summaryEl, result);
    } else {
        statusEl.className = "status invalid";
        statusEl.textContent = "Invalid";
        errorEl.textContent = result.error;
        errorEl.classList.remove("hidden");
        summaryEl.classList.add("hidden");
        stateIsValid = false;
        currentStateDict = null;
    }

    updateRunButtons();
}

function onStateInput() {
    clearTimeout(stateValidationTimer);
    stateValidationTimer = setTimeout(validateState, 300);
}

// --- State Summary ---

function renderStateSummary(container, result) {
    let html = "<h3>Alliances</h3><table><tr>";
    html += "<th>ID</th><th>Faction</th><th>Power</th><th>Starting Spice</th><th>Daily Rate</th>";
    html += "</tr>";
    for (const a of result.alliances) {
        html += `<tr>
            <td>${esc(a.alliance_id)}</td>
            <td>${esc(a.faction)}</td>
            <td>${a.power}</td>
            <td>${a.starting_spice.toLocaleString()}</td>
            <td>${a.daily_rate.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    html += "<h3>Event Schedule</h3><table><tr>";
    html += "<th>#</th><th>Attacker</th><th>Day</th><th>Days Before</th>";
    html += "</tr>";
    for (const e of result.event_schedule) {
        html += `<tr>
            <td>${e.event_number}</td>
            <td>${esc(e.attacker_faction)}</td>
            <td>${esc(e.day)}</td>
            <td>${e.days_before}</td>
        </tr>`;
    }
    html += "</table>";

    container.innerHTML = html;
    container.classList.remove("hidden");
}

// --- Model Validation ---

function validateModel() {
    const textarea = document.getElementById("model-textarea");
    const statusEl = document.getElementById("model-status");
    const errorEl = document.getElementById("model-error");

    let parsed;
    try {
        parsed = JSON.parse(textarea.value);
    } catch (e) {
        statusEl.className = "status invalid";
        statusEl.textContent = "Invalid JSON";
        errorEl.textContent = e.message;
        errorEl.classList.remove("hidden");
        modelIsValid = false;
        updateRunButtons();
        return;
    }

    if (!stateIsValid) {
        statusEl.className = "status";
        statusEl.textContent = "Needs valid state";
        errorEl.classList.add("hidden");
        modelIsValid = false;
        updateRunButtons();
        return;
    }

    const result = PyBridge.validateModelConfig(parsed, currentStateDict);

    if (result.ok) {
        statusEl.className = "status valid";
        statusEl.textContent = "Valid";
        errorEl.classList.add("hidden");
        modelIsValid = true;
    } else {
        statusEl.className = "status invalid";
        statusEl.textContent = "Invalid";
        errorEl.textContent = result.error;
        errorEl.classList.remove("hidden");
        modelIsValid = false;
    }

    updateRunButtons();
}

function onModelInput() {
    clearTimeout(modelValidationTimer);
    modelValidationTimer = setTimeout(validateModel, 300);
}

// --- Run Controls ---

function updateRunButtons() {
    const canRun = stateIsValid && modelIsValid;
    document.getElementById("run-single-btn").disabled = !canRun;
    document.getElementById("run-mc-btn").disabled = !canRun;
}

function setRunning(isRunning) {
    document.getElementById("run-single-btn").disabled = isRunning;
    document.getElementById("run-mc-btn").disabled = isRunning;
    document.getElementById("run-spinner").classList.toggle("hidden", !isRunning);
}

// --- Single Run ---

async function runSingle() {
    const stateDict = JSON.parse(document.getElementById("state-textarea").value);
    const modelDict = JSON.parse(document.getElementById("model-textarea").value);
    const seedInput = document.getElementById("single-seed").value;
    const seed = seedInput ? parseInt(seedInput, 10) : null;

    setRunning(true);
    const result = await PyBridge.runSingle(stateDict, modelDict, seed);
    setRunning(false);

    if (!result.ok) {
        showError(result.error);
        return;
    }

    lastResult = result;
    renderSingleResults(result);
}

function renderSingleResults(result) {
    const container = document.getElementById("results-content");
    const section = document.getElementById("results");
    section.classList.remove("hidden");

    const entries = Object.entries(result.final_spice).map(([id, spice]) => ({
        id,
        spice,
        tier: result.rankings[id],
    }));
    entries.sort((a, b) => a.tier - b.tier || b.spice - a.spice);

    let html = `<h3>Final Rankings (seed: ${result.seed})</h3>`;
    html += "<table><tr><th>Alliance</th><th>Tier</th><th>Final Spice</th></tr>";
    for (const e of entries) {
        html += `<tr>
            <td>${esc(e.id)}</td>
            <td>${e.tier}</td>
            <td>${e.spice.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    html += "<h3>Event Details</h3>";
    for (const event of result.event_history) {
        html += `<details>
            <summary>Event ${event.event_number}: ${esc(event.attacker_faction)} (${esc(event.day)})</summary>
            ${renderEventDetail(event)}
        </details>`;
    }

    container.innerHTML = html;
}

function renderEventDetail(event) {
    let html = "";

    html += "<h4>Spice</h4><table>";
    html += "<tr><th>Alliance</th><th>Before</th><th>After</th><th>Change</th></tr>";
    for (const [id, before] of Object.entries(event.spice_before)) {
        const after = event.spice_after[id];
        const change = after - before;
        const sign = change >= 0 ? "+" : "";
        html += `<tr>
            <td>${esc(id)}</td>
            <td>${before.toLocaleString()}</td>
            <td>${after.toLocaleString()}</td>
            <td>${sign}${change.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    html += "<h4>Targeting</h4><table>";
    html += "<tr><th>Attacker</th><th>Defender</th></tr>";
    for (const [att, def_] of Object.entries(event.targeting)) {
        html += `<tr><td>${esc(att)}</td><td>${esc(def_)}</td></tr>`;
    }
    html += "</table>";

    html += "<h4>Battles</h4>";
    for (const battle of event.battles) {
        html += `<div class="battle-detail">`;
        html += `<p><strong>${esc(battle.attackers.join(", "))} &rarr; ${esc(battle.defenders[0])}</strong>`;
        html += ` | Outcome: ${esc(battle.outcome)}`;
        html += ` | Theft: ${battle.theft_percentage}%</p>`;

        const probs = battle.outcome_probabilities;
        html += `<p class="probs">P(full)=${(probs.full_success * 100).toFixed(1)}%`;
        html += ` P(partial)=${(probs.partial_success * 100).toFixed(1)}%`;
        if (probs.custom !== undefined) {
            html += ` P(custom)=${(probs.custom * 100).toFixed(1)}%`;
        }
        html += ` P(fail)=${(probs.fail * 100).toFixed(1)}%</p>`;

        if (Object.keys(battle.transfers).length > 0) {
            html += "<table><tr><th>Alliance</th><th>Transfer</th></tr>";
            for (const [id, amount] of Object.entries(battle.transfers)) {
                const sign = amount >= 0 ? "+" : "";
                html += `<tr><td>${esc(id)}</td><td>${sign}${amount.toLocaleString()}</td></tr>`;
            }
            html += "</table>";
        }
        html += "</div>";
    }

    return html;
}

// --- Monte Carlo ---

async function runMonteCarlo() {
    const stateDict = JSON.parse(document.getElementById("state-textarea").value);
    const modelDict = JSON.parse(document.getElementById("model-textarea").value);
    const iterations = parseInt(document.getElementById("mc-iterations").value, 10) || 1000;
    const baseSeed = parseInt(document.getElementById("mc-base-seed").value, 10) || 0;

    setRunning(true);
    const result = await PyBridge.runMonteCarlo(stateDict, modelDict, iterations, baseSeed);
    setRunning(false);

    if (!result.ok) {
        showError(result.error);
        return;
    }

    lastResult = result;
    renderMonteCarloResults(result);
}

function renderMonteCarloResults(result) {
    const container = document.getElementById("results-content");
    const section = document.getElementById("results");
    section.classList.remove("hidden");

    const aids = Object.keys(result.tier_distribution);
    aids.sort((a, b) => {
        const aT1 = parseFloat(result.tier_distribution[a]["1"] || 0);
        const bT1 = parseFloat(result.tier_distribution[b]["1"] || 0);
        return bT1 - aT1;
    });

    let html = `<h3>Tier Distribution (${result.num_iterations} iterations)</h3>`;
    html += "<table><tr><th>Alliance</th>";
    for (let t = 1; t <= 5; t++) html += `<th>T${t}</th>`;
    html += "</tr>";
    for (const aid of aids) {
        html += `<tr><td>${esc(aid)}</td>`;
        const dist = result.tier_distribution[aid];
        for (let t = 1; t <= 5; t++) {
            const pct = (parseFloat(dist[String(t)] || 0) * 100).toFixed(1);
            html += `<td>${pct}%</td>`;
        }
        html += "</tr>";
    }
    html += "</table>";

    html += "<h3>Spice Statistics</h3>";
    html += "<table><tr><th>Alliance</th><th>Mean</th><th>Median</th>";
    html += "<th>Min</th><th>Max</th><th>P25</th><th>P75</th></tr>";
    for (const aid of aids) {
        const s = result.spice_stats[aid];
        html += `<tr>
            <td>${esc(aid)}</td>
            <td>${s.mean.toLocaleString()}</td>
            <td>${s.median.toLocaleString()}</td>
            <td>${s.min.toLocaleString()}</td>
            <td>${s.max.toLocaleString()}</td>
            <td>${s.p25.toLocaleString()}</td>
            <td>${s.p75.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    html += '<div id="chart-section">';
    html += '<h3>Tier Distribution</h3><canvas id="tier-chart"></canvas>';
    html += '<h3>Spice Distribution</h3><canvas id="spice-chart"></canvas>';
    html += "</div>";

    container.innerHTML = html;

    renderTierChart(aids, result.tier_distribution);
    renderSpiceChart(aids, result.spice_stats);
}

// --- Charts ---

function renderTierChart(aids, tierDist) {
    if (tierChartInstance) tierChartInstance.destroy();

    const ctx = document.getElementById("tier-chart").getContext("2d");
    const datasets = [];
    const tierColors = ["#28a745", "#17a2b8", "#ffc107", "#fd7e14", "#dc3545"];

    for (let t = 1; t <= 5; t++) {
        datasets.push({
            label: `Tier ${t}`,
            data: aids.map(aid => parseFloat(tierDist[aid][String(t)] || 0) * 100),
            backgroundColor: tierColors[t - 1],
        });
    }

    tierChartInstance = new Chart(ctx, {
        type: "bar",
        data: { labels: aids, datasets },
        options: {
            responsive: true,
            scales: {
                x: { stacked: true },
                y: { stacked: true, max: 100, title: { display: true, text: "%" } },
            },
        },
    });
}

function renderSpiceChart(aids, spiceStats) {
    if (spiceChartInstance) spiceChartInstance.destroy();

    const ctx = document.getElementById("spice-chart").getContext("2d");

    const datasets = [
        {
            label: "Min\u2013Max Range",
            data: aids.map(aid => [spiceStats[aid].min, spiceStats[aid].max]),
            backgroundColor: "rgba(54, 162, 235, 0.2)",
            borderColor: "rgba(54, 162, 235, 1)",
            borderWidth: 1,
        },
        {
            label: "P25\u2013P75 Range",
            data: aids.map(aid => [spiceStats[aid].p25, spiceStats[aid].p75]),
            backgroundColor: "rgba(54, 162, 235, 0.5)",
            borderColor: "rgba(54, 162, 235, 1)",
            borderWidth: 1,
        },
        {
            label: "Median",
            data: aids.map(aid => spiceStats[aid].median),
            type: "line",
            borderColor: "#dc3545",
            pointRadius: 6,
            pointStyle: "rectRot",
            showLine: false,
        },
    ];

    spiceChartInstance = new Chart(ctx, {
        type: "bar",
        data: { labels: aids, datasets },
        options: {
            indexAxis: "y",
            responsive: true,
            scales: {
                x: { title: { display: true, text: "Spice" } },
            },
        },
    });
}

// --- Event Handlers ---

function setupEventHandlers() {
    // State editor
    document.getElementById("state-textarea").addEventListener("input", onStateInput);
    document.getElementById("state-upload-btn").addEventListener("click", () => {
        document.getElementById("state-file-input").click();
    });
    document.getElementById("state-file-input").addEventListener("change", (e) => {
        readFileToTextarea(e.target.files[0], "state-textarea", validateState);
    });

    // Model editor
    document.getElementById("model-textarea").addEventListener("input", onModelInput);
    document.getElementById("model-upload-btn").addEventListener("click", () => {
        document.getElementById("model-file-input").click();
    });
    document.getElementById("model-file-input").addEventListener("change", (e) => {
        readFileToTextarea(e.target.files[0], "model-textarea", validateModel);
    });

    // CSV import
    document.getElementById("csv-import-btn").addEventListener("click", () => {
        document.getElementById("csv-file-input").click();
    });
    document.getElementById("csv-file-input").addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
            const result = PyBridge.importCsv(reader.result);
            if (result.ok) {
                document.getElementById("model-textarea").value =
                    JSON.stringify(result.config, null, 2);
                validateModel();
            } else {
                alert("CSV import error: " + result.error);
            }
        };
        reader.readAsText(file);
    });

    // CSV template download
    document.getElementById("csv-template-btn").addEventListener("click", () => {
        if (!currentStateDict) return;
        const result = PyBridge.generateTemplateCsv(currentStateDict, 6);
        if (result.ok) {
            downloadFile("spice_war_template.csv", result.csv, "text/csv");
        } else {
            alert("Template error: " + result.error);
        }
    });

    // Run buttons
    document.getElementById("run-single-btn").addEventListener("click", runSingle);
    document.getElementById("run-mc-btn").addEventListener("click", runMonteCarlo);

    // Export buttons
    document.getElementById("download-results-btn").addEventListener("click", () => {
        if (lastResult) {
            downloadFile("spice_war_results.json",
                JSON.stringify(lastResult, null, 2), "application/json");
        }
    });
    document.getElementById("download-model-btn").addEventListener("click", () => {
        const model = document.getElementById("model-textarea").value;
        downloadFile("model_config.json", model, "application/json");
    });
}

// --- Utilities ---

function readFileToTextarea(file, textareaId, validateFn) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
        document.getElementById(textareaId).value = reader.result;
        validateFn();
    };
    reader.readAsText(file);
}

function downloadFile(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

function showError(msg) {
    const container = document.getElementById("results-content");
    const section = document.getElementById("results");
    section.classList.remove("hidden");
    container.innerHTML = `<div class="error-msg">${esc(msg)}</div>`;
}

function esc(str) {
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
}
