initThemeToggle();

let ME = null;
let DRINKS = [];
let currentRange = 'month';
let currentScope = 'user';
let lineChart = null;
let pieChart = null;

function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
}
function chartTextColor() { return cssVar('--text-color', '#333'); }
function chartGridColor() { return cssVar('--border-color', '#ccc'); }
function chartTooltipBg() { return cssVar('--container-bg', '#fff'); }

function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

function fmtDay(isoDay) {
    if (!isoDay) return '-';
    return new Date(isoDay + 'T00:00:00Z').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Turn a raw bucket key ("2026-09-01T14:00", "2026-09-01", "2026-09") into
// a short, locale-aware label appropriate for the active range.
function formatBucketLabel(bucket, range) {
    if (range === 'day') {
        const d = new Date(bucket + ':00');
        return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    }
    if (range === 'year' || range === '2year' || range === 'all') {
        const [y, m] = bucket.split('-');
        const d = new Date(Number(y), Number(m) - 1, 1);
        return d.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
    }
    // week / month -> a day
    const d = new Date(bucket + 'T00:00:00');
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }
    // Fallback for plain-HTTP LAN access where the async Clipboard API is
    // unavailable.
    return new Promise((resolve, reject) => {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try {
            document.execCommand('copy');
            resolve();
        } catch (e) {
            reject(e);
        } finally {
            ta.remove();
        }
    });
}

async function boot() {
    ME = await requireAuth();
    document.getElementById('who').textContent = ME.name;
    const whoBig = document.getElementById('who-big');
    if (whoBig) whoBig.textContent = ME.name;

    const adminLink = document.getElementById('admin-link');
    const settingsLink = document.getElementById('settings-link');
    if (ME.role === 'admin') {
        adminLink.style.display = 'inline';
        adminLink.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.href = '/admin.html';
        });
    } else {
        settingsLink.style.display = 'inline';
        settingsLink.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.href = '/settings.html';
        });
    }
    document.getElementById('logout-link').addEventListener('click', async (e) => {
        e.preventDefault();
        await api('/api/auth/logout', { method: 'POST' });
        window.location.href = '/index.html';
    });

    DRINKS = await api('/api/drinks');
    renderTriggerButtons();
    await loadWebhookLinks();
    await refreshAll();

    document.querySelectorAll('#range-switcher button').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#range-switcher button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentRange = btn.dataset.range;
            refreshAll();
        });
    });
    document.querySelectorAll('#scope-switcher button').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#scope-switcher button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentScope = btn.dataset.scope;
            refreshAll();
        });
    });

    document.getElementById('undo-btn').addEventListener('click', prepareUndo);
    document.getElementById('export-btn').addEventListener('click', () => {
        window.location.href = `/api/export?scope=${currentScope}&range=${currentRange}`;
    });

    // Repaint charts on theme toggle so text/grid colors stay legible.
    document.getElementById('theme-toggle').addEventListener('click', () => {
        setTimeout(refreshAll, 50);
    });
}

function renderTriggerButtons() {
    const grid = document.getElementById('trigger-grid');
    grid.innerHTML = '';
    DRINKS.forEach(d => {
        const btn = document.createElement('button');
        btn.className = 'trigger-btn';
        btn.style.background = d.color;
        btn.innerHTML = `<span>${esc(d.name)}</span><span class="count" data-drink="${d.id}">&nbsp;</span>`;
        btn.addEventListener('click', () => triggerDrink(d.id, d.name));
        grid.appendChild(btn);
    });
}

async function triggerDrink(drinkTypeId, name) {
    try {
        const res = await api('/api/events', { method: 'POST', body: JSON.stringify({ drink_type_id: drinkTypeId }) });
        showToast(`${res.drink} logged (+1, ${res.count_today} today)`, 'success');
        await refreshAll();
    } catch (e) {
        showToast(`Couldn't log ${name}: ${e.message}`, 'error');
    }
}

// ---- Undo with confirmation ----
function closeUndoConfirm() {
    const el = document.getElementById('undo-confirm');
    el.style.display = 'none';
    el.innerHTML = '';
    document.getElementById('undo-btn').disabled = false;
}

async function prepareUndo() {
    try {
        const recent = await api('/api/events/recent?limit=1');
        if (recent.length === 0) {
            showToast('Nothing to undo yet', 'info');
            return;
        }
        const ev = recent[0];
        const el = document.getElementById('undo-confirm');
        el.style.display = 'flex';
        el.innerHTML = `
            <span>Remove <strong>${esc(ev.drink_name)}</strong> from ${fmtTime(ev.timestamp)}?</span>
            <div class="undo-actions">
                <button class="secondary btn-cancel" id="undo-cancel">Cancel</button>
                <button id="undo-confirm-btn">Undo</button>
            </div>`;
        document.getElementById('undo-cancel').addEventListener('click', closeUndoConfirm);
        document.getElementById('undo-confirm-btn').addEventListener('click', async () => {
            try {
                await api('/api/events/last', { method: 'DELETE' });
                showToast(`Removed ${ev.drink_name}`, 'success');
                closeUndoConfirm();
                await refreshAll();
            } catch (e) {
                showToast(e.message || 'Nothing to undo', 'error');
                closeUndoConfirm();
            }
        });
        document.getElementById('undo-btn').disabled = true;
    } catch (e) {
        showToast(e.message || 'Nothing to undo', 'info');
    }
}

