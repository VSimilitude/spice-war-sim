/* global PyBridge, Chart */

let stateValidationTimer = null;
let currentStateDict = null;
let stateIsValid = false;

let modelValidationTimer = null;
let modelIsValid = false;

// Current model form data, mirrors the JSON structure.
// null when form hasn't been populated yet.
let modelFormData = null;

// Tracks which view is active: "form" or "json"
let modelViewMode = "form";

let lastResult = null;
let tierChartInstance = null;
let spiceChartInstance = null;
let formHandlersAttached = false;
let resultFilter = "top10";

// Stash for maximize_tier options — preserved when switching away from maximize_tier
let _tierOptsStash = { top_n: 5, fallback: "rank_aware" };

const STRATEGIES = [
    { value: "expected_value", label: "expected_value" },
    { value: "highest_spice", label: "highest_spice" },
    { value: "rank_aware", label: "rank_aware" },
    { value: "maximize_tier", label: "maximize_tier" },
];

function strategyOptions(selected, { includeDefault = false } = {}) {
    let html = "";
    if (includeDefault) {
        html += `<option value="" ${selected === "" ? "selected" : ""}>(use global default)</option>`;
    }
    for (const s of STRATEGIES) {
        html += `<option value="${s.value}" ${selected === s.value ? "selected" : ""}>${s.label}</option>`;
    }
    return html;
}

function fallbackStrategyOptions(selected) {
    return STRATEGIES
        .filter(s => s.value !== "maximize_tier")
        .map(s => `<option value="${s.value}" ${selected === s.value ? "selected" : ""}>${s.label}</option>`)
        .join("");
}

// --- Initialization ---

