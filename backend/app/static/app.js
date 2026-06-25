const TOKEN_KEY = "nkxl-token";
const USER_KEY = "nkxl-user";
const FAVORITES_KEY_PREFIX = "nkxl-favorites";
const UI_PAGE_SIZE = 10;
const FETCH_RESULT_SIZE = 20;
const HERO_ROTATE_MS = 60_000;

const STRATEGY_META = {
    personalized: {
        label: "个性引入",
        subtitle: "个性化召回 10 条与普通召回 10 条去重合并，个性化结果置前，组内按 PageRank 排序",
    },
};

const MODE_META = {
    normal: "综合搜索",
    document: "文档搜索",
    phrase: "短语查询",
    wildcard: "通配查询",
};

const state = {
    activeMode: "normal",
    activeStrategy: "personalized",
    phraseSlop: 0,
    lastResponse: null,
    lastQuery: "",
    page: 1,
    activeCorrection: null,
    suggestionTimer: null,
    suggestionRequestId: 0,
};

async function apiFetch(url, options = {}) {
    const { timeoutMs = 30000, ...fetchOptions } = options;
    const headers = new Headers(fetchOptions.headers || {});
    const token = localStorage.getItem(TOKEN_KEY);
    const hasTimeout = Number.isFinite(timeoutMs) && timeoutMs > 0;

    if (token) {
        headers.set("Authorization", `Bearer ${token}`);
    }
    if (fetchOptions.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
    }

    const controller = hasTimeout ? new AbortController() : null;
    const timeoutId = hasTimeout
        ? window.setTimeout(() => {
              controller.abort();
          }, timeoutMs)
        : null;

    try {
        const response = await fetch(url, { ...fetchOptions, headers, signal: controller?.signal });
        if (response.ok) {
            return response;
        }

        let detail = "\u8bf7\u6c42\u5931\u8d25";
        try {
            const payload = await response.json();
            if (Array.isArray(payload.detail)) {
                detail = payload.detail.map((item) => item.msg || JSON.stringify(item)).join("\uff1b");
            } else if (payload.detail && typeof payload.detail === "object") {
                detail = payload.detail.msg || JSON.stringify(payload.detail);
            } else {
                detail = payload.detail || detail;
            }
        } catch {
            const text = await response.text().catch(() => "");
            if (text) {
                detail = text;
            }
        }
        throw new Error(detail);
    } catch (error) {
        if (hasTimeout && error && error.name === "AbortError") {
            throw new Error(`\u8bf7\u6c42\u8d85\u65f6\uff08\u8d85\u8fc7 ${Math.round(timeoutMs / 1000)} \u79d2\uff09\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5`);
        }
        throw error;
    } finally {
        if (timeoutId !== null) {
            window.clearTimeout(timeoutId);
        }
    }
}

function getSearchTimeoutMs() {
    const configured = window.APP_CONFIG?.searchTimeoutMs;
    return Number.isFinite(configured) ? configured : 0;
}