async function loadWebhookLinks() {
    const container = document.getElementById('webhook-list');
    let tokens = await api('/api/webhook-tokens');

    // Auto-provision a token for each active drink type that doesn't have one yet.
    const missing = DRINKS.filter(d => !tokens.some(t => t.drink_type_id === d.id));
    for (const d of missing) {
        try {
            await api('/api/webhook-tokens', { method: 'POST', body: JSON.stringify({ user_id: ME.id, drink_type_id: d.id }) });
        } catch (e) { /* ignore */ }
    }
    if (missing.length) tokens = await api('/api/webhook-tokens');

    container.innerHTML = '';
    if (tokens.length === 0) {
        container.innerHTML = '<div class="empty-message">No webhook links yet</div>';
        return;
    }
    tokens.forEach(t => {
        const url = `${window.location.origin}/hook/${t.token}`;
        const row = document.createElement('div');
        row.className = 'webhook-link';
        row.innerHTML = `
            <span class="color-dot" style="background:${esc(t.color)}"></span>
            <span style="flex:1;">${esc(t.drink_name)}: ${esc(url)}</span>
            <button class="secondary" data-action="copy">Copy</button>
            <button class="secondary" data-action="test">Test</button>
        `;
        row.querySelector('[data-action="copy"]').addEventListener('click', () => {
            copyText(url).then(() => {
                showToast(`${t.drink_name} link copied`, 'success');
            }).catch(() => {
                showToast('Could not copy the link', 'error');
            });
        });
        row.querySelector('[data-action="test"]').addEventListener('click', async () => {
            try {
                const res = await fetch(url);
                const data = await res.json();
                showToast(`Test OK — ${data.drink}: ${data.count_today} today`, 'success');
                await refreshAll();
            } catch (e) {
                showToast('Test failed — link not working', 'error');
            }
        });
        container.appendChild(row);
    });
}