document.addEventListener("DOMContentLoaded", async () => {
    const loadingStatus = document.getElementById("loading-status");

    await PyBridge.init((msg) => {
        loadingStatus.textContent = msg;
    });

    document.getElementById("loading-screen").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");

    // Load default state
    const defaultState = PyBridge.getDefaultState();
    document.getElementById("state-textarea").value = JSON.stringify(defaultState, null, 2);
    validateState();

    // Load default model — populate both form and textarea
    const defaultModel = PyBridge.getDefaultModelConfig(defaultState);
    modelFormData = defaultModel;
    document.getElementById("model-textarea").value = JSON.stringify(defaultModel, null, 2);
    buildModelForm();
    validateModel();

    updateRunButtons();
    setupEventHandlers();

    // Quick-start guide: remember collapse state
    const quickStart = document.getElementById("quick-start");
    if (quickStart) {
        if (localStorage.getItem("hideQuickStart") === "1") {
            quickStart.removeAttribute("open");
        }
        quickStart.addEventListener("toggle", () => {
            localStorage.setItem("hideQuickStart", quickStart.open ? "0" : "1");
        });
    }

    // Load configuration from shared URL hash
    const hash = window.location.hash.slice(1);
    if (hash) {
        try {
            const config = await decodeHashToConfig(hash);
            if (config) {
                if (config.v === 1 && config.state) {
                    document.getElementById("state-textarea").value = JSON.stringify(config.state, null, 2);
                    validateState();
                }
                if (config.model) {
                    if (config.model.tier_optimization_top_n != null) {
                        _tierOptsStash.top_n = config.model.tier_optimization_top_n;
                    }
                    if (config.model.tier_optimization_fallback != null) {
                        _tierOptsStash.fallback = config.model.tier_optimization_fallback;
                    }
                    modelFormData = config.model;
                    document.getElementById("model-textarea").value = JSON.stringify(config.model, null, 2);
                    buildModelForm();
                    validateModel();
                }
                if (config.seed != null) {
                    document.getElementById("single-seed").value = config.seed;
                }
                document.getElementById("mc-iterations").value = config.mcIterations || 1000;
                document.getElementById("mc-base-seed").value = config.mcBaseSeed || 0;

                const msg = config.v === 1
                    ? "Configuration loaded from shared URL"
                    : "Model config loaded from shared link";
                showNotification(msg);
            }
        } catch {
            // Invalid hash — silently ignore
        }
    }
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
        buildModelForm();
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
    let html = "<details><summary><h3>Alliances</h3></summary><table><tr>";
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
    html += "</table></details>";

    html += "<details open><summary><h3>Event Schedule</h3></summary><table><tr>";
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
    html += "</table></details>";

    container.innerHTML = html;
    container.classList.remove("hidden");
}

// --- Model Form ---

function getAlliancesFromState() {
    if (!currentStateDict) return [];
    return currentStateDict.alliances.map(a => ({
        id: a.alliance_id,
        faction: a.faction,
    }));
}

function getEventsFromState() {
    if (!currentStateDict) return [];
    return currentStateDict.event_schedule.map((e, i) => ({
        number: i + 1,
        attacker_faction: e.attacker_faction,
        day: e.day,
    }));
}

function alliancesByFaction(alliances) {
    const factions = {};
    for (const a of alliances) {
        if (!factions[a.faction]) factions[a.faction] = [];
        factions[a.faction].push(a.id);
    }
    return factions;
}

function buildModelForm() {
    const container = document.getElementById("model-form");

    if (!stateIsValid) {
        container.innerHTML = '<p class="muted">Load a valid game state to configure the model.</p>';
        return;
    }

    if (!modelFormData) {
        modelFormData = {};
    }

    const alliances = getAlliancesFromState();
    const events = getEventsFromState();

    let html = "";
    html += buildGeneralSettings();
    html += buildEventTargets(alliances, events);
    html += buildOutcomeMatrix(alliances, events);
    html += '<details class="model-section advanced-settings">';
    html += '<summary>Advanced Settings</summary>';
    html += buildFactionTargeting(alliances);
    html += buildDefaultTargets(alliances);
    html += buildEventReinforcements(alliances, events);
    html += buildDamageWeights(alliances);
    html += '</details>';

    container.innerHTML = html;
    attachFormHandlers();
    initHeuristicPlaceholders();
}

// --- Section Builders ---

function buildGeneralSettings() {
    const seed = modelFormData.random_seed ?? "";
    const strategy = modelFormData.targeting_strategy ?? "expected_value";
    const targTemp = modelFormData.targeting_temperature ?? "";
    const powerNoise = modelFormData.power_noise ?? "";
    const outcomeNoise = modelFormData.outcome_noise ?? "";
    const topN = modelFormData.tier_optimization_top_n ?? _tierOptsStash.top_n;
    const fallback = modelFormData.tier_optimization_fallback ?? _tierOptsStash.fallback;
    const showTierOpts = strategy === "maximize_tier";

    return `
    <details class="model-section key-section">
        <summary>General Settings</summary>
        <div class="form-grid">
            <label>Random Seed
                <input type="number" id="form-seed" value="${seed}" placeholder="auto"
                       data-field="random_seed">
            </label>
            <label>Global Targeting Strategy
                <span class="help-text">Fallback algorithm when no explicit target is set.
                    <strong>Expected Value</strong> maximizes expected spice stolen.
                    <strong>Highest Spice</strong> targets the richest defender.
                    <strong>Rank Aware</strong> optimizes for tier/rank improvement
                    rather than raw spice. <strong>Maximize Tier</strong> runs forward
                    simulations of the remaining war for the top N alliances to find the
                    target yielding the best final tier.</span>
                <select id="form-strategy" data-field="targeting_strategy">
                    ${strategyOptions(strategy)}
                </select>
            </label>
            <div id="maximize-tier-options" class="${showTierOpts ? "" : "hidden"}">
                <p class="help-text"><strong>Top N</strong> alliances (by spice within
                    the attacking faction) evaluate each candidate target by simulating
                    the rest of the war. Alliances outside the top N use the
                    <strong>fallback strategy</strong>. Higher N = more accurate but
                    slower Monte Carlo runs.</p>
                <label>Top N Alliances
                    <input type="number" id="form-tier-top-n" value="${topN}"
                           placeholder="5" min="1" step="1"
                           data-field="tier_optimization_top_n">
                </label>
                <label>Fallback Strategy
                    <select id="form-tier-fallback" data-field="tier_optimization_fallback">
                        ${fallbackStrategyOptions(fallback)}
                    </select>
                </label>
            </div>
            <div class="help-text noise-note">These three settings only affect
                <strong>Monte Carlo</strong> runs. Set all to 0 for fully
                deterministic results.</div>
            <label>Targeting Temperature
                <span class="help-text">0 = deterministic, higher = more random target selection</span>
                <input type="number" id="form-targeting-temp" value="${targTemp}"
                       placeholder="0" min="0" step="0.05"
                       data-field="targeting_temperature">
            </label>
            <label>Power Noise
                <span class="help-text">Per-event power fluctuation range (e.g. 0.1 = \u00b110%)</span>
                <input type="number" id="form-power-noise" value="${powerNoise}"
                       placeholder="0" min="0" step="0.05"
                       data-field="power_noise">
            </label>
            <label>Outcome Noise
                <span class="help-text">Random offset range for battle outcome probabilities</span>
                <input type="number" id="form-outcome-noise" value="${outcomeNoise}"
                       placeholder="0" min="0" step="0.05"
                       data-field="outcome_noise">
            </label>
        </div>
    </details>`;
}

function buildFactionTargeting(alliances) {
    const factions = [...new Set(alliances.map(a => a.faction))];
    const fts = modelFormData.faction_targeting_strategy || {};

    let rows = "";
    for (const faction of factions) {
        const val = fts[faction] || "";
        rows += `
        <tr>
            <td>${esc(faction)}</td>
            <td>
                <select data-field="faction_targeting_strategy" data-faction="${esc(faction)}">
                    ${strategyOptions(val, { includeDefault: true })}
                </select>
            </td>
        </tr>`;
    }

    return `
    <details class="model-section">
        <summary>Faction Targeting Strategy</summary>
        <p class="help-text">Override the global strategy for a specific faction.
            Alliances in that faction use this algorithm unless they have an
            explicit target.</p>
        <table class="form-table">
            <tr><th>Faction</th><th>Strategy</th></tr>
            ${rows}
        </table>
    </details>`;
}

function buildDefaultTargets(alliances) {
    const dt = modelFormData.default_targets || {};
    const aids = alliances.map(a => a.id);

    let rows = "";
    for (const [aid, val] of Object.entries(dt)) {
        const isPinned = typeof val === "string" || (typeof val === "object" && val.target);
        const target = typeof val === "string" ? val : val.target || "";
        const strategy = val.strategy || "";
        rows += defaultTargetRow(aids, aid, isPinned, target, strategy);
    }

    return `
    <details class="model-section">
        <summary>Default Targets</summary>
        <p class="help-text">Pin a specific target or strategy for an alliance
            across all events. Overridden by any event-level target below.</p>
        <table class="form-table" id="default-targets-table">
            <tr><th>Alliance</th><th>Type</th><th>Value</th><th></th><th></th></tr>
            ${rows}
        </table>
        <button class="add-row-btn" data-action="add-default-target">+ Add default target</button>
    </details>`;
}

function defaultTargetRow(aids, selectedAid, isPinned, target, strategy) {
    return `
    <tr class="dynamic-row" data-section="default_targets">
        <td>${allianceDropdown(aids, selectedAid, "dt-alliance")}</td>
        <td>
            <select class="dt-type">
                <option value="pin" ${isPinned ? "selected" : ""}>Pin to target</option>
                <option value="strategy" ${!isPinned ? "selected" : ""}>Use strategy</option>
            </select>
        </td>
        <td>
            <span class="dt-pin-value ${isPinned ? "" : "hidden"}">
                ${allianceDropdown(aids, target, "dt-target")}
            </span>
            <span class="dt-strategy-value ${isPinned ? "hidden" : ""}">
                ${strategyDropdown(strategy, "dt-strategy")}
            </span>
        </td>
        <td><button class="remove-row-btn" title="Remove">&times;</button></td>
        <td class="row-error-cell"></td>
    </tr>`;
}

function buildEventTargets(alliances, events) {
    const et = modelFormData.event_targets || {};
    const byFaction = alliancesByFaction(alliances);
    const factions = Object.keys(byFaction);

    let sections = "";
    for (const event of events) {
        const eventKey = String(event.number);
        const attackerFaction = event.attacker_faction;
        const defenderFaction = factions.find(f => f !== attackerFaction);
        const attackerIds = byFaction[attackerFaction] || [];
        const defenderIds = byFaction[defenderFaction] || [];
        const overrides = et[eventKey] || {};

        let rows = "";
        for (const [aid, val] of Object.entries(overrides)) {
            const isPinned = typeof val === "string" || (typeof val === "object" && val.target);
            const target = typeof val === "string" ? val : val.target || "";
            const strategy = typeof val === "object" ? val.strategy || "" : "";
            rows += eventTargetRow(attackerIds, defenderIds, aid, isPinned, target, strategy, eventKey);
        }

        sections += `
        <div class="event-subsection" data-event="${eventKey}">
            <h4>Event ${event.number} — ${esc(attackerFaction)} attacks (${esc(event.day)})</h4>
            <table class="form-table">
                <tr><th>Alliance</th><th>Type</th><th>Value</th><th></th><th></th></tr>
                ${rows}
            </table>
            <button class="add-row-btn" data-action="add-event-target" data-event="${eventKey}">
                + Add override</button>
        </div>`;
    }

    return `
    <details class="model-section key-section" open>
        <summary>Event Targets</summary>
        <p class="help-text">Pin a target for a specific alliance in a specific
            event. Highest priority — overrides default targets and
            faction/global strategies.</p>
        ${sections}
        <details class="deep-dive">
            <summary>How targeting resolution works</summary>
            <ol>
                <li><strong>Event target</strong> — checked first. If set for
                    this alliance + event, use it.</li>
                <li><strong>Default target</strong> — checked second. If set
                    for this alliance, use it.</li>
                <li><strong>Faction strategy</strong> — checked third. Uses the
                    faction's algorithm if configured.</li>
                <li><strong>Global strategy</strong> — final fallback.</li>
            </ol>
            <p class="help-text">Within each algorithm, alliances choose targets
                in descending power order. Ties break by higher spice, then
                alphabetical ID.</p>
            <p class="help-text">Available strategies at every level:
                <code>expected_value</code>, <code>highest_spice</code>,
                <code>rank_aware</code>, <code>maximize_tier</code>.</p>
        </details>
    </details>`;
}

function eventTargetRow(attackerIds, defenderIds, selectedAid, isPinned, target, strategy, eventKey) {
    return `
    <tr class="dynamic-row" data-section="event_targets" data-event="${eventKey}">
        <td>${allianceDropdown(attackerIds, selectedAid, "et-alliance")}</td>
        <td>
            <select class="dt-type">
                <option value="pin" ${isPinned ? "selected" : ""}>Pin to target</option>
                <option value="strategy" ${!isPinned ? "selected" : ""}>Use strategy</option>
            </select>
        </td>
        <td>
            <span class="dt-pin-value ${isPinned ? "" : "hidden"}">
                ${allianceDropdown(defenderIds, target, "et-target")}
            </span>
            <span class="dt-strategy-value ${isPinned ? "hidden" : ""}">
                ${strategyDropdown(strategy, "et-strategy")}
            </span>
        </td>
        <td><button class="remove-row-btn" title="Remove">&times;</button></td>
        <td class="row-error-cell"></td>
    </tr>`;
}

function buildEventReinforcements(alliances, events) {
    const er = modelFormData.event_reinforcements || {};
    const byFaction = alliancesByFaction(alliances);
    const factions = Object.keys(byFaction);

    let sections = "";
    for (const event of events) {
        const eventKey = String(event.number);
        const defenderFaction = factions.find(f => f !== event.attacker_faction);
        const defenderIds = byFaction[defenderFaction] || [];
        const overrides = er[eventKey] || {};

        let rows = "";
        for (const [defender, target] of Object.entries(overrides)) {
            rows += `
            <tr class="dynamic-row" data-section="event_reinforcements" data-event="${eventKey}">
                <td>${allianceDropdown(defenderIds, defender, "er-defender")}</td>
                <td>${allianceDropdown(defenderIds, target, "er-target")}</td>
                <td><button class="remove-row-btn" title="Remove">&times;</button></td>
            </tr>`;
        }

        sections += `
        <div class="event-subsection" data-event="${eventKey}">
            <h4>Event ${event.number} — ${esc(event.attacker_faction)} attacks (${esc(event.day)})</h4>
            <table class="form-table">
                <tr><th>Defender</th><th>Reinforce (join battle of)</th><th></th></tr>
                ${rows}
            </table>
            <button class="add-row-btn" data-action="add-event-reinforcement" data-event="${eventKey}">
                + Add</button>
        </div>`;
    }

    return `
    <details class="model-section">
        <summary>Event Reinforcements</summary>
        ${sections}
    </details>`;
}

function buildOutcomeMatrix(alliances, events) {
    const matrix = modelFormData.battle_outcome_matrix || {};
    const aids = alliances.map(a => a.id);
    const aidsWithWildcard = ["*", ...aids];
    const days = [...new Set(events.map(e => e.day))];

    let sections = "";
    for (const day of days) {
        const dayMatrix = matrix[day] || {};
        let rows = "";

        for (const [attacker, defenders] of Object.entries(dayMatrix)) {
            for (const [defender, probs] of Object.entries(defenders)) {
                const full = probs.full_success != null
                    ? (probs.full_success * 100).toFixed(1) : "";
                const partial = probs.partial_success != null
                    ? (probs.partial_success * 100).toFixed(1) : "";
                const custom = probs.custom != null ? (probs.custom * 100).toFixed(1) : "";
                const customTheft = probs.custom_theft_percentage != null
                    ? probs.custom_theft_percentage : "";

                rows += `
                <tr class="dynamic-row" data-section="battle_outcome_matrix" data-day="${day}">
                    <td>${wildcardDropdown(aidsWithWildcard, attacker, "bom-attacker")}</td>
                    <td>${wildcardDropdown(aidsWithWildcard, defender, "bom-defender")}</td>
                    <td><input type="number" class="bom-full pct-input" value="${full}"
                               min="0" max="100" step="0.1"></td>
                    <td><input type="number" class="bom-partial pct-input" value="${partial}"
                               min="0" max="100" step="0.1"></td>
                    <td><input type="number" class="bom-custom pct-input" value="${custom}"
                               min="0" max="100" step="0.1" placeholder="—"></td>
                    <td><input type="number" class="bom-custom-theft pct-input" value="${customTheft}"
                               min="0" max="100" step="0.1" placeholder="—"></td>
                    <td><button class="remove-row-btn" title="Remove">&times;</button></td>
                    <td class="row-error-cell"></td>
                </tr>`;
            }
        }

        sections += `
        <div class="day-subsection" data-day="${day}">
            <h4>${capitalize(day)} outcomes</h4>
            <table class="form-table outcome-table">
                <tr>
                    <th>Attacker</th><th>Defender</th>
                    <th>Full %</th><th>Partial %</th>
                    <th>Custom %</th><th>Custom Theft %</th><th></th><th></th>
                </tr>
                ${rows}
            </table>
            <div id="bom-validation-${day}" class="validation-inline hidden"></div>
            <button class="add-row-btn" data-action="add-outcome-row" data-day="${day}">
                + Add row</button>
        </div>`;
    }

    return `
    <details class="model-section key-section" open>
        <summary>Battle Outcomes</summary>
        <p class="help-text">Set the probability (0\u2013100) of <strong>full success</strong>
            and optionally <strong>partial success</strong> for each
            attacker\u2013defender pairing and day. If you only enter full success,
            partial is derived automatically. Fail is implicit (100% minus the
            others). Leave fields blank to use the power-ratio heuristic
            (shown as placeholder values).</p>
        ${sections}
        <details class="deep-dive">
            <summary>How battle outcomes and lookup priority work</summary>
            <ul>
                <li><strong>Full success</strong> \u2014 all buildings destroyed.
                    Theft up to 30% of defender\u2019s spice.</li>
                <li><strong>Partial success</strong> \u2014 side buildings only.
                    Lower theft (5\u201320%).</li>
                <li><strong>Custom</strong> \u2014 you specify the exact theft
                    percentage directly.</li>
                <li><strong>Fail</strong> (implicit) \u2014 the remaining probability
                    after full, partial, and custom. No buildings destroyed, 0%
                    theft.</li>
            </ul>
            <p class="help-text">When multiple attackers hit the same defender,
                stolen spice is split by damage weights.</p>
            <p class="help-text"><strong>Lookup priority:</strong> exact pairing &rarr;
                attacker wildcard (*) &rarr; defender wildcard (*) &rarr; heuristic
                fallback. Wildcards let you set a default for all opponents without
                listing every pairing.</p>
        </details>
    </details>`;
}

function validateOutcomeRow(full, partial, custom) {
    const total = (full || 0) + (partial || 0) + (custom || 0);
    if (total > 100) {
        return `Probabilities sum to ${total.toFixed(1)}% (must be <= 100%)`;
    }
    return null;
}

function validateOutcomeRowFull(row) {
    const errors = [];
    const fullVal = row.querySelector(".bom-full").value;
    const partialVal = row.querySelector(".bom-partial").value;
    const customVal = row.querySelector(".bom-custom").value;
    const customTheftVal = row.querySelector(".bom-custom-theft").value;

    const full = parseFloat(fullVal);
    const partial = parseFloat(partialVal);
    const custom = parseFloat(customVal);
    const customTheft = parseFloat(customTheftVal);

    if (fullVal !== "" && isNaN(full)) {
        errors.push("Full % must be a number");
    }
    if (partialVal !== "" && isNaN(partial)) {
        errors.push("Partial % must be a number");
    }

    const pctFields = [
        [fullVal, full], [partialVal, partial],
        [customVal, custom], [customTheftVal, customTheft],
    ];
    for (const [raw, num] of pctFields) {
        if (raw !== "" && !isNaN(num) && (num < 0 || num > 100)) {
            errors.push("Percentages must be between 0 and 100");
            break;
        }
    }

    const hasCustom = customVal !== "" && !isNaN(custom);
    const hasCustomTheft = customTheftVal !== "" && !isNaN(customTheft);
    if (hasCustom !== hasCustomTheft) {
        errors.push("Custom % and Custom Theft % must both be set");
    }

    const fVal = (fullVal !== "" && !isNaN(full)) ? full : 0;
    const pVal = (partialVal !== "" && !isNaN(partial)) ? partial : 0;
    const cVal = (customVal !== "" && !isNaN(custom)) ? custom : 0;
    if (fVal + pVal + cVal > 100) {
        errors.push("Probabilities exceed 100%");
    }

    return errors;
}

function validateDamageWeightRow(row) {
    const errors = [];
    const weightVal = row.querySelector(".dw-weight").value;
    const weight = parseFloat(weightVal);

    if (weightVal === "" || isNaN(weight)) {
        errors.push("Weight must be a number");
    } else if (weight < 0 || weight > 1) {
        errors.push("Weight must be between 0 and 1");
    }

    return errors;
}

function buildDamageWeights(alliances) {
    const dw = modelFormData.damage_weights || {};
    const aids = alliances.map(a => a.id);

    let rows = "";
    for (const [aid, weight] of Object.entries(dw)) {
        rows += `
        <tr class="dynamic-row" data-section="damage_weights">
            <td>${allianceDropdown(aids, aid, "dw-alliance")}</td>
            <td><input type="number" class="dw-weight" value="${weight}"
                       min="0" max="1" step="0.05"></td>
            <td><button class="remove-row-btn" title="Remove">&times;</button></td>
            <td class="row-error-cell"></td>
        </tr>`;
    }

    return `
    <details class="model-section">
        <summary>Damage Weights</summary>
        <p class="help-text">Only relevant when multiple attackers target the same defender.
            Weights are normalized to sum to 1.</p>
        <table class="form-table" id="damage-weights-table">
            <tr><th>Alliance</th><th>Weight</th><th></th><th></th></tr>
            ${rows}
        </table>
        <button class="add-row-btn" data-action="add-damage-weight">+ Add</button>
    </details>`;
}

// --- Shared Dropdown Helpers ---

function allianceDropdown(aids, selected, className) {
    let html = `<select class="${className}">`;
    for (const aid of aids) {
        html += `<option value="${esc(aid)}" ${aid === selected ? "selected" : ""}>${esc(aid)}</option>`;
    }
    html += "</select>";
    return html;
}

function wildcardDropdown(aids, selected, className) {
    let html = `<select class="${className}">`;
    for (const aid of aids) {
        const label = aid === "*" ? "* (any)" : aid;
        html += `<option value="${esc(aid)}" ${aid === selected ? "selected" : ""}>${esc(label)}</option>`;
    }
    html += "</select>";
    return html;
}

function strategyDropdown(selected, className) {
    return `
    <select class="${className}">
        ${strategyOptions(selected)}
    </select>`;
}

function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
}