function getUser() {
    try {
        const raw = localStorage.getItem(USER_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

function setUser(user) {
    if (!user) {
        localStorage.removeItem(USER_KEY);
        return;
    }
    localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function escapeHtml(value = "") {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function escapeAttr(value = "") {
    return escapeHtml(value).replaceAll("`", "&#96;");
}

function renderHighlightHtml(value = "") {
    return escapeHtml(value)
        .replaceAll("&lt;em&gt;", "<em>")
        .replaceAll("&lt;/em&gt;", "</em>");
}

function formatNumber(value) {
    return new Intl.NumberFormat("zh-CN").format(value || 0);
}

function formatDate(value) {
    if (!value) {
        return "时间未知";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return String(value).slice(0, 10);
    }
    return date.toISOString().slice(0, 10);
}

function docIconClass(docKind) {
    const normalized = String(docKind || "html").toLowerCase();
    if (["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx"].includes(normalized)) {
        return normalized;
    }
    return "html";
}

function docIconLabel(docKind) {
    const normalized = String(docKind || "html").toLowerCase();
    return normalized === "html" ? "WEB" : normalized.toUpperCase();
}

function formatUserBadgeText(user) {
    if (!user) {
        return "未登录";
    }
    const profilePart = user.college || user.major || "待完善画像";
    return `${user.username} / ${user.identity} / ${profilePart}`;
}

function bootImageCarousel({ stageId, primaryId, secondaryId, indicatorId, images = [] }) {
    const stage = document.getElementById(stageId);
    const primary = document.getElementById(primaryId);
    const secondary = document.getElementById(secondaryId);
    const indicator = document.getElementById(indicatorId);
    if (!stage || !primary || !secondary || !indicator) {
        return;
    }

    if (!images.length) {
        stage.classList.add("is-empty");
        indicator.textContent = "无可用图片";
        return;
    }

    let activeLayer = primary;
    let standbyLayer = secondary;
    let activeImageIndex = 0;

    const applyImage = (layer, imageIndex) => {
        layer.src = images[imageIndex];
        layer.alt = `南开大学校园照片 ${imageIndex + 1}`;
    };

    const updateIndicator = () => {
        indicator.textContent = `${activeImageIndex + 1} / ${images.length}`;
    };

    const preloadImage = (imageIndex) => {
        const image = new Image();
        image.src = images[imageIndex];
    };

    applyImage(activeLayer, activeImageIndex);
    activeLayer.classList.add("is-active");
    updateIndicator();

    if (images.length === 1) {
        return;
    }

    preloadImage(1);
    window.setInterval(() => {
        const nextImageIndex = (activeImageIndex + 1) % images.length;
        applyImage(standbyLayer, nextImageIndex);

        const activateNext = () => {
            activeLayer.classList.remove("is-active");
            standbyLayer.classList.add("is-active");
            [activeLayer, standbyLayer] = [standbyLayer, activeLayer];
            activeImageIndex = nextImageIndex;
            updateIndicator();
            preloadImage((activeImageIndex + 1) % images.length);
        };

        if (standbyLayer.complete) {
            activateNext();
            return;
        }

        standbyLayer.onload = () => {
            standbyLayer.onload = null;
            standbyLayer.onerror = null;
            activateNext();
        };
        standbyLayer.onerror = () => {
            standbyLayer.onload = null;
            standbyLayer.onerror = null;
            activateNext();
        };
    }, HERO_ROTATE_MS);
}

function bootHeroCarousel() {
    const heroImages = Array.isArray(window.APP_CONFIG?.heroImages)
        ? window.APP_CONFIG.heroImages.map((item) => String(item || "").trim()).filter(Boolean)
        : [];
    bootImageCarousel({
        stageId: "hero-photo-stage",
        primaryId: "hero-photo-primary",
        secondaryId: "hero-photo-secondary",
        indicatorId: "hero-photo-indicator",
        images: heroImages,
    });
}

function bootAuthCarousel() {
    const heroImages = Array.isArray(window.APP_CONFIG?.heroImages)
        ? window.APP_CONFIG.heroImages.map((item) => String(item || "").trim()).filter(Boolean)
        : [];
    bootImageCarousel({
        stageId: "auth-photo-stage",
        primaryId: "auth-photo-primary",
        secondaryId: "auth-photo-secondary",
        indicatorId: "auth-photo-indicator",
        images: heroImages,
    });
}

function setUserBadge() {
    const badge = document.getElementById("user-badge");
    if (!badge) {
        return;
    }
    badge.textContent = formatUserBadgeText(getUser());
}

function getFavoriteStorageKey() {
    const username = getUser()?.username || "guest";
    return `${FAVORITES_KEY_PREFIX}:${username}`;
}

function getFavorites() {
    try {
        const raw = localStorage.getItem(getFavoriteStorageKey());
        const items = raw ? JSON.parse(raw) : [];
        if (!Array.isArray(items)) {
            return [];
        }
        return items
            .map((item) => ({
                doc_id: String(item?.doc_id || "").trim(),
                title: String(item?.title || "").trim(),
                url: String(item?.url || "").trim(),
                saved_at: String(item?.saved_at || "").trim(),
            }))
            .filter((item) => item.doc_id && item.title && item.url);
    } catch {
        return [];
    }
}

function saveFavorites(items) {
    localStorage.setItem(getFavoriteStorageKey(), JSON.stringify(items.slice(0, 50)));
}

function isFavorite(docId) {
    return getFavorites().some((item) => item.doc_id === String(docId || ""));
}

function toggleFavoriteItem(payload) {
    const docId = String(payload?.doc_id || "").trim();
    if (!docId) {
        return false;
    }

    const favorites = getFavorites();
    const existingIndex = favorites.findIndex((item) => item.doc_id === docId);
    if (existingIndex >= 0) {
        favorites.splice(existingIndex, 1);
        saveFavorites(favorites);
        return false;
    }

    favorites.unshift({
        doc_id: docId,
        title: String(payload?.title || "").trim(),
        url: String(payload?.url || "").trim(),
        saved_at: new Date().toISOString(),
    });
    saveFavorites(favorites);
    return true;
}

function syncFavoriteButtons() {
    const favoriteIds = new Set(getFavorites().map((item) => item.doc_id));
    document.querySelectorAll("[data-favorite-doc-id]").forEach((button) => {
        const isActive = favoriteIds.has(button.dataset.favoriteDocId || "");
        button.classList.toggle("is-active", isActive);
        button.textContent = isActive ? "\u5df2\u6536\u85cf" : "\u6536\u85cf";
    });
}

function setActivityMenuOpen(open) {
    const menu = document.getElementById("activity-menu");
    const toggle = document.getElementById("activity-menu-toggle");
    if (!menu || !toggle) {
        return;
    }

    menu.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));

    if (open) {
        loadHistory().catch(() => null);
        renderFavoritesPanel();
    }
}

function setLoading(visible) {
    const loading = document.getElementById("results-loading");
    if (!loading) {
        return;
    }
    loading.classList.toggle("is-hidden", !visible);
}

function scrollResultsIntoView() {
    const board = document.getElementById("results-board");
    if (!board) {
        return;
    }
    board.scrollIntoView({ behavior: "smooth", block: "start" });
}

function updateSegmentIndicator(container) {
    if (!container) {
        return;
    }
    const indicator = container.querySelector(".segment-indicator");
    const activeButton = container.querySelector(".segment-button.is-active");
    if (!indicator || !activeButton) {
        return;
    }
    indicator.style.width = `${activeButton.offsetWidth}px`;
    indicator.style.transform = `translateX(${activeButton.offsetLeft}px)`;
}

function syncAllIndicators() {
    document.querySelectorAll(".segmented-control").forEach((container) => {
        updateSegmentIndicator(container);
    });
}

function setActiveSegment(containerId, dataKey, value) {
    const container = document.getElementById(containerId);
    if (!container) {
        return;
    }
    container.querySelectorAll(".segment-button").forEach((button) => {
        button.classList.toggle("is-active", button.dataset[dataKey] === value);
    });
    updateSegmentIndicator(container);
}

function getStrategyMeta(key) {
    return STRATEGY_META[key] || STRATEGY_META.personalized;
}

function setResultsHeaderVisible(visible) {
    const header = document.getElementById("results-header");
    if (!header) {
        return;
    }
    header.classList.toggle("is-hidden", !visible);
}

function getStrategyResult(key) {
    if (!state.lastResponse || !Array.isArray(state.lastResponse.strategies)) {
        return null;
    }
    return state.lastResponse.strategies.find((item) => item.key === key) || state.lastResponse.strategies[0] || null;
}

function renderQueryOverlay() {
    const shell = document.getElementById("query-shell");
    const overlay = document.getElementById("query-overlay");
    const input = document.getElementById("query");

    if (!shell || !overlay || !input) {
        return;
    }

    const text = input.value || "";
    if (!text) {
        overlay.innerHTML = "";
        shell.classList.remove("has-overlay", "has-correction");
        input.classList.remove("is-overlaying");
        return;
    }

    shell.classList.add("has-overlay");
    input.classList.add("is-overlaying");

    const correction = state.activeCorrection;
    if (!correction || correction.corrected_text === text) {
        shell.classList.remove("has-correction");
        overlay.innerHTML = escapeHtml(text);
        return;
    }

    const start = Math.max(0, Math.min(text.length, Number(correction.wrong_start || 0)));
    const end = Math.max(start + 1, Math.min(text.length, Number(correction.wrong_end || 0)));
    const message = correction.message || `你是否想输入“${correction.corrected_text}”？`;

    shell.classList.add("has-correction");
    overlay.innerHTML = [
        escapeHtml(text.slice(0, start)),
        `<span class="query-error-fragment" data-tooltip="${escapeAttr(message)}">${escapeHtml(text.slice(start, end))}</span>`,
        escapeHtml(text.slice(end)),
    ].join("");
}

function setActiveCorrection(correction) {
    state.activeCorrection = correction;
    renderQueryOverlay();
}

function renderSuggestions(items) {
    const panel = document.getElementById("suggestions-panel");
    if (!panel) {
        return;
    }

    if (!items.length) {
        panel.innerHTML = "";
        panel.classList.remove("is-open");
        return;
    }

    panel.innerHTML = items
        .slice(0, 8)
        .map(
            (text) => `
                <button type="button" class="suggestion-item bubble-target" data-query="${escapeAttr(text)}">
                    <span>${escapeHtml(text)}</span>
                </button>
            `,
        )
        .join("");
    panel.classList.add("is-open");
}

async function requestSuggestions(prefix, requestId) {
    const response = await apiFetch(`/api/suggestions?q=${encodeURIComponent(prefix)}`);
    const payload = await response.json();
    if (requestId !== state.suggestionRequestId) {
        return;
    }
    setActiveCorrection(payload.correction || null);
    renderSuggestions(payload.suggestions || []);
}

function scheduleSuggestions(prefix) {
    if (state.suggestionTimer) {
        window.clearTimeout(state.suggestionTimer);
    }

    state.suggestionRequestId += 1;
    const requestId = state.suggestionRequestId;

    if (!prefix) {
        setActiveCorrection(null);
    }

    renderQueryOverlay();
    state.suggestionTimer = window.setTimeout(() => {
        requestSuggestions(prefix, requestId).catch(() => {
            if (requestId === state.suggestionRequestId) {
                renderSuggestions([]);
            }
        });
    }, 120);
}

function closeSuggestions() {
    const panel = document.getElementById("suggestions-panel");
    if (!panel) {
        return;
    }
    panel.classList.remove("is-open");
}

async function loadHistory() {
    const container = document.getElementById("history-panel");
    if (!container) {
        return;
    }

    const response = await apiFetch("/api/history?limit=50");
    const items = await response.json();

    if (!items.length) {
        container.innerHTML = localStorage.getItem(TOKEN_KEY)
            ? '<p class="empty-copy">\u6682\u65e0\u67e5\u8be2\u5386\u53f2\u3002</p>'
            : '<p class="empty-copy">\u767b\u5f55\u540e\u4f1a\u663e\u793a\u6700\u8fd1 50 \u6761\u67e5\u8be2\u5386\u53f2\u3002</p>';
        return;
    }

    container.innerHTML = items
        .map(
            (item) => `
                <button type="button" class="history-item bubble-target" data-query="${escapeAttr(item)}">
                    ${escapeHtml(item)}
                </button>
            `,
        )
        .join("");
}

function renderFavoritesPanel() {
    const container = document.getElementById("favorites-panel");
    if (!container) {
        return;
    }

    const favorites = getFavorites();
    if (!favorites.length) {
        container.innerHTML = '<p class="empty-copy">\u6682\u65e0\u6536\u85cf\u5185\u5bb9\u3002</p>';
        syncFavoriteButtons();
        return;
    }

    container.innerHTML = favorites
        .map(
            (item) => `
                <article class="favorite-item">
                    <a href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer" class="favorite-link">
                        ${escapeHtml(item.title)}
                    </a>
                    <button
                        type="button"
                        class="favorite-remove bubble-target"
                        data-remove-favorite-doc-id="${escapeAttr(item.doc_id)}"
                    >
                        \u79fb\u9664
                    </button>
                </article>
            `,
        )
        .join("");
    syncFavoriteButtons();
}

async function loadRecommendations() {
    const container = document.getElementById("recommendations");
    const tagContainer = document.getElementById("recommendation-tags");
    if (!container) {
        return;
    }

    if (!localStorage.getItem(TOKEN_KEY)) {
        if (tagContainer) {
            tagContainer.innerHTML = '<p class="empty-copy">登录后会显示当前用于推荐的画像标签。</p>';
        }
        container.innerHTML = '<p class="empty-copy">登录后可基于行为画像标签生成推荐内容。</p>';
        return;
    }

    try {
        const response = await apiFetch("/api/recommendations");
        const payload = await response.json();

        if (tagContainer) {
            const tags = Array.isArray(payload.profile_tags) ? payload.profile_tags : [];
            if (!tags.length) {
                tagContainer.innerHTML = '<p class="empty-copy">当前画像标签为空，推荐将退化为默认校园热点内容。</p>';
            } else {
                tagContainer.innerHTML = tags
                    .slice(0, 10)
                    .map((tag) => `<span class="recommendation-tag">${escapeHtml(tag)}</span>`)
                    .join("");
            }
        }

        if (!payload.items.length) {
            container.innerHTML = '<p class="empty-copy">暂时没有可展示的推荐结果。</p>';
            return;
        }

        container.innerHTML = payload.items
            .map(
                (item) => `
                    <article class="recommendation-card">
                        <strong><a href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a></strong>
                    </article>
                `,
            )
            .join("");
    } catch (error) {
        if (tagContainer) {
            tagContainer.innerHTML = '<p class="empty-copy">画像标签加载失败。</p>';
        }
        container.innerHTML = `<p class="empty-copy">${escapeHtml(error.message || "加载推荐失败")}</p>`;
    }
}

function renderStrategyLegend(activeResult) {
    const container = document.getElementById("strategy-legend");
    if (!container || !state.lastResponse || !activeResult) {
        return;
    }

    const meta = getStrategyMeta(activeResult.key);
    const chips = [
        `<span class="legend-chip">模式：${escapeHtml(MODE_META[state.activeMode] || MODE_META.normal)}</span>`,
        `<span class="legend-chip">策略：${escapeHtml(meta.label)}</span>`,
        `<span class="legend-chip">耗时：${escapeHtml(String(state.lastResponse.took_ms || 0))} ms</span>`,
    ];

    if (!state.lastResponse.personalization_enabled) {
        chips.push('<span class="legend-chip">当前未启用个性化扩展</span>');
    }

    container.innerHTML = chips.join("");
}

function renderCompareNote(activeResult) {
    const note = document.getElementById("compare-note");
    if (!note || !state.lastResponse || !activeResult) {
        return;
    }

    const meta = getStrategyMeta(activeResult.key);
    let text = meta.subtitle;

    if (state.lastResponse.corrected_query) {
        text += `。本次查询已自动采用纠错结果“${state.lastResponse.corrected_query}”。`;
    }

    if (activeResult.key === "personalized" && !state.lastResponse.personalization_enabled) {
        text += "。当前未生成可用的个性化扩展，因此该视图退化为普通搜索结果。";
    }

    note.textContent = text;
}

function renderIdleState(messageText = "") {
    const results = document.getElementById("results");
    const title = document.getElementById("results-summary-title");
    const pagination = document.getElementById("pagination");

    if (title) {
        title.textContent = "";
    }
    setResultsHeaderVisible(false);
    if (results) {
        results.innerHTML = messageText ? `<p class="empty-search-state">${escapeHtml(messageText)}</p>` : "";
    }
    if (pagination) {
        pagination.innerHTML = "";
    }
}

function renderResultCard(hit, rank) {
    const docKind = String(hit.file_extension || hit.doc_kind || "html");
    const sourceName = Array.isArray(hit.departments) && hit.departments.length
        ? hit.departments[0]
        : hit.site_name;
    const favoriteActive = isFavorite(hit.doc_id);

    return `
        <article class="result-card bubble-target">
            <div class="result-icon ${docIconClass(docKind)}">${docIconLabel(docKind)}</div>
            <div class="result-body">
                <a
                    href="${escapeAttr(hit.url)}"
                    class="result-title"
                    target="_blank"
                    rel="noreferrer"
                    data-doc-id="${escapeAttr(hit.doc_id)}"
                    data-query="${escapeAttr(state.lastQuery)}"
                >
                    ${rank}. ${escapeHtml(hit.title)}
                </a>
                <p class="result-snippet">${renderHighlightHtml(hit.snippet || "")}</p>
                <div class="meta-row">
                    <span class="meta-chip">${escapeHtml(sourceName || "未知来源")}</span>
                    <span class="meta-chip">${escapeHtml(docKind.toUpperCase())}</span>
                </div>
                <div class="result-actions">
                    <a href="${escapeAttr(hit.url)}" target="_blank" rel="noreferrer" class="result-action bubble-target">原网页</a>
                    <a href="${escapeAttr(hit.snapshot_url)}" target="_blank" rel="noreferrer" class="result-action bubble-target">网页快照</a>
                    <button
                        type="button"
                        class="result-action result-action-favorite bubble-target ${favoriteActive ? "is-active" : ""}"
                        data-favorite-doc-id="${escapeAttr(hit.doc_id)}"
                        data-favorite-title="${escapeAttr(hit.title)}"
                        data-favorite-url="${escapeAttr(hit.url)}"
                    >
                        ${favoriteActive ? "\u5df2\u6536\u85cf" : "\u6536\u85cf"}
                    </button>
                </div>
            </div>
        </article>
    `;
}

function renderResults() {
    if (!state.lastResponse) {
        renderIdleState();
        return;
    }

    const results = document.getElementById("results");
    const title = document.getElementById("results-summary-title");
    if (!results || !title) {
        return;
    }

    const activeResult = getStrategyResult(state.activeStrategy);
    if (!activeResult) {
        renderIdleState("当前查询未返回任何可用结果。");
        return;
    }

    setResultsHeaderVisible(true);
    title.textContent = `返回 ${formatNumber(state.lastResponse.total)} 条结果`;

    results.classList.add("is-swapping");
    window.setTimeout(() => results.classList.remove("is-swapping"), 280);

    const offset = (Math.max(1, Number(state.page || 1)) - 1) * UI_PAGE_SIZE;
    const limit = offset + UI_PAGE_SIZE;
    const visibleHits = activeResult.hits.slice(offset, limit);

    if (!visibleHits.length) {
        results.innerHTML = '<p class="empty-search-state">当前页没有可展示的结果。</p>';
        return;
    }

    const startRank = offset;
    results.innerHTML = visibleHits
        .map((hit, index) => renderResultCard(hit, startRank + index + 1))
        .join("");
}

function renderPagination() {
    const container = document.getElementById("pagination");
    if (!container || !state.lastResponse) {
        return;
    }

    const total = Number(state.lastResponse.total || 0);
    const size = UI_PAGE_SIZE;
    const current = Math.max(1, Number(state.page || 1));
    const totalPages = Math.max(1, Math.ceil(total / size));

    if (totalPages <= 1) {
        container.innerHTML = "";
        return;
    }

    const pageNumbers = [];
    for (let page = Math.max(1, current - 2); page <= Math.min(totalPages, current + 2); page += 1) {
        pageNumbers.push(page);
    }

    container.innerHTML = `
        <button type="button" class="page-button bubble-target" ${current === 1 ? "disabled" : ""} data-page="${current - 1}">
            上一页
        </button>
        ${pageNumbers
            .map(
                (page) => `
                    <button
                        type="button"
                        class="page-chip bubble-target ${page === current ? "is-active" : ""}"
                        data-page="${page}"
                    >
                        ${page}
                    </button>
                `,
            )
            .join("")}
        <button type="button" class="page-button bubble-target" ${current === totalPages ? "disabled" : ""} data-page="${current + 1}">
            下一页
        </button>
    `;
}

async function performSearch(page = 1) {
    const queryInput = document.getElementById("query");
    if (!queryInput) {
        return;
    }

    const query = queryInput.value.trim();
    if (!query) {
        renderIdleState();
        return;
    }

    state.lastQuery = query;
    state.page = page;
    closeSuggestions();
    setLoading(true);

    const params = new URLSearchParams({
        q: query,
        mode: state.activeMode,
        page: "1",
        size: String(FETCH_RESULT_SIZE),
        slop: state.activeMode === "phrase" ? String(getPhraseSlopValue()) : "0",
    });

    try {
        const response = await apiFetch(`/api/search?${params.toString()}`, {
            timeoutMs: getSearchTimeoutMs(),
        });
        state.lastResponse = await response.json();
        renderResults();
        renderPagination();
        scrollResultsIntoView();
        await loadHistory();
    } finally {
        setLoading(false);
    }
}

function syncStrategySelect() {
    const sortSelect = document.getElementById("filter-sort-kind");
    if (!sortSelect) {
        return;
    }
    sortSelect.value = state.activeStrategy;
}

function getPhraseSlopValue() {
    return Math.min(5, Math.max(0, Number(state.phraseSlop || 0)));
}

function setPhraseSlop(value) {
    const parsed = Math.min(5, Math.max(0, Number(value || 0)));
    state.phraseSlop = Number.isInteger(parsed) ? parsed : 0;
    setActiveSegment("phrase-slop-switch", "phraseSlop", String(state.phraseSlop));
}

function syncPhraseSlopControl() {
    const tools = document.querySelector(".query-tools");
    const control = document.getElementById("phrase-slop-control");
    const isPhraseMode = state.activeMode === "phrase";

    if (tools) {
        tools.classList.toggle("is-inactive", !isPhraseMode);
    }
    if (control) {
        control.classList.toggle("is-inactive", !isPhraseMode);
        control.setAttribute("aria-disabled", String(!isPhraseMode));
    }
    window.requestAnimationFrame(syncAllIndicators);
}

function setStrategy(strategyKey) {
    state.activeStrategy = strategyKey;
    setActiveSegment("compare-switch", "strategy", strategyKey);
    syncStrategySelect();
    if (state.lastResponse) {
        renderResults();
        renderPagination();
    }
}

function setMode(modeKey) {
    state.activeMode = modeKey;
    setActiveSegment("mode-switch", "mode", modeKey);
    syncPhraseSlopControl();
}

function getSelectedInterestTags(scope = document) {
    return Array.from(scope.querySelectorAll("[data-interest-tag].is-selected"))
        .map((button) => button.dataset.interestTag || "")
        .filter(Boolean);
}

function collectProfilePayload(prefix, scope = document) {
    return {
        identity: scope.querySelector(`#${prefix}identity`)?.value || "本科生",
        college: scope.querySelector(`#${prefix}college`)?.value || "",
        major: scope.querySelector(`#${prefix}major`)?.value.trim() || "",
        interest_tags: getSelectedInterestTags(scope),
        search_need_text: scope.querySelector(`#${prefix}search-need-text`)?.value.trim() || "",
    };
}

async function submitAuth(action, username, password, statusNode, extraPayload = null) {
    if (!username || !password) {
        if (statusNode) {
            statusNode.textContent = "请先填写用户名和密码。";
        }
        return;
    }

    const response = await apiFetch(`/api/auth/${action}`, {
        method: "POST",
        body: JSON.stringify({
            username,
            password,
            ...(extraPayload || {}),
        }),
    });
    const result = await response.json();

    localStorage.setItem(TOKEN_KEY, result.access_token);
    setUser(result.user);

    if (statusNode) {
        statusNode.textContent = action === "login" ? "登录成功，正在跳转…" : "注册成功，正在跳转…";
    }

    window.setTimeout(() => {
        if (result.needs_profile_setup) {
            window.location.href = "/profile-setup";
            return;
        }
        window.location.href = "/";
    }, 900);
}

async function loadProfileSetup() {
    const response = await apiFetch("/api/auth/profile");
    const user = await response.json();
    setUser(user);

    const identity = document.getElementById("profile-identity");
    const college = document.getElementById("profile-college");
    const major = document.getElementById("profile-major");
    const searchNeed = document.getElementById("profile-search-need-text");

    if (identity) {
        identity.value = user.identity || "本科生";
    }
    if (college) {
        college.value = user.college || "";
    }
    if (major) {
        major.value = user.major || "";
    }
    if (searchNeed) {
        searchNeed.value = user.search_need_text || "";
    }

    const selectedTags = new Set(user.interest_tags || []);
    document.querySelectorAll("[data-interest-tag]").forEach((button) => {
        button.classList.toggle("is-selected", selectedTags.has(button.dataset.interestTag));
    });
}

async function submitProfileSetup() {
    const statusNode = document.getElementById("profile-status");
    const payload = collectProfilePayload("profile-");

    const response = await apiFetch("/api/auth/profile", {
        method: "PUT",
        body: JSON.stringify(payload),
    });
    const user = await response.json();
    setUser(user);

    if (statusNode) {
        statusNode.textContent = "画像已保存，正在返回搜索首页…";
    }

    window.setTimeout(() => {
        window.location.href = "/";
    }, 900);
}

function bindBubbleInteractions() {
    document.addEventListener("pointerdown", (event) => {
        const target = event.target.closest(
            ".bubble-target, .segment-button, .result-card, .suggestion-item, .result-action, .page-button, .page-chip, .tag-toggle",
        );
        if (!target) {
            return;
        }

        const rect = target.getBoundingClientRect();
        const ripple = document.createElement("span");
        ripple.className = "bubble-ripple";

        const size = Math.max(rect.width, rect.height) * 1.15;
        ripple.style.width = `${size}px`;
        ripple.style.height = `${size}px`;
        ripple.style.left = `${event.clientX - rect.left}px`;
        ripple.style.top = `${event.clientY - rect.top}px`;

        target.appendChild(ripple);
        window.setTimeout(() => ripple.remove(), 650);
    });
}

function bindDelegatedClicks() {
    document.addEventListener("click", (event) => {
        const strategyButton = event.target.closest("[data-strategy]");
        if (strategyButton) {
            setStrategy(strategyButton.dataset.strategy);
            return;
        }

        const modeButton = event.target.closest("#mode-switch [data-mode]");
        if (modeButton) {
            setMode(modeButton.dataset.mode);
            return;
        }

        const phraseSlopButton = event.target.closest("#phrase-slop-switch [data-phrase-slop]");
        if (phraseSlopButton) {
            setPhraseSlop(phraseSlopButton.dataset.phraseSlop);
            return;
        }

        const queryButton = event.target.closest("[data-query]");
        if (queryButton) {
            const queryInput = document.getElementById("query");
            if (!queryInput) {
                return;
            }

            queryInput.value = queryButton.dataset.query || "";
            setActiveCorrection(null);
            renderQueryOverlay();
            closeSuggestions();
            setActivityMenuOpen(false);
            performSearch(1).catch(showSearchError);
            return;
        }

        const activityToggle = event.target.closest("#activity-menu-toggle");
        if (activityToggle) {
            const menu = document.getElementById("activity-menu");
            setActivityMenuOpen(!menu?.classList.contains("is-open"));
            return;
        }

        const pageButton = event.target.closest("[data-page]");
        if (pageButton) {
            const page = Number(pageButton.dataset.page || "1");
            if (!Number.isNaN(page) && page > 0) {
                state.page = page;
                renderResults();
                renderPagination();
                scrollResultsIntoView();
            }
            return;
        }

        const docLink = event.target.closest("[data-doc-id]");
        if (docLink) {
            apiFetch("/api/click", {
                method: "POST",
                body: JSON.stringify({
                    doc_id: docLink.dataset.docId,
                    query_text: docLink.dataset.query || state.lastQuery,
                }),
            }).catch(() => null);
            return;
        }

        const tagButton = event.target.closest("[data-interest-tag]");
        if (tagButton) {
            tagButton.classList.toggle("is-selected");
            return;
        }

        const favoriteButton = event.target.closest("[data-favorite-doc-id]");
        if (favoriteButton) {
            toggleFavoriteItem({
                doc_id: favoriteButton.dataset.favoriteDocId,
                title: favoriteButton.dataset.favoriteTitle,
                url: favoriteButton.dataset.favoriteUrl,
            });
            renderFavoritesPanel();
            syncFavoriteButtons();
            return;
        }

        const removeFavoriteButton = event.target.closest("[data-remove-favorite-doc-id]");
        if (removeFavoriteButton) {
            toggleFavoriteItem({
                doc_id: removeFavoriteButton.dataset.removeFavoriteDocId,
            });
            renderFavoritesPanel();
            syncFavoriteButtons();
            return;
        }

        if (!event.target.closest(".search-input-shell")) {
            closeSuggestions();
        }
        if (!event.target.closest(".activity-menu")) {
            setActivityMenuOpen(false);
        }
    });
}

function showSearchError(error) {
    setLoading(false);
    renderIdleState(error.message || "请求失败");
}

function setAuthTab(tabKey) {
    const switcher = document.getElementById("auth-mode-switch");
    if (!switcher) {
        return;
    }

    switcher.querySelectorAll("[data-auth-tab]").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.authTab === tabKey);
    });

    document.querySelectorAll(".auth-view").forEach((panel) => {
        panel.classList.toggle("is-active", panel.id === `auth-view-${tabKey}`);
    });

    updateSegmentIndicator(switcher);
}

