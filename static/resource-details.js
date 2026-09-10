(function () {
    'use strict';

    function makeMemorySwapSection() {
        const card = document.querySelector('[data-card-id="memory"]');
        if (!card || document.getElementById('swap-details')) return;
        const box = document.createElement('div');
        box.id = 'swap-details';
        box.className = 'resource-divider';
        box.innerHTML = `
            <div class="resource-subtitle">
                <span>Swap</span>
                <span class="swap-badge" id="swap-percent">0.0%</span>
            </div>
            <div class="swap-bar"><div class="swap-fill" id="swap-bar"></div></div>
            <div class="metrics">
                <div class="metric"><span class="metric-name">Total</span><span class="metric-val" id="swap-total">0 B</span></div>
                <div class="metric"><span class="metric-name">Used</span><span class="metric-val" id="swap-used">0 B</span></div>
                <div class="metric"><span class="metric-name">Free</span><span class="metric-val" id="swap-free">0 B</span></div>
            </div>`;
        card.appendChild(box);
    }

    function makeDiskDfSection() {
        const card = document.querySelector('[data-card-id="disk"]');
        if (!card || document.getElementById('disk-df-details')) return;
        const box = document.createElement('div');
        box.id = 'disk-df-details';
        box.className = 'df-card-wrap';
        box.innerHTML = `
            <div class="resource-subtitle"><span>df -h</span><span>mounted filesystems</span></div>
            <div class="df-scroll">
                <table class="df-mini-table">
                    <thead><tr>
                        <th>Filesystem</th><th class="right">Size</th><th class="right">Used</th>
                        <th class="right">Avail</th><th class="right">Use%</th><th>Mounted on</th>
                    </tr></thead>
                    <tbody id="disk-df-body"><tr><td colspan="6" class="loading">Loading...</td></tr></tbody>
                </table>
            </div>`;
        card.appendChild(box);
    }

    function percentClass(value) {
        return num(value) >= 90 ? 'df-use-high' : 'df-use-normal';
    }

    function dfRows(disks) {
        if (!Array.isArray(disks) || !disks.length) {
            return '<tr><td colspan="6" class="empty">Tidak ada filesystem.</td></tr>';
        }
        return disks.map(d => `
            <tr>
                <td>${esc(d.device || d.filesystem || '—')}</td>
                <td class="right">${fmtBytesDF(d.total)}</td>
                <td class="right">${fmtBytesDF(d.used)}</td>
                <td class="right">${fmtBytesDF(d.available)}</td>
                <td class="right ${percentClass(d.percent)}">${Math.round(num(d.percent))}%</td>
                <td>${esc(d.mountpoint || '—')}</td>
            </tr>`).join('');
    }

    function updateSwap(memory) {
        const swap = memory && memory.swap ? memory.swap : {};
        const pct = num(swap.percent);
        const percent = document.getElementById('swap-percent');
        const bar = document.getElementById('swap-bar');
        const total = document.getElementById('swap-total');
        const used = document.getElementById('swap-used');
        const free = document.getElementById('swap-free');
        if (percent) percent.textContent = pct.toFixed(1) + '%';
        if (bar) bar.style.width = Math.min(100, Math.max(0, pct)) + '%';
        if (total) total.textContent = fmtBytes(swap.total);
        if (used) used.textContent = fmtBytes(swap.used);
        if (free) free.textContent = fmtBytes(swap.free);
    }

    function updateDiskCard(disks) {
        const body = document.getElementById('disk-df-body');
        if (body) body.innerHTML = dfRows(disks);
    }

    function installStorageRenderer() {
        const storage = document.querySelector('#view-storage .panel table');
        if (!storage) return;
        const header = storage.querySelector('thead tr');
        if (header) {
            header.innerHTML = `
                <th>Filesystem</th><th class="right">Size</th><th class="right">Used</th>
                <th class="right">Avail</th><th class="right">Use%</th><th>Mounted on</th>`;
        }
        const desc = document.querySelector('#view-storage .section-desc');
        if (desc) desc.textContent = 'Mounted filesystems in df -h style.';

        window.renderStorage = function (disks) {
            const body = document.getElementById('storage-body');
            if (!body) return;
            body.innerHTML = dfRows(disks);
        };
    }

    makeMemorySwapSection();
    makeDiskDfSection();
    installStorageRenderer();

    if (typeof window.renderLive === 'function') {
        const coreRenderLive = window.renderLive;
        window.renderLive = function (data) {
            coreRenderLive(data);
            updateSwap(data && data.memory);
            updateDiskCard(data && data.disks);
        };
    }

    setTimeout(function () {
        try {
            if (typeof latestData !== 'undefined' && latestData) {
                updateSwap(latestData.memory);
                updateDiskCard(latestData.disks);
                if (typeof window.renderStorage === 'function') window.renderStorage(latestData.disks || []);
            }
        } catch (_) {}
    }, 0);
})();