// --- Heuristic Probability Hints ---

function getAlliancePower() {
    if (!currentStateDict) return {};
    const power = {};
    for (const a of currentStateDict.alliances) {
        power[a.alliance_id] = a.power;
    }
    return power;
}

function computeHeuristicHints(attackerId, defenderId, day) {
    const power = getAlliancePower();
    const aPower = power[attackerId];
    const dPower = power[defenderId];
    if (!aPower || !dPower) return null;

    return PyBridge.computeHeuristic(aPower, dPower, day);
}

function updateHeuristicPlaceholders(row, day) {
    const attacker = row.querySelector(".bom-attacker").value;
    const defender = row.querySelector(".bom-defender").value;
    const fullInput = row.querySelector(".bom-full");
    const partialInput = row.querySelector(".bom-partial");

    if (attacker === "*" || defender === "*") {
        fullInput.placeholder = "";
        partialInput.placeholder = "";
        return;
    }

    const hints = computeHeuristicHints(attacker, defender, day);
    if (hints) {
        fullInput.placeholder = `~${hints.full}`;
        partialInput.placeholder = `~${hints.partial}`;
    } else {
        fullInput.placeholder = "";
        partialInput.placeholder = "";
    }
}

function initHeuristicPlaceholders() {
    const daySections = document.querySelectorAll(".day-subsection");
    for (const section of daySections) {
        const day = section.dataset.day;
        const rows = section.querySelectorAll(".dynamic-row");
        for (const row of rows) {
            updateHeuristicPlaceholders(row, day);
        }
    }
}