function bootSearchPage() {
    const form = document.getElementById("search-form");
    if (!form) {
        return;
    }

    setUserBadge();
    syncStrategySelect();
    setPhraseSlop(state.phraseSlop);
    syncPhraseSlopControl();
    renderFavoritesPanel();
    syncFavoriteButtons();
    renderIdleState();

    window.requestAnimationFrame(syncAllIndicators);
    window.setTimeout(syncAllIndicators, 80);
    window.addEventListener("resize", syncAllIndicators);

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        performSearch(1).catch(showSearchError);
    });

    const queryInput = document.getElementById("query");
    if (queryInput) {
        queryInput.addEventListener("input", (event) => {
            setActiveCorrection(null);
            renderQueryOverlay();
            scheduleSuggestions(event.target.value.trim());
        });

        queryInput.addEventListener("focus", () => {
            renderQueryOverlay();
            scheduleSuggestions(queryInput.value.trim());
        });

        queryInput.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeSuggestions();
            }
        });

        queryInput.addEventListener("blur", () => {
            window.setTimeout(closeSuggestions, 180);
        });
    }

    const sortSelect = document.getElementById("filter-sort-kind");
    if (sortSelect) {
        sortSelect.addEventListener("change", (event) => {
            setStrategy(event.target.value);
        });
    }

    const recommendationsButton = document.getElementById("load-recommendations");
    if (recommendationsButton) {
        recommendationsButton.addEventListener("click", () => {
            loadRecommendations().catch(() => null);
        });
    }

    loadHistory().catch(() => null);
    if (localStorage.getItem(TOKEN_KEY)) {
        loadRecommendations().catch(() => null);
    }
}