async function refreshAll() {
    const stats = await api(`/api/stats?scope=${currentScope}&range=${currentRange}`);
    renderLineChart(stats.series);
    renderPieChart(stats.pie);
    renderSummary(stats);

    if (currentScope === 'global') {
        const lb = await api(`/api/stats/leaderboard?range=${currentRange}`);
        renderLeaderboard(lb.people);
    } else {
        renderLeaderboardOff();
    }

    const recent = await api(`/api/events/recent?limit=15`);
    const body = document.getElementById('recent-body');
    body.innerHTML = '';
    if (recent.length === 0) {
        body.innerHTML = '<tr><td colspan="3" class="empty-message">No activity yet — trigger a drink above to get started</td></tr>';
    }
    recent.forEach(e => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${fmtTime(e.timestamp)}</td>
            <td><span class="color-dot" style="background:${esc(e.color)}"></span>${esc(e.drink_name)}</td>
            <td>${esc(e.source)}</td>`;
        body.appendChild(tr);
    });

    const todayCounts = await api('/api/events/today-counts');
    DRINKS.forEach(d => {
        const countEl = document.querySelector(`.count[data-drink="${d.id}"]`);
        if (countEl) countEl.textContent = `${todayCounts[d.id] || 0} today`;
    });
}

// ---- Summary chips ----
function renderSummary(stats) {
    const set = (id, v) => {
        const el = document.getElementById(id);
        if (el) el.textContent = v;
    };
    const scopeLabel = currentScope === 'global' ? 'Everyone' : 'You';

    set('stat-total', stats.total.toLocaleString());
    set('stat-total-sub', `${scopeLabel} · ${currentRange}`);

    const dot = document.getElementById('stat-top-dot');
    if (stats.top_drink) {
        set('stat-top', stats.top_drink.name);
        dot.style.display = '';
        dot.style.background = stats.top_drink.color;
        set('stat-top-sub', `${stats.top_drink.count.toLocaleString()} in period`);
    } else {
        set('stat-top', '-');
        dot.style.display = 'none';
        set('stat-top-sub', '');
    }

    if (stats.busiest_day) {
        set('stat-busiest', fmtDay(stats.busiest_day.day));
        set('stat-busiest-sub', `${stats.busiest_day.count.toLocaleString()} drinks`);
    } else {
        set('stat-busiest', '-');
        set('stat-busiest-sub', '');
    }

    if (stats.active_days) {
        set('stat-perday', Number.isInteger(stats.avg_per_day)
            ? stats.avg_per_day.toLocaleString()
            : stats.avg_per_day.toLocaleString(undefined, { maximumFractionDigits: 1 }));
        set('stat-perday-sub', `${stats.active_days} active day${stats.active_days === 1 ? '' : 's'}`);
    } else {
        set('stat-perday', '0');
        set('stat-perday-sub', 'no activity yet');
    }
}

// ---- Leaderboard ----
function renderLeaderboardOff() {
    const body = document.getElementById('leaderboard-body');
    body.innerHTML = '<div class="empty-message">Everyone view is off — switch to &ldquo;Everyone&rdquo; to compare.</div>';
}

function renderLeaderboard(people) {
    const body = document.getElementById('leaderboard-body');
    body.innerHTML = '';
    if (!people.length) {
        body.innerHTML = '<div class="empty-message">No users yet</div>';
        return;
    }
    const max = Math.max(...people.map(p => p.count), 1);
    people.forEach((p, i) => {
        const row = document.createElement('div');
        row.className = 'leaderboard-row' + (p.user_id === ME.id ? ' me' : '');
        row.innerHTML = `
            <span class="rank">${i + 1}</span>
            <span class="name">${esc(p.name)}${p.user_id === ME.id ? ' (you)' : ''}</span>
            <span class="bar-wrap"><span class="bar" style="width:${Math.round((p.count / max) * 100)}%"></span></span>
            <span class="count">${p.count}</span>`;
        body.appendChild(row);
    });
}

function showChartEmptyState(canvasId, show) {
    const canvas = document.getElementById(canvasId);
    let overlay = canvas.parentElement.querySelector('.chart-empty-overlay');
    if (show) {
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'chart-empty-overlay empty-message';
            overlay.style.position = 'absolute';
            overlay.style.inset = '0';
            overlay.style.display = 'flex';
            overlay.style.alignItems = 'center';
            overlay.style.justifyContent = 'center';
            canvas.parentElement.appendChild(overlay);
        }
        overlay.textContent = 'No data for this period yet';
        overlay.style.display = 'flex';
        canvas.style.visibility = 'hidden';
    } else {
        if (overlay) overlay.style.display = 'none';
        canvas.style.visibility = 'visible';
    }
}

function renderLineChart(series) {
    const bucketSet = new Set();
    Object.values(series).forEach(s => s.points.forEach(p => bucketSet.add(p.bucket)));
    const buckets = [...bucketSet].sort();
    const hasData = buckets.length > 0 && Object.values(series).some(s => s.points.some(p => p.count > 0));

    showChartEmptyState('line-chart', !hasData);
    if (!hasData) {
        if (lineChart) { lineChart.destroy(); lineChart = null; }
        return;
    }

    const labels = buckets.map(b => formatBucketLabel(b, currentRange));

    const datasets = Object.entries(series).map(([name, s]) => {
        const byBucket = Object.fromEntries(s.points.map(p => [p.bucket, p.count]));
        return {
            label: name,
            data: buckets.map(b => byBucket[b] || 0),
            borderColor: s.color,
            backgroundColor: s.color + '33',
            pointBackgroundColor: s.color,
            pointRadius: buckets.length > 40 ? 0 : 3,
            borderWidth: 2,
            tension: 0.3,
            fill: false,
        };
    });

    const ctx = document.getElementById('line-chart');
    if (lineChart) lineChart.destroy();
    lineChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: {
                    ticks: {
                        color: chartTextColor(),
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 8,
                    },
                    grid: { color: chartGridColor(), display: false },
                },
                y: {
                    beginAtZero: true,
                    ticks: { color: chartTextColor(), precision: 0 },
                    grid: { color: chartGridColor() },
                },
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    align: 'center',
                    labels: {
                        color: chartTextColor(),
                        usePointStyle: true,
                        pointStyle: 'circle',
                        boxWidth: 9,
                        boxHeight: 9,
                        padding: 14,
                    },
                },
                tooltip: {
                    backgroundColor: chartTooltipBg(),
                    titleColor: chartTextColor(),
                    bodyColor: chartTextColor(),
                    borderColor: chartGridColor(),
                    borderWidth: 1,
                    padding: 10,
                    boxPadding: 4,
                },
            },
        },
    });
}

function renderPieChart(pie) {
    const ctx = document.getElementById('pie-chart');
    const hasData = pie.length > 0 && pie.some(p => p.count > 0);

    showChartEmptyState('pie-chart', !hasData);
    if (pieChart) { pieChart.destroy(); pieChart = null; }
    if (!hasData) return;

    pieChart = new Chart(ctx, {
        type: 'pie',
        data: {
            labels: pie.map(p => p.name),
            datasets: [{
                data: pie.map(p => p.count),
                backgroundColor: pie.map(p => p.color),
                borderColor: chartTooltipBg(),
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { color: chartTextColor(), usePointStyle: true, boxWidth: 8 } },
                tooltip: {
                    backgroundColor: chartTooltipBg(),
                    titleColor: chartTextColor(),
                    bodyColor: chartTextColor(),
                    borderColor: chartGridColor(),
                    borderWidth: 1,
                    padding: 10,
                    callbacks: {
                        label: (item) => {
                            const total = item.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = total ? Math.round((item.parsed / total) * 100) : 0;
                            return ` ${item.label}: ${item.parsed} (${pct}%)`;
                        },
                    },
                },
            },
        },
    });
}

boot();