// --- Form Event Handling ---

function attachFormHandlers() {
    if (formHandlersAttached) return;
    formHandlersAttached = true;

    const form = document.getElementById("model-form");

    form.addEventListener("input", () => {
        collectFormData();
        scheduleModelValidation();
    });

    form.addEventListener("change", (e) => {
        // Handle type toggle (pin/strategy) visibility
        if (e.target.classList.contains("dt-type")) {
            const row = e.target.closest("tr");
            row.querySelector(".dt-pin-value").classList.toggle("hidden", e.target.value !== "pin");
            row.querySelector(".dt-strategy-value").classList.toggle("hidden", e.target.value === "pin");
        }
        // Show/hide maximize_tier options when global strategy changes
        if (e.target.id === "form-strategy") {
            const tierOpts = document.getElementById("maximize-tier-options");
            if (tierOpts) {
                tierOpts.classList.toggle("hidden", e.target.value !== "maximize_tier");
            }
        }
        // Update heuristic placeholders when attacker/defender changes
        if (e.target.classList.contains("bom-attacker") || e.target.classList.contains("bom-defender")) {
            const row = e.target.closest("tr");
            const daySection = row.closest(".day-subsection");
            if (daySection) updateHeuristicPlaceholders(row, daySection.dataset.day);
        }
        collectFormData();
        scheduleModelValidation();
    });

    form.addEventListener("click", (e) => {
        if (e.target.classList.contains("remove-row-btn")) {
            e.target.closest("tr").remove();
            collectFormData();
            scheduleModelValidation();
        }

        if (e.target.classList.contains("add-row-btn")) {
            handleAddRow(e.target);
        }
    });
}

function handleAddRow(button) {
    const action = button.dataset.action;
    const table = button.previousElementSibling?.tagName === "DIV"
        ? button.parentElement.querySelector("table")
        : button.previousElementSibling;
    const alliances = getAlliancesFromState();
    const aids = alliances.map(a => a.id);

    let newRow = "";
    switch (action) {
        case "add-default-target":
            newRow = defaultTargetRow(aids, aids[0], true, aids[0], "");
            break;
        case "add-event-target": {
            const eventKey = button.dataset.event;
            const events = getEventsFromState();
            const event = events.find(e => String(e.number) === eventKey);
            const byFaction = alliancesByFaction(alliances);
            const factions = Object.keys(byFaction);
            const defenderFaction = factions.find(f => f !== event.attacker_faction);
            newRow = eventTargetRow(
                byFaction[event.attacker_faction], byFaction[defenderFaction],
                byFaction[event.attacker_faction][0], true, byFaction[defenderFaction][0], "",
                eventKey
            );
            break;
        }
        case "add-event-reinforcement": {
            const eventKey = button.dataset.event;
            const events = getEventsFromState();
            const event = events.find(e => String(e.number) === eventKey);
            const byFaction = alliancesByFaction(alliances);
            const factions = Object.keys(byFaction);
            const defenderFaction = factions.find(f => f !== event.attacker_faction);
            const defenderIds = byFaction[defenderFaction];
            newRow = `
            <tr class="dynamic-row" data-section="event_reinforcements" data-event="${eventKey}">
                <td>${allianceDropdown(defenderIds, defenderIds[0], "er-defender")}</td>
                <td>${allianceDropdown(defenderIds, defenderIds[0], "er-target")}</td>
                <td><button class="remove-row-btn" title="Remove">&times;</button></td>
            </tr>`;
            break;
        }
        case "add-outcome-row": {
            const day = button.dataset.day;
            const aidsWithWildcard = ["*", ...aids];
            newRow = `
            <tr class="dynamic-row" data-section="battle_outcome_matrix" data-day="${day}">
                <td>${wildcardDropdown(aidsWithWildcard, aids[0], "bom-attacker")}</td>
                <td>${wildcardDropdown(aidsWithWildcard, aids[0], "bom-defender")}</td>
                <td><input type="number" class="bom-full pct-input" value="" min="0" max="100" step="0.1"></td>
                <td><input type="number" class="bom-partial pct-input" value="" min="0" max="100" step="0.1"></td>
                <td><input type="number" class="bom-custom pct-input" value="" min="0" max="100" step="0.1" placeholder="—"></td>
                <td><input type="number" class="bom-custom-theft pct-input" value="" min="0" max="100" step="0.1" placeholder="—"></td>
                <td><button class="remove-row-btn" title="Remove">&times;</button></td>
                <td class="row-error-cell"></td>
            </tr>`;
            break;
        }
        case "add-damage-weight":
            newRow = `
            <tr class="dynamic-row" data-section="damage_weights">
                <td>${allianceDropdown(aids, aids[0], "dw-alliance")}</td>
                <td><input type="number" class="dw-weight" value="0.5" min="0" max="1" step="0.05"></td>
                <td><button class="remove-row-btn" title="Remove">&times;</button></td>
                <td class="row-error-cell"></td>
            </tr>`;
            break;
    }

    if (newRow && table) {
        table.querySelector("tr:last-child").insertAdjacentHTML("afterend", newRow);
        // Update heuristic placeholders on newly added outcome rows
        if (action === "add-outcome-row") {
            const addedRow = table.querySelector("tr:last-child");
            const daySection = addedRow.closest(".day-subsection");
            if (daySection) updateHeuristicPlaceholders(addedRow, daySection.dataset.day);
        }
        collectFormData();
        scheduleModelValidation();
    }
}