function bootLoginPage() {
    const loginForm = document.getElementById("login-form");
    const registerForm = document.getElementById("register-form");
    if (!loginForm || !registerForm) {
        return;
    }

    setAuthTab("login");
    window.requestAnimationFrame(() => updateSegmentIndicator(document.getElementById("auth-mode-switch")));

    document.querySelectorAll("[data-auth-tab]").forEach((button) => {
        button.addEventListener("click", () => {
            const tabKey = button.dataset.authTab;
            if (!tabKey) {
                return;
            }
            setAuthTab(tabKey);
        });
    });

    loginForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const statusNode = document.getElementById("login-status");
        const username = document.getElementById("login-username")?.value.trim() || "";
        const password = document.getElementById("login-password")?.value.trim() || "";
        submitAuth("login", username, password, statusNode).catch((error) => {
            if (statusNode) {
                statusNode.textContent = error.message || "请求失败";
            }

            if ((error.message || "").includes("账号不存在")) {
                const registerUsername = document.getElementById("register-username");
                if (registerUsername && username) {
                    registerUsername.value = username;
                }
                setAuthTab("register");
            }
        });
    });

    registerForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const statusNode = document.getElementById("register-status");
        const username = document.getElementById("register-username")?.value.trim() || "";
        const password = document.getElementById("register-password")?.value.trim() || "";
        const profilePayload = collectProfilePayload("register-", registerForm);

        submitAuth("register", username, password, statusNode, profilePayload).catch((error) => {
            if (statusNode) {
                statusNode.textContent = error.message || "请求失败";
            }
        });
    });
}

function bootProfileSetupPage() {
    const profileForm = document.getElementById("profile-form");
    if (!profileForm) {
        return;
    }

    if (!localStorage.getItem(TOKEN_KEY)) {
        window.location.href = "/login";
        return;
    }

    profileForm.addEventListener("submit", (event) => {
        event.preventDefault();
        submitProfileSetup().catch((error) => {
            const statusNode = document.getElementById("profile-status");
            if (statusNode) {
                statusNode.textContent = error.message || "请求失败";
            }
        });
    });

    loadProfileSetup().catch((error) => {
        const statusNode = document.getElementById("profile-status");
        if (statusNode) {
            statusNode.textContent = error.message || "画像加载失败";
        }
    });
}

function init() {
    bindBubbleInteractions();
    bindDelegatedClicks();
    bootHeroCarousel();
    bootAuthCarousel();
    bootSearchPage();
    bootLoginPage();
    bootProfileSetupPage();
    setUserBadge();
}

document.addEventListener("DOMContentLoaded", init);
