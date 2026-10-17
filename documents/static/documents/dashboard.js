
"use strict";

const PAGE_SIZE = 10;

const state = {
    page: 1,
    total: 0,
    query: "",
    collection: "",
    searching: false,
};

const $ = (id) => document.getElementById(id);

async function getJson(url, allowUnavailable = false) {
    const response = await fetch(url, {
        headers: { Accept: "application/json" },
        cache: "no-store",
    });

    let data;
    try {
        data = await response.json();
    } catch {
        throw new Error(`Invalid server response (${response.status}).`);
    }

    if (!response.ok && !(allowUnavailable && response.status === 503)) {
        throw new Error(
            data.error || data.detail || data.message ||
            `Request failed (${response.status}).`
        );
    }

    return data;
}

function setText(id, value) {
    const element = $(id);
    if (element) element.textContent = String(value);
}

function setDot(id, status) {
    const element = $(id);
    if (!element) return;

    element.classList.remove("healthy", "warning", "unhealthy");
    if (status) element.classList.add(status);
}

function setChip(id, label, status) {
    const element = $(id);
    if (!element) return;

    element.textContent = label;
    element.classList.remove("healthy", "warning", "unhealthy");
    if (status) element.classList.add(status);
}

function setNotice(message, isError = false) {
    const notice = $("search-notice");
    notice.textContent = message;
    notice.classList.toggle("error", isError);
    notice.hidden = !message;
}

function formatDuration(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
        return "Not available";
    }

    const seconds = Math.max(0, Math.floor(Number(value)));
    if (seconds < 60) return `${seconds} seconds`;

    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} min`;

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} hr ${minutes % 60} min`;

    const days = Math.floor(hours / 24);
    return `${days} day${days === 1 ? "" : "s"} ${hours % 24} hr`;
}

function updateSystemStatus(ready) {
    setText("sidebar-status-title", ready ? "All systems ready" : "Service unavailable");
    setText("overall-status-text", ready
        ? "All systems operational"
        : "One or more dependencies unavailable");

    setDot("sidebar-status-dot", ready ? "healthy" : "unhealthy");
    setDot("overall-status-dot", ready ? "healthy" : "unhealthy");
}

async function refreshHealth() {
    const data = await getJson("/ready/", true);
    const checks = data.checks || {};

    const postgres = checks.postgres === true;
    const opensearch = checks.opensearch === true;
    const ready = data.status === "ok" && postgres && opensearch;

    setChip("postgres-status", postgres ? "Ready" : "Unavailable",
        postgres ? "healthy" : "unhealthy");
    setDot("postgres-dot", postgres ? "healthy" : "unhealthy");
    setText("postgres-detail", postgres
        ? "Connection check passed"
        : "Connection check failed");

    setChip("opensearch-status", opensearch ? "Ready" : "Unavailable",
        opensearch ? "healthy" : "unhealthy");
    setDot("opensearch-dot", opensearch ? "healthy" : "unhealthy");
    setText("opensearch-detail", opensearch
        ? "Connection check passed"
        : "Connection check failed");

    updateSystemStatus(ready);
    return ready;
}

function formatCount(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString() : "—";
}

function renderMetrics(data) {
    const metrics = [
        ["metric-total", data.total],
        ["metric-pending", data.pending],
        ["metric-processing", data.processing],
        ["metric-processed", data.processed],
        ["metric-failed", data.failed],
        ["metric-exhausted", data.exhausted_retries],
    ];

    for (const [id, value] of metrics) setText(id, formatCount(value));

    $("metric-failed").classList.toggle("has-issues", Number(data.failed) > 0);
    $("metric-exhausted").classList.toggle(
        "has-issues", Number(data.exhausted_retries) > 0
    );

    setText("oldest-pending-age", formatDuration(data.oldest_pending_age_seconds));

    const status = data.status || "unknown";
    const label = status === "healthy"
        ? (Number(data.pending) + Number(data.processing) > 0 ? "Active" : "Healthy")
        : status === "degraded" || status === "unhealthy"
          ? "Needs attention"
          : status === "unknown"
            ? "Unknown"
            : status.replaceAll("_", " ");

    setText("pipeline-status", label);
}

async function refreshOutbox() {
    const data = await getJson("/api/monitoring/outbox/");
    renderMetrics(data);
}

function displayValue(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);

    try {
        return JSON.stringify(value);
    } catch {
        return "";
    }
}

function makeTag(text) {
    const tag = document.createElement("span");
    tag.className = "result-tag";
    tag.textContent = text;
    return tag;
}

function renderResults(results) {
    const container = $("search-results");
    container.replaceChildren();

    if (!results.length) {
        const empty = document.createElement("div");
        empty.className = "empty-state";

        const icon = document.createElement("span");
        icon.className = "empty-icon";
        icon.textContent = "⌕";
        icon.setAttribute("aria-hidden", "true");

        const heading = document.createElement("h3");
        heading.textContent = "Nothing found this time.";

        const paragraph = document.createElement("p");
        paragraph.textContent =
            "Try a different phrase or remove the collection filter.";

        empty.append(icon, heading, paragraph);
        container.appendChild(empty);
        return;
    }

    for (const result of results) {
        const row = document.createElement("article");
        row.className = "result-row";

        const icon = document.createElement("span");
        icon.className = "result-file-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = "▤";

        const content = document.createElement("div");
        content.className = "result-content";

        const title = document.createElement("h3");
        title.className = "result-title";
        title.textContent = displayValue(result.external_id) ||
            displayValue(result.id) || "Indexed document";

        const description = document.createElement("p");
        description.className = "result-description";
        const rawData = result.data;
        const preview = displayValue(rawData);
        description.textContent = preview
            ? preview.slice(0, 400) + (preview.length > 400 ? "…" : "")
            : "No document preview available.";

        const metadata = document.createElement("div");
        metadata.className = "result-meta";

        if (result.collection_id !== undefined) {
            metadata.appendChild(makeTag(`Collection ${displayValue(result.collection_id)}`));
        }
        if (result.version !== undefined) {
            metadata.appendChild(makeTag(`Version ${displayValue(result.version)}`));
        }
        if (result.id !== undefined) {
            metadata.appendChild(makeTag(`ID ${displayValue(result.id)}`));
        }

        content.append(title, description);
        if (metadata.childElementCount) content.appendChild(metadata);
        row.append(icon, content);
        container.appendChild(row);
    }
}