// --- Collecting Form Data ---

function collectFormData() {
    const data = {};

    // General settings
    const seedVal = document.getElementById("form-seed")?.value;
    if (seedVal !== "" && seedVal != null) {
        data.random_seed = parseInt(seedVal, 10);
    }
    const strategyVal = document.getElementById("form-strategy")?.value;
    if (strategyVal) {
        data.targeting_strategy = strategyVal;
    }

    // Tier optimization fields — always update stash, only emit when maximize_tier
    const topNEl = document.getElementById("form-tier-top-n");
    const fallbackEl = document.getElementById("form-tier-fallback");
    if (topNEl?.value) _tierOptsStash.top_n = parseInt(topNEl.value, 10);
    if (fallbackEl?.value) _tierOptsStash.fallback = fallbackEl.value;
    if (data.targeting_strategy === "maximize_tier") {
        data.tier_optimization_top_n = _tierOptsStash.top_n;
        data.tier_optimization_fallback = _tierOptsStash.fallback;
    }

    // MC randomness parameters
    for (const [id, key] of [
        ["form-targeting-temp", "targeting_temperature"],
        ["form-power-noise", "power_noise"],
        ["form-outcome-noise", "outcome_noise"],
    ]) {
        const val = document.getElementById(id)?.value;
        if (val !== "" && val != null) {
            const num = parseFloat(val);
            if (num > 0) data[key] = num;
        }
    }

    // Faction targeting strategy
    const ftsSelects = document.querySelectorAll('[data-field="faction_targeting_strategy"]');
    const fts = {};
    for (const sel of ftsSelects) {
        if (sel.value) {
            fts[sel.dataset.faction] = sel.value;
        }
    }
    if (Object.keys(fts).length > 0) data.faction_targeting_strategy = fts;

    // Default targets
    const dtRows = document.querySelectorAll('#default-targets-table .dynamic-row');
    const dt = {};
    const dtSeen = new Set();
    for (const row of dtRows) {
        const aid = row.querySelector(".dt-alliance").value;
        const errorCell = row.querySelector(".row-error-cell");
        if (dtSeen.has(aid)) {
            row.classList.add("validation-error");
            if (errorCell) errorCell.textContent = "Duplicate alliance \u2014 only the last entry will apply";
        } else {
            row.classList.remove("validation-error");
            if (errorCell) errorCell.textContent = "";
        }
        dtSeen.add(aid);

        const type = row.querySelector(".dt-type").value;
        if (type === "pin") {
            dt[aid] = { target: row.querySelector(".dt-target").value };
        } else {
            dt[aid] = { strategy: row.querySelector(".dt-strategy").value };
        }
    }
    if (Object.keys(dt).length > 0) data.default_targets = dt;

    // Event targets
    const etContainers = document.querySelectorAll(
        '[data-action="add-event-target"]');
    const et = {};
    for (const btn of etContainers) {
        const eventKey = btn.dataset.event;
        const rows = btn.parentElement.querySelectorAll('.dynamic-row');
        const overrides = {};
        const etSeen = new Set();
        for (const row of rows) {
            const aid = row.querySelector(".et-alliance")?.value;
            const errorCell = row.querySelector(".row-error-cell");
            if (etSeen.has(aid)) {
                row.classList.add("validation-error");
                if (errorCell) errorCell.textContent = "Duplicate alliance \u2014 only the last entry will apply";
            } else {
                row.classList.remove("validation-error");
                if (errorCell) errorCell.textContent = "";
            }
            etSeen.add(aid);

            const type = row.querySelector(".dt-type")?.value;
            if (type === "pin") {
                const target = row.querySelector(".et-target")?.value;
                overrides[aid] = target;
            } else {
                overrides[aid] = { strategy: row.querySelector(".et-strategy")?.value };
            }
        }
        if (Object.keys(overrides).length > 0) et[eventKey] = overrides;
    }
    if (Object.keys(et).length > 0) data.event_targets = et;

    // Event reinforcements
    const erContainers = document.querySelectorAll(
        '[data-action="add-event-reinforcement"]');
    const er = {};
    for (const btn of erContainers) {
        const eventKey = btn.dataset.event;
        const rows = btn.parentElement.querySelectorAll('.dynamic-row');
        const overrides = {};
        for (const row of rows) {
            const defender = row.querySelector(".er-defender").value;
            const target = row.querySelector(".er-target").value;
            overrides[defender] = target;
        }
        if (Object.keys(overrides).length > 0) er[eventKey] = overrides;
    }
    if (Object.keys(er).length > 0) data.event_reinforcements = er;

    // Battle outcome matrix
    const bomDays = document.querySelectorAll(".day-subsection");
    const matrix = {};
    for (const daySection of bomDays) {
        const day = daySection.dataset.day;
        const rows = daySection.querySelectorAll(".dynamic-row");
        const dayMatrix = {};
        for (const row of rows) {
            const attacker = row.querySelector(".bom-attacker").value;
            const defender = row.querySelector(".bom-defender").value;
            const fullVal = row.querySelector(".bom-full").value;
            const partialVal = row.querySelector(".bom-partial").value;
            const customVal = row.querySelector(".bom-custom").value;
            const customTheftVal = row.querySelector(".bom-custom-theft").value;
            const full = parseFloat(fullVal);
            const partial = parseFloat(partialVal);

            // Inline validation
            const rowErrors = validateOutcomeRowFull(row);
            const errorCell = row.querySelector(".row-error-cell");
            if (rowErrors.length > 0) {
                row.classList.add("validation-error");
                if (errorCell) errorCell.innerHTML = rowErrors.map(e => `<div class="row-error-msg">${esc(e)}</div>`).join("");
            } else {
                row.classList.remove("validation-error");
                if (errorCell) errorCell.innerHTML = "";
            }

            // Skip truly empty rows (both full and partial blank)
            if (fullVal === "" && partialVal === "") continue;

            const probs = {};
            if (!isNaN(full)) {
                probs.full_success = full / 100;
            }
            if (!isNaN(partial)) {
                probs.partial_success = partial / 100;
            }
            if (customVal !== "" && !isNaN(parseFloat(customVal))) {
                probs.custom = parseFloat(customVal) / 100;
            }
            if (customTheftVal !== "" && !isNaN(parseFloat(customTheftVal))) {
                probs.custom_theft_percentage = parseFloat(customTheftVal);
            }

            if (!dayMatrix[attacker]) dayMatrix[attacker] = {};
            dayMatrix[attacker][defender] = probs;
        }
        if (Object.keys(dayMatrix).length > 0) matrix[day] = dayMatrix;
    }
    if (Object.keys(matrix).length > 0) data.battle_outcome_matrix = matrix;

    // Damage weights
    const dwRows = document.querySelectorAll('#damage-weights-table .dynamic-row');
    const dw = {};
    for (const row of dwRows) {
        const aid = row.querySelector(".dw-alliance").value;
        const weight = parseFloat(row.querySelector(".dw-weight").value);

        const dwErrors = validateDamageWeightRow(row);
        const dwErrorCell = row.querySelector(".row-error-cell");
        if (dwErrors.length > 0) {
            row.classList.add("validation-error");
            if (dwErrorCell) dwErrorCell.innerHTML = dwErrors.map(e => `<div class="row-error-msg">${esc(e)}</div>`).join("");
        } else {
            row.classList.remove("validation-error");
            if (dwErrorCell) dwErrorCell.innerHTML = "";
        }

        if (!isNaN(weight)) dw[aid] = weight;
    }
    if (Object.keys(dw).length > 0) data.damage_weights = dw;

    modelFormData = data;
    syncFormToJson();
}

// --- Form <-> JSON Synchronization ---

function syncFormToJson() {
    const textarea = document.getElementById("model-textarea");
    textarea.value = JSON.stringify(modelFormData, null, 2);
}

function syncJsonToForm() {
    const textarea = document.getElementById("model-textarea");
    let parsed;
    try {
        parsed = JSON.parse(textarea.value);
    } catch {
        // If JSON is invalid, stay in JSON view and show error
        return false;
    }

    // Seed tier options stash from loaded JSON
    if (parsed.tier_optimization_top_n != null) {
        _tierOptsStash.top_n = parsed.tier_optimization_top_n;
    }
    if (parsed.tier_optimization_fallback != null) {
        _tierOptsStash.fallback = parsed.tier_optimization_fallback;
    }

    modelFormData = parsed;
    buildModelForm();
    return true;
}

function scheduleModelValidation() {
    clearTimeout(modelValidationTimer);
    modelValidationTimer = setTimeout(() => {
        // Textarea is already synced by syncFormToJson(), reuse existing validateModel()
        validateModel();
    }, 300);
}

// --- View Toggle ---

function toggleModelView() {
    const toggleBtn = document.getElementById("model-view-toggle");
    const formDiv = document.getElementById("model-form");
    const jsonDiv = document.getElementById("model-json-view");

    if (modelViewMode === "form") {
        // Switching to JSON view — form is already synced
        modelViewMode = "json";
        formDiv.classList.add("hidden");
        jsonDiv.classList.remove("hidden");
        toggleBtn.textContent = "Back to form";
    } else {
        // Switching to form view — parse JSON and rebuild
        const success = syncJsonToForm();
        if (!success) {
            // JSON is invalid, can't switch. The validation error is already visible.
            return;
        }
        modelViewMode = "form";
        jsonDiv.classList.add("hidden");
        formDiv.classList.remove("hidden");
        toggleBtn.textContent = "Edit as JSON";
    }
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

// --- Results Helpers ---

function getAllianceFaction() {
    if (!currentStateDict) return {};
    const factions = {};
    for (const a of currentStateDict.alliances) {
        factions[a.alliance_id] = a.faction;
    }
    return factions;
}

function computeRanks(spiceMap) {
    const sorted = Object.entries(spiceMap)
        .sort((a, b) => b[1] - a[1]);
    const ranks = {};
    for (let i = 0; i < sorted.length; i++) {
        ranks[sorted[i][0]] = i + 1;
    }
    return ranks;
}

function rankChangeIndicator(beforeRank, afterRank) {
    if (afterRank < beforeRank) {
        return '<span class="rank-up">\u2191</span>';       // ↑ green
    } else if (afterRank > beforeRank) {
        return '<span class="rank-down">\u2193</span>';     // ↓ red
    }
    return '<span class="rank-same">\u2014</span>';         // — grey
}

function getAllianceBracket(eventBrackets) {
    const bracketMap = {};
    for (const [bracketNum, group] of Object.entries(eventBrackets)) {
        const num = parseInt(bracketNum, 10);
        const label = `${(num - 1) * 10 + 1}-${num * 10}`;
        for (const aid of group.attackers) {
            bracketMap[aid] = label;
        }
        for (const aid of group.defenders) {
            bracketMap[aid] = label;
        }
    }
    return bracketMap;
}

function getFilteredAlliances(filter) {
    if (filter === "all" || !currentStateDict) return null;

    const n = parseInt(filter.replace("top", ""), 10);
    const byFaction = {};
    for (const a of currentStateDict.alliances) {
        if (!byFaction[a.faction]) byFaction[a.faction] = [];
        byFaction[a.faction].push(a);
    }

    const allowed = new Set();
    for (const faction of Object.keys(byFaction)) {
        const sorted = byFaction[faction].sort((a, b) => b.power - a.power);
        for (let i = 0; i < Math.min(n, sorted.length); i++) {
            allowed.add(sorted[i].alliance_id);
        }
    }
    return allowed;
}

function renderSingleResults(result) {
    const container = document.getElementById("results-content");
    const section = document.getElementById("results");
    section.classList.remove("hidden");
    document.getElementById("result-filter").classList.remove("hidden");

    const factions = getAllianceFaction();
    const allowed = getFilteredAlliances(resultFilter);

    const entries = Object.entries(result.final_spice)
        .map(([id, spice]) => ({ id, spice, tier: result.rankings[id] }));
    entries.sort((a, b) => a.tier - b.tier || b.spice - a.spice);

    let html = `<p class="help-text">Expand each event to see targeting decisions,
        battle outcomes, and spice transfers. Rank arrows show movement from the
        previous event.</p>`;
    html += `<h3>Final Rankings (seed: ${result.seed})</h3>`;
    html += "<table><tr><th>Faction</th><th>Alliance</th><th>Rank</th><th>Tier</th><th>Final Spice</th></tr>";
    for (let i = 0; i < entries.length; i++) {
        const e = entries[i];
        if (allowed && !allowed.has(e.id)) continue;
        html += `<tr>
            <td>${esc(factions[e.id] || "")}</td>
            <td>${esc(e.id)}</td>
            <td>${i + 1}</td>
            <td>${e.tier}</td>
            <td>${e.spice.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    html += "<h3>Event Details</h3>";
    for (const event of result.event_history) {
        html += `<details>
            <summary>Event ${event.event_number}: ${esc(event.attacker_faction)} (${esc(event.day)})</summary>
            ${renderEventDetail(event, allowed)}
        </details>`;
    }

    container.innerHTML = html;
}

function renderEventDetail(event, allowed) {
    const factions = getAllianceFaction();
    const beforeRanks = computeRanks(event.spice_before);
    const afterRanks = computeRanks(event.spice_after);
    const bracketMap = event.brackets ? getAllianceBracket(event.brackets) : {};
    let html = "";

    html += "<h4>Spice</h4><table>";
    html += "<tr><th>Faction</th><th>Alliance</th><th>Before Rank</th><th>After Rank</th>"
          + "<th>Before</th><th>After</th><th>Change</th></tr>";
    const spiceEntries = Object.entries(event.spice_before)
        .sort((a, b) => afterRanks[a[0]] - afterRanks[b[0]]);
    for (const [id, before] of spiceEntries) {
        if (allowed && !allowed.has(id)) continue;
        const after = event.spice_after[id];
        const change = after - before;
        const sign = change >= 0 ? "+" : "";
        const br = beforeRanks[id];
        const ar = afterRanks[id];
        html += `<tr>
            <td>${esc(factions[id] || "")}</td>
            <td>${esc(id)}</td>
            <td>${br}</td>
            <td>${ar} ${rankChangeIndicator(br, ar)}</td>
            <td>${before.toLocaleString()}</td>
            <td>${after.toLocaleString()}</td>
            <td>${sign}${change.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    html += "<h4>Targeting</h4><table>";
    html += "<tr><th>Bracket</th><th>Attacker</th><th>Attacker Rank</th><th>Defender</th><th>Defender Rank</th></tr>";
    for (const [att, def_] of Object.entries(event.targeting)) {
        if (allowed && !allowed.has(att)) continue;
        html += `<tr>
            <td>${bracketMap[att] || "\u2014"}</td>
            <td>${esc(att)}</td>
            <td>${beforeRanks[att] || "\u2014"}</td>
            <td>${esc(def_)}</td>
            <td>${beforeRanks[def_] || "\u2014"}</td>
        </tr>`;
    }
    html += "</table>";

    html += "<h4>Battles</h4>";
    for (const battle of event.battles) {
        const battleAlliances = [...battle.attackers, ...battle.defenders];
        if (allowed && !battleAlliances.some(id => allowed.has(id))) continue;

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
            html += "<table><tr><th>Faction</th><th>Alliance</th><th>Transfer</th></tr>";
            for (const [id, amount] of Object.entries(battle.transfers)) {
                const sign = amount >= 0 ? "+" : "";
                html += `<tr>
                    <td>${esc(factions[id] || "")}</td>
                    <td>${esc(id)}</td>
                    <td>${sign}${amount.toLocaleString()}</td>
                </tr>`;
            }
            html += "</table>";
        }
        html += "</div>";
    }

    return html;
}

// --- Monte Carlo ---

function hasMaximizeTier(modelDict) {
    if (modelDict.targeting_strategy === "maximize_tier") return true;
    const fts = modelDict.faction_targeting_strategy || {};
    return Object.values(fts).includes("maximize_tier");
}

async function runMonteCarlo() {
    const stateDict = JSON.parse(document.getElementById("state-textarea").value);
    const modelDict = JSON.parse(document.getElementById("model-textarea").value);
    const iterations = parseInt(document.getElementById("mc-iterations").value, 10) || 1000;
    const baseSeed = parseInt(document.getElementById("mc-base-seed").value, 10) || 0;

    // Show/hide performance warning for maximize_tier
    const warningEl = document.getElementById("mc-tier-warning");
    if (warningEl) {
        warningEl.classList.toggle("hidden", !hasMaximizeTier(modelDict));
    }

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
    document.getElementById("result-filter").classList.remove("hidden");

    const factions = getAllianceFaction();
    const allowed = getFilteredAlliances(resultFilter);

    const allAids = Object.keys(result.tier_distribution);
    const aids = allAids.filter(aid => !allowed || allowed.has(aid));
    aids.sort((a, b) => {
        const aT1 = parseFloat(result.tier_distribution[a]["1"] || 0);
        const bT1 = parseFloat(result.tier_distribution[b]["1"] || 0);
        return bT1 - aT1;
    });

    let html = `<p class="help-text"><strong>Tier distribution</strong> shows the
        % chance each alliance finishes in each tier (T1 = rank 1, T2 = ranks 2\u20133,
        T3 = 4\u201310, T4 = 11\u201320, T5 = 21+). The <strong>targeting matrix</strong>
        below shows how often each attacker targeted each defender across all
        iterations.</p>`;
    html += `<h3>Tier Distribution (${result.num_iterations} iterations)</h3>`;
    html += "<table><tr><th>Faction</th><th>Alliance</th>";
    for (let t = 1; t <= 5; t++) html += `<th>T${t}</th>`;
    html += "</tr>";
    for (const aid of aids) {
        html += `<tr><td>${esc(factions[aid] || "")}</td><td>${esc(aid)}</td>`;
        const dist = result.tier_distribution[aid];
        for (let t = 1; t <= 5; t++) {
            const frac = parseFloat(dist[String(t)] || 0);
            const pct = (frac * 100).toFixed(1);
            if (frac > 0) {
                html += `<td class="tier-cell-clickable" data-aid="${esc(aid)}" data-tier="${t}" title="Click to see an example run">${pct}%</td>`;
            } else {
                html += `<td>${pct}%</td>`;
            }
        }
        html += "</tr>";
    }
    html += "</table>";

    html += "<h3>Spice Statistics</h3>";
    html += "<table><tr><th>Faction</th><th>Alliance</th><th>Mean</th><th>Median</th>";
    html += "<th>Min</th><th>Max</th><th>P25</th><th>P75</th></tr>";
    for (const aid of aids) {
        const s = result.spice_stats[aid];
        html += `<tr>
            <td>${esc(factions[aid] || "")}</td>
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

    if (result.targeting_matrix) {
        const powerMap = {};
        for (const a of currentStateDict.alliances) {
            powerMap[a.alliance_id] = a.power;
        }
        const byPowerDesc = (a, b) => (powerMap[b] || 0) - (powerMap[a] || 0);

        const eventNums = Object.keys(result.targeting_matrix).sort((a, b) => +a - +b);
        for (const eventNum of eventNums) {
            const eventData = result.targeting_matrix[eventNum];
            const idx = parseInt(eventNum, 10) - 1;
            const evCfg = currentStateDict.event_schedule[idx];

            let attackers = Object.keys(eventData);
            let defenders = new Set();
            for (const att of attackers) {
                for (const def_ of Object.keys(eventData[att])) defenders.add(def_);
            }
            defenders = [...defenders];

            if (allowed) {
                attackers = attackers.filter(a => allowed.has(a));
                defenders = defenders.filter(d => allowed.has(d));
            }
            if (!attackers.length || !defenders.length) continue;

            attackers.sort(byPowerDesc);
            defenders.sort(byPowerDesc);

            html += `<h3>Event ${esc(eventNum)} — ${esc(evCfg.attacker_faction)} attacks (${esc(evCfg.day)})</h3>`;
            html += "<table><tr><th></th>";
            for (const d of defenders) html += `<th>${esc(d)}</th>`;
            html += "</tr>";
            for (const att of attackers) {
                html += `<tr><td>${esc(att)}</td>`;
                for (const def_ of defenders) {
                    const frac = (eventData[att] || {})[def_] || 0;
                    html += `<td>${frac ? (frac * 100).toFixed(1) + "%" : ""}</td>`;
                }
                html += "</tr>";
            }
            html += "</table>";
        }
    }

    container.innerHTML = html;

    // Delegated click handler for tier distribution cells
    container.addEventListener("click", async (e) => {
        const cell = e.target.closest(".tier-cell-clickable");
        if (!cell || !lastResult || !lastResult.raw_results) return;

        const aid = cell.dataset.aid;
        const tier = parseInt(cell.dataset.tier, 10);

        const matching = lastResult.raw_results
            .filter(r => r.rankings[aid] === tier)
            .sort((a, b) => a.seed - b.seed);
        if (!matching.length) return;

        await showExampleRunModal(aid, tier, matching, 0);
    });

    renderTierChart(aids, result.tier_distribution);
    renderSpiceChart(aids, result.spice_stats);
}

// --- Example Run Modal ---

async function showExampleRunModal(aid, tier, matching, index) {
    const stateDict = JSON.parse(document.getElementById("state-textarea").value);
    const modelDict = JSON.parse(document.getElementById("model-textarea").value);
    const result = await PyBridge.runSingle(stateDict, modelDict, matching[index].seed);
    if (!result.ok) return;

    const existing = document.getElementById("example-run-modal");
    if (existing) existing.remove();

    const factions = getAllianceFaction();
    const allowed = getFilteredAlliances(resultFilter);
    const ranks = computeRanks(result.final_spice);

    const overlay = document.createElement("div");
    overlay.id = "example-run-modal";
    overlay.className = "modal-overlay";

    let html = '<div class="modal-content">';
    html += '<button class="modal-close">&times;</button>';
    html += `<h2>Example: ${esc(aid)} finishing T${tier} — seed ${result.seed}</h2>`;
    const factionName = factions[aid] || "";
    if (factionName) {
        html += `<p class="help-text">Faction: ${esc(factionName)}</p>`;
    }

    // Navigation controls
    html += '<div class="modal-nav">';
    html += `<button class="modal-prev"${index === 0 ? " disabled" : ""}>&larr; Prev</button>`;
    html += `<span>${index + 1} of ${matching.length}</span>`;
    html += `<button class="modal-next"${index === matching.length - 1 ? " disabled" : ""}>Next &rarr;</button>`;
    html += '</div>';

    // Final rankings table
    const entries = Object.entries(result.final_spice)
        .map(([id, spice]) => ({ id, spice, tier: result.rankings[id], rank: ranks[id] }));
    entries.sort((a, b) => a.rank - b.rank);

    html += "<h3>Final Rankings</h3>";
    html += "<table><tr><th>Faction</th><th>Alliance</th><th>Rank</th><th>Tier</th><th>Final Spice</th></tr>";
    for (const e of entries) {
        if (allowed && !allowed.has(e.id)) continue;
        const highlight = e.id === aid ? ' style="background:#fffde7"' : "";
        html += `<tr${highlight}>
            <td>${esc(factions[e.id] || "")}</td>
            <td>${esc(e.id)}</td>
            <td>${e.rank}</td>
            <td>T${e.tier}</td>
            <td>${e.spice.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    // Event-by-event breakdown
    html += "<h3>Event History</h3>";
    for (let i = 0; i < result.event_history.length; i++) {
        const event = result.event_history[i];
        html += `<details><summary>Event ${event.event_number}: ${esc(event.attacker_faction)} (${esc(event.day)})</summary>`;
        html += renderEventDetail(event, allowed);
        html += "</details>";
    }

    html += "</div>";
    overlay.innerHTML = html;
    document.body.appendChild(overlay);

    // Navigation handlers
    overlay.querySelector(".modal-prev").addEventListener("click", () => {
        if (index > 0) showExampleRunModal(aid, tier, matching, index - 1);
    });
    overlay.querySelector(".modal-next").addEventListener("click", () => {
        if (index < matching.length - 1) showExampleRunModal(aid, tier, matching, index + 1);
    });

    // Close handlers
    overlay.querySelector(".modal-close").addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) overlay.remove();
    });
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

// --- Notifications ---

function showNotification(message, type = "info") {
    const existing = document.querySelector(".notification");
    if (existing) existing.remove();

    const el = document.createElement("div");
    el.className = `notification notification-${type}`;
    el.textContent = message;
    document.body.appendChild(el);

    setTimeout(() => el.remove(), 3000);
}

// --- Shareable URL ---

async function encodeModelToHash() {
    const payload = {
        v: 2,
        model: JSON.parse(document.getElementById("model-textarea").value),
        seed: document.getElementById("single-seed").value || null,
        mcIterations: parseInt(document.getElementById("mc-iterations").value, 10) || 1000,
        mcBaseSeed: parseInt(document.getElementById("mc-base-seed").value, 10) || 0,
    };

    const json = JSON.stringify(payload);
    const bytes = new TextEncoder().encode(json);

    const cs = new CompressionStream("deflate");
    const writer = cs.writable.getWriter();
    writer.write(bytes);
    writer.close();

    const compressed = await new Response(cs.readable).arrayBuffer();
    const compressedBytes = new Uint8Array(compressed);

    let base64 = btoa(String.fromCharCode(...compressedBytes));
    base64 = base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

    return `v2:${base64}`;
}

async function decodeHashToConfig(hash) {
    let version, base64url;
    if (hash.startsWith("v2:")) {
        version = 2;
        base64url = hash.slice(3);
    } else if (hash.startsWith("v1:")) {
        version = 1;
        base64url = hash.slice(3);
    } else {
        return null;
    }

    let base64 = base64url.replace(/-/g, "+").replace(/_/g, "/");
    while (base64.length % 4) base64 += "=";

    const compressed = Uint8Array.from(atob(base64), c => c.charCodeAt(0));

    const ds = new DecompressionStream("deflate");
    const writer = ds.writable.getWriter();
    writer.write(compressed);
    writer.close();

    const decompressed = await new Response(ds.readable).arrayBuffer();
    const json = new TextDecoder().decode(decompressed);

    const config = JSON.parse(json);
    config.v = version;
    return config;
}

async function shareConfig() {
    try {
        const hash = await encodeModelToHash();
        const url = `${window.location.origin}${window.location.pathname}#${hash}`;

        if (url.length > 8000) {
            showNotification("Configuration too large to share via URL", "error");
            return;
        }

        window.location.hash = hash;
        await navigator.clipboard.writeText(url);
        showNotification("Model link copied \u2014 recipient needs the same game state loaded");
    } catch (e) {
        showNotification("Failed to generate share link: " + e.message, "error");
    }
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

    // Model editor — JSON textarea still gets direct input handler for JSON-view editing
    document.getElementById("model-textarea").addEventListener("input", onModelInput);
    document.getElementById("model-upload-btn").addEventListener("click", () => {
        document.getElementById("model-file-input").click();
    });
    document.getElementById("model-file-input").addEventListener("change", (e) => {
        readFileToTextarea(e.target.files[0], "model-textarea", () => {
            syncJsonToForm();
            validateModel();
        });
    });

    // View toggle
    document.getElementById("model-view-toggle").addEventListener("click", toggleModelView);

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
                syncJsonToForm();
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

    // Filter buttons
    document.getElementById("result-filter").addEventListener("click", (e) => {
        if (!e.target.classList.contains("filter-btn")) return;
        for (const btn of document.querySelectorAll(".filter-btn")) {
            btn.classList.toggle("active", btn === e.target);
        }
        resultFilter = e.target.dataset.filter;
        if (lastResult) {
            if (lastResult.event_history) {
                renderSingleResults(lastResult);
            } else {
                renderMonteCarloResults(lastResult);
            }
        }
    });

    // Run buttons
    document.getElementById("run-single-btn").addEventListener("click", runSingle);
    document.getElementById("run-mc-btn").addEventListener("click", runMonteCarlo);

    // Share button
    document.getElementById("share-btn").addEventListener("click", shareConfig);

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