function updatePagination() {
    const pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
    const start = state.total ? (state.page - 1) * PAGE_SIZE + 1 : 0;
    const end = Math.min(state.page * PAGE_SIZE, state.total);

    setText("page-description", state.total
        ? `Showing ${start}–${end} of ${state.total.toLocaleString()} documents`
        : "No results loaded");

    $("previous-page").disabled = state.searching || state.page <= 1;
    $("next-page").disabled = state.searching || state.page >= pages;
}

async function performSearch() {
    const query = $("search-query").value.trim();
    const collection = $("collection-filter").value.trim();

    if (!query) {
        setNotice("Enter a search phrase to continue.");
        $("search-query").focus();
        return;
    }

    state.query = query;
    state.collection = collection;
    state.searching = true;

    $("search-results").setAttribute("aria-busy", "true");
    $("result-count").textContent = "Searching";
    $("search-summary").textContent = `Looking for “${query}”`;
    $("search-results").replaceChildren();

    const loading = document.createElement("div");
    loading.className = "empty-state";
    const loadingTitle = document.createElement("h3");
    loadingTitle.textContent = "Finding your documents…";
    loading.appendChild(loadingTitle);
    $("search-results").appendChild(loading);

    setNotice("");
    updatePagination();

    const params = new URLSearchParams({
        q: query,
        page: String(state.page),
        page_size: String(PAGE_SIZE),
    });

    if (collection) params.set("collection", collection);

    try {
        const data = await getJson(`/api/search/?${params.toString()}`);
        const results = Array.isArray(data.results) ? data.results : [];

        state.total = Number(data.total || 0);
        state.page = Number(data.page || state.page);

        renderResults(results);
        setText("result-count",
            `${state.total.toLocaleString()} result${state.total === 1 ? "" : "s"}`);
        setText("search-summary",
            `Results for “${query}”${collection ? ` in ${collection}` : ""}`);

        if (!state.total) setNotice("No documents matched this search.");
    } catch (error) {
        state.total = 0;
        renderResults([]);

        setText("result-count", "Search unavailable");
        setText("search-summary", "We couldn't retrieve search results.");
        setNotice(error instanceof Error ? error.message : "Search failed.", true);
    } finally {
        state.searching = false;
        $("search-results").setAttribute("aria-busy", "false");
        updatePagination();
    }
}

async function refreshDashboard() {
    const button = $("refresh-button");
    button.disabled = true;
    button.classList.add("is-loading");

    const [health, outbox] = await Promise.allSettled([
        refreshHealth(),
        refreshOutbox(),
    ]);

    if (health.status === "rejected") {
        updateSystemStatus(false);
        setChip("postgres-status", "Check failed", "unhealthy");
        setChip("opensearch-status", "Check failed", "unhealthy");
        setDot("postgres-dot", "unhealthy");
        setDot("opensearch-dot", "unhealthy");
        setText("postgres-detail", "Readiness information unavailable");
        setText("opensearch-detail", "Readiness information unavailable");
    }

    if (outbox.status === "rejected") {
        setText("pipeline-status", "Unavailable");
        setText("oldest-pending-age", "Not available");

        for (const id of [
            "metric-total", "metric-pending", "metric-processing",
            "metric-processed", "metric-failed", "metric-exhausted",
        ]) setText(id, "—");
    }

    if (health.status === "rejected" || outbox.status === "rejected") {
        setText("sidebar-status-subtitle", "Unable to check all services");
    }

    setText("last-updated", `Updated ${new Intl.DateTimeFormat(undefined, {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
    }).format(new Date())}`);

    button.disabled = false;
    button.classList.remove("is-loading");
}

function setupNavigation() {
    document.querySelectorAll(".nav-links a").forEach((link) => {
        link.addEventListener("click", () => {
            document.querySelectorAll(".nav-links a").forEach((item) => {
                item.style.color = item === link ? "#0071e3" : "";
            });
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    $("search-form").addEventListener("submit", (event) => {
        event.preventDefault();
        state.page = 1;
        performSearch();

        document.getElementById("search").scrollIntoView({
            behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
                ? "auto" : "smooth",
            block: "start",
        });
    });

    $("previous-page").addEventListener("click", () => {
        if (state.page > 1 && !state.searching) {
            state.page -= 1;
            $("search-query").value = state.query;
            $("collection-filter").value = state.collection;
            performSearch();
        }
    });

    $("next-page").addEventListener("click", () => {
        if (state.page * PAGE_SIZE < state.total && !state.searching) {
            state.page += 1;
            $("search-query").value = state.query;
            $("collection-filter").value = state.collection;
            performSearch();
        }
    });

    $("refresh-button").addEventListener("click", refreshDashboard);
    setupNavigation();
    updatePagination();
    refreshDashboard();
});
