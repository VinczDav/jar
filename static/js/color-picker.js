/**
 * Modern Color Picker Component with Saved Colors
 * Features:
 * - Custom popup color picker (no native browser picker)
 * - Color palette with preset colors
 * - Save colors with names
 * - HSL color picker for custom colors
 */

(function() {
    'use strict';

    // Default color palette - colors where white text looks good
    const DEFAULT_COLORS = [
        // Row 1: Reds, pinks, purples
        '#D81B60', '#DD4B69', '#F012BE', '#605CA8', '#8E44AD',
        // Row 2: Blues
        '#001F3F', '#0073B7', '#3C8DBC', '#3F8FBD', '#00C0EF',
        // Row 3: Greens, teals
        '#00A65A', '#3D9970', '#01FF70', '#39CCCC', '#17A2B8',
        // Row 4: Oranges, yellows, neutrals
        '#FF851B', '#F39C12', '#E67E22', '#111111', '#6C757D'
    ];

    let savedColors = [];
    let apiEndpoints = {
        list: '/matches/api/colors/',
        save: '/matches/api/colors/save/',
        delete: '/matches/api/colors/delete/'
    };

    /**
     * Load saved colors from server
     */
    async function loadSavedColors() {
        try {
            const response = await fetch(apiEndpoints.list);
            if (response.ok) {
                savedColors = await response.json();
            }
        } catch (e) {
            console.log('Could not load saved colors');
        }
    }

    /**
     * Save a color to server
     */
    async function saveColor(name, color) {
        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                             document.cookie.split('; ').find(c => c.startsWith('csrftoken='))?.split('=')[1];

            const response = await fetch(apiEndpoints.save, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ name, color })
            });

            if (response.ok) {
                const newColor = await response.json();
                savedColors.push(newColor);
                return true;
            }
        } catch (e) {
            console.error('Could not save color', e);
        }
        return false;
    }

    /**
     * Delete a saved color
     */
    async function deleteColor(id) {
        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                             document.cookie.split('; ').find(c => c.startsWith('csrftoken='))?.split('=')[1];

            const response = await fetch(apiEndpoints.delete, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ id })
            });

            if (response.ok) {
                savedColors = savedColors.filter(c => c.id !== id);
                return true;
            }
        } catch (e) {
            console.error('Could not delete color', e);
        }
        return false;
    }

    /**
     * Create color picker popup HTML
     */
    function createColorPickerPopup() {
        const popup = document.createElement('div');
        popup.className = 'color-picker-popup';
        popup.innerHTML = `
            <div class="color-picker-header">
                <span class="color-picker-title">Szín kiválasztása</span>
                <button type="button" class="color-picker-close">&times;</button>
            </div>

            <div class="color-picker-section">
                <div class="color-picker-section-title">Előre beállított színek</div>
                <div class="color-picker-presets"></div>
            </div>

            <div class="color-picker-section color-picker-saved-section">
                <div class="color-picker-section-title">Mentett színek</div>
                <div class="color-picker-saved"></div>
            </div>

            <div class="color-picker-section">
                <div class="color-picker-section-title">Egyedi szín</div>
                <div class="color-picker-custom">
                    <div class="color-picker-hue-slider">
                        <input type="range" min="0" max="360" value="0" class="hue-input">
                    </div>
                    <div class="color-picker-saturation-lightness">
                        <canvas class="sl-canvas" width="200" height="150"></canvas>
                        <div class="sl-marker"></div>
                    </div>
                </div>
            </div>

            <div class="color-picker-preview">
                <div class="color-preview-box"></div>
                <input type="text" class="color-hex-input" maxlength="7" placeholder="#000000">
            </div>

            <div class="color-picker-actions">
                <div class="color-save-form" style="display: none;">
                    <input type="text" class="color-name-input" placeholder="Szín neve...">
                    <button type="button" class="btn-save-color">
                        <span class="material-icons">save</span>
                    </button>
                </div>
                <button type="button" class="btn-toggle-save">
                    <span class="material-icons">bookmark_add</span>
                    Mentés
                </button>
                <button type="button" class="btn-select-color">Kiválasztás</button>
            </div>
        `;
        return popup;
    }

    /**
     * HSL to Hex conversion
     */
    function hslToHex(h, s, l) {
        s /= 100;
        l /= 100;
        const a = s * Math.min(l, 1 - l);
        const f = n => {
            const k = (n + h / 30) % 12;
            const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
            return Math.round(255 * color).toString(16).padStart(2, '0');
        };
        return `#${f(0)}${f(8)}${f(4)}`;
    }

    /**
     * Hex to HSL conversion
     */
    function hexToHsl(hex) {
        let r = parseInt(hex.slice(1, 3), 16) / 255;
        let g = parseInt(hex.slice(3, 5), 16) / 255;
        let b = parseInt(hex.slice(5, 7), 16) / 255;

        let max = Math.max(r, g, b), min = Math.min(r, g, b);
        let h, s, l = (max + min) / 2;

        if (max === min) {
            h = s = 0;
        } else {
            let d = max - min;
            s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
            switch (max) {
                case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
                case g: h = ((b - r) / d + 2) / 6; break;
                case b: h = ((r - g) / d + 4) / 6; break;
            }
        }

        return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) };
    }

    /**
     * Initialize color picker on an element
     */
    function initColorPicker(input) {
        if (input.dataset.colorPickerInit) return;
        input.dataset.colorPickerInit = 'true';

        // Create wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'color-picker-wrapper-custom';
        input.parentNode.insertBefore(wrapper, input);

        // Create color button
        const colorBtn = document.createElement('button');
        colorBtn.type = 'button';
        colorBtn.className = 'color-picker-btn';
        colorBtn.innerHTML = `<span class="color-preview" style="background: ${input.value || '#6366f1'}"></span>`;

        // Create popup
        const popup = createColorPickerPopup();

        // Hide original input
        input.style.display = 'none';

        wrapper.appendChild(input);
        wrapper.appendChild(colorBtn);
        wrapper.appendChild(popup);

        // State
        let currentHue = 240;
        let currentSat = 70;
        let currentLight = 50;
        let currentColor = input.value || '#6366f1';

        // Initialize from current value
        if (currentColor) {
            const hsl = hexToHsl(currentColor);
            currentHue = hsl.h;
            currentSat = hsl.s;
            currentLight = hsl.l;
        }

        // Get elements
        const previewBox = popup.querySelector('.color-preview-box');
        const hexInput = popup.querySelector('.color-hex-input');
        const hueInput = popup.querySelector('.hue-input');
        const slCanvas = popup.querySelector('.sl-canvas');
        const slMarker = popup.querySelector('.sl-marker');
        const presetsContainer = popup.querySelector('.color-picker-presets');
        const savedContainer = popup.querySelector('.color-picker-saved');
        const saveForm = popup.querySelector('.color-save-form');
        const nameInput = popup.querySelector('.color-name-input');
        const btnToggleSave = popup.querySelector('.btn-toggle-save');
        const btnSaveColor = popup.querySelector('.btn-save-color');
        const btnSelect = popup.querySelector('.btn-select-color');
        const btnClose = popup.querySelector('.color-picker-close');

        // Update UI
        function updateUI() {
            previewBox.style.background = currentColor;
            hexInput.value = currentColor.toUpperCase();
            colorBtn.querySelector('.color-preview').style.background = currentColor;
            input.value = currentColor;
        }

        // Render presets
        function renderPresets() {
            presetsContainer.innerHTML = DEFAULT_COLORS.map(c =>
                `<button type="button" class="color-preset" style="background: ${c}" data-color="${c}"></button>`
            ).join('');

            presetsContainer.querySelectorAll('.color-preset').forEach(btn => {
                btn.addEventListener('click', () => {
                    currentColor = btn.dataset.color;
                    const hsl = hexToHsl(currentColor);
                    currentHue = hsl.h;
                    currentSat = hsl.s;
                    currentLight = hsl.l;
                    hueInput.value = currentHue;
                    drawSLCanvas();
                    updateSlMarker();
                    updateUI();
                });
            });
        }

        // Render saved colors
        function renderSavedColors() {
            if (savedColors.length === 0) {
                savedContainer.innerHTML = '<div class="no-saved-colors">Nincs mentett szín</div>';
                return;
            }

            savedContainer.innerHTML = savedColors.map(c => `
                <div class="saved-color-item" data-id="${c.id}" data-color="${c.color}">
                    <button type="button" class="color-preset" style="background: ${c.color}" data-color="${c.color}"></button>
                    <span class="saved-color-name">${c.name}</span>
                    <button type="button" class="saved-color-delete" data-id="${c.id}">
                        <span class="material-icons">close</span>
                    </button>
                </div>
            `).join('');

            savedContainer.querySelectorAll('.color-preset').forEach(btn => {
                btn.addEventListener('click', () => {
                    currentColor = btn.dataset.color;
                    const hsl = hexToHsl(currentColor);
                    currentHue = hsl.h;
                    currentSat = hsl.s;
                    currentLight = hsl.l;
                    hueInput.value = currentHue;
                    drawSLCanvas();
                    updateSlMarker();
                    updateUI();
                });
            });

            savedContainer.querySelectorAll('.saved-color-delete').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const id = parseInt(btn.dataset.id);
                    if (await deleteColor(id)) {
                        renderSavedColors();
                    }
                });
            });
        }

        // Draw saturation/lightness canvas
        function drawSLCanvas() {
            const ctx = slCanvas.getContext('2d');
            const width = slCanvas.width;
            const height = slCanvas.height;

            for (let x = 0; x < width; x++) {
                for (let y = 0; y < height; y++) {
                    const s = (x / width) * 100;
                    const l = 100 - (y / height) * 100;
                    ctx.fillStyle = hslToHex(currentHue, s, l);
                    ctx.fillRect(x, y, 1, 1);
                }
            }
        }

        // Update SL marker position
        function updateSlMarker() {
            const x = (currentSat / 100) * slCanvas.width;
            const y = ((100 - currentLight) / 100) * slCanvas.height;
            slMarker.style.left = x + 'px';
            slMarker.style.top = y + 'px';
        }

        // Handle hue change
        hueInput.addEventListener('input', () => {
            currentHue = parseInt(hueInput.value);
            drawSLCanvas();
            currentColor = hslToHex(currentHue, currentSat, currentLight);
            updateUI();
        });

        // Handle SL canvas click
        function handleSLClick(e) {
            const rect = slCanvas.getBoundingClientRect();
            const x = Math.max(0, Math.min(slCanvas.width, e.clientX - rect.left));
            const y = Math.max(0, Math.min(slCanvas.height, e.clientY - rect.top));

            currentSat = Math.round((x / slCanvas.width) * 100);
            currentLight = Math.round(100 - (y / slCanvas.height) * 100);
            currentColor = hslToHex(currentHue, currentSat, currentLight);
            updateSlMarker();
            updateUI();
        }

        slCanvas.addEventListener('click', handleSLClick);

        let isDragging = false;
        slCanvas.addEventListener('mousedown', (e) => {
            isDragging = true;
            handleSLClick(e);
        });
        document.addEventListener('mousemove', (e) => {
            if (isDragging) handleSLClick(e);
        });
        document.addEventListener('mouseup', () => isDragging = false);

        // Handle hex input
        hexInput.addEventListener('input', () => {
            let val = hexInput.value;
            if (!val.startsWith('#')) val = '#' + val;
            if (/^#[0-9A-Fa-f]{6}$/.test(val)) {
                currentColor = val.toLowerCase();
                const hsl = hexToHsl(currentColor);
                currentHue = hsl.h;
                currentSat = hsl.s;
                currentLight = hsl.l;
                hueInput.value = currentHue;
                drawSLCanvas();
                updateSlMarker();
                updateUI();
            }
        });

        // Toggle save form
        btnToggleSave.addEventListener('click', () => {
            saveForm.style.display = saveForm.style.display === 'none' ? 'flex' : 'none';
            if (saveForm.style.display !== 'none') {
                nameInput.focus();
            }
        });

        // Save color
        btnSaveColor.addEventListener('click', async () => {
            const name = nameInput.value.trim();
            if (name && currentColor) {
                if (await saveColor(name, currentColor)) {
                    nameInput.value = '';
                    saveForm.style.display = 'none';
                    renderSavedColors();
                }
            }
        });

        nameInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                btnSaveColor.click();
            }
        });

        // Select color
        btnSelect.addEventListener('click', () => {
            input.value = currentColor;
            hidePopup();
            // Trigger change event and submit if needed
            input.dispatchEvent(new Event('change', { bubbles: true }));
            // Auto-submit form if input has data-autosubmit or onchange attribute
            if (input.form && (input.dataset.autosubmit || input.hasAttribute('onchange'))) {
                input.form.submit();
            }
        });

        // Close button
        btnClose.addEventListener('click', hidePopup);

        // Show/hide popup
        function showPopup() {
            currentColor = input.value || '#6366f1';
            const hsl = hexToHsl(currentColor);
            currentHue = hsl.h;
            currentSat = hsl.s;
            currentLight = hsl.l;
            hueInput.value = currentHue;

            renderPresets();
            renderSavedColors();
            drawSLCanvas();
            updateSlMarker();
            updateUI();

            popup.classList.add('show');
        }

        function hidePopup() {
            popup.classList.remove('show');
            saveForm.style.display = 'none';
        }

        colorBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (popup.classList.contains('show')) {
                hidePopup();
            } else {
                showPopup();
            }
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!wrapper.contains(e.target)) {
                hidePopup();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                hidePopup();
            }
        });
    }

    /**
     * Add styles
     */
    function addStyles() {
        if (document.getElementById('color-picker-styles')) return;

        const style = document.createElement('style');
        style.id = 'color-picker-styles';
        style.textContent = `
            .color-picker-wrapper-custom {
                position: relative;
                display: inline-block;
            }

            .color-picker-btn {
                width: 36px;
                height: 36px;
                padding: 3px;
                border: 2px solid var(--border-color, #e2e8f0);
                border-radius: 6px;
                background: var(--card-bg, #fff);
                cursor: pointer;
                transition: all 0.2s;
            }

            .color-picker-btn:hover {
                border-color: var(--accent-color, #3b82f6);
            }

            .color-picker-btn .color-preview {
                display: block;
                width: 100%;
                height: 100%;
                border-radius: 3px;
            }

            .color-picker-popup {
                position: absolute;
                top: 100%;
                right: 0;
                z-index: 10000;
                width: 260px;
                background: var(--card-bg, #ffffff);
                border: 1px solid var(--border-color, #e2e8f0);
                border-radius: 12px;
                box-shadow: 0 8px 30px rgba(0,0,0,0.2);
                padding: 0;
                margin-top: 8px;
                display: none;
            }

            .color-picker-popup.show {
                display: block;
            }

            .color-picker-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 0.75rem 1rem;
                border-bottom: 1px solid var(--border-color, #e2e8f0);
            }

            .color-picker-title {
                font-weight: 600;
                font-size: 0.9rem;
            }

            .color-picker-close {
                background: none;
                border: none;
                font-size: 1.25rem;
                cursor: pointer;
                color: var(--text-secondary, #64748b);
                line-height: 1;
            }

            .color-picker-section {
                padding: 0.75rem 1rem;
                border-bottom: 1px solid var(--border-color, #e2e8f0);
            }

            .color-picker-section-title {
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: uppercase;
                color: var(--text-secondary, #64748b);
                margin-bottom: 0.5rem;
            }

            .color-picker-presets {
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 6px;
            }

            .color-preset {
                width: 100%;
                aspect-ratio: 1;
                border: 2px solid transparent;
                border-radius: 6px;
                cursor: pointer;
                transition: all 0.15s;
            }

            .color-preset:hover {
                transform: scale(1.1);
                border-color: var(--text-primary, #1e293b);
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            }

            .color-picker-saved {
                display: flex;
                flex-direction: column;
                gap: 4px;
                max-height: 120px;
                overflow-y: auto;
            }

            .saved-color-item {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                padding: 4px;
                border-radius: 6px;
                transition: background 0.2s;
            }

            .saved-color-item .color-preset {
                width: 28px;
                height: 28px;
                aspect-ratio: auto;
                flex-shrink: 0;
            }

            .saved-color-item:hover {
                background: var(--bg-color, #f1f5f9);
            }

            .saved-color-name {
                flex: 1;
                font-size: 0.85rem;
                color: var(--text-primary, #1e293b);
            }

            .saved-color-delete {
                background: none;
                border: none;
                cursor: pointer;
                padding: 2px;
                color: var(--text-secondary, #64748b);
                opacity: 0;
                transition: opacity 0.2s;
            }

            .saved-color-item:hover .saved-color-delete {
                opacity: 1;
            }

            .saved-color-delete:hover {
                color: var(--danger-color, #ef4444);
            }

            .saved-color-delete .material-icons {
                font-size: 1rem;
            }

            .no-saved-colors {
                font-size: 0.85rem;
                color: var(--text-secondary, #64748b);
                font-style: italic;
            }

            .color-picker-custom {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .color-picker-hue-slider {
                padding: 0.25rem 0;
            }

            .hue-input {
                width: 100%;
                height: 12px;
                -webkit-appearance: none;
                background: linear-gradient(to right,
                    hsl(0, 100%, 50%), hsl(60, 100%, 50%), hsl(120, 100%, 50%),
                    hsl(180, 100%, 50%), hsl(240, 100%, 50%), hsl(300, 100%, 50%), hsl(360, 100%, 50%));
                border-radius: 6px;
                outline: none;
            }

            .hue-input::-webkit-slider-thumb {
                -webkit-appearance: none;
                width: 16px;
                height: 16px;
                border-radius: 50%;
                background: white;
                border: 2px solid #333;
                cursor: pointer;
            }

            .color-picker-saturation-lightness {
                position: relative;
                border-radius: 8px;
                overflow: hidden;
            }

            .sl-canvas {
                width: 100%;
                height: 100px;
                cursor: crosshair;
                border-radius: 8px;
            }

            .sl-marker {
                position: absolute;
                width: 14px;
                height: 14px;
                border: 2px solid white;
                border-radius: 50%;
                box-shadow: 0 0 3px rgba(0,0,0,0.5);
                transform: translate(-50%, -50%);
                pointer-events: none;
            }

            .color-picker-preview {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                padding: 0.75rem 1rem;
                border-bottom: 1px solid var(--border-color, #e2e8f0);
            }

            .color-preview-box {
                width: 40px;
                height: 40px;
                border-radius: 8px;
                border: 1px solid var(--border-color, #e2e8f0);
            }

            .color-hex-input {
                flex: 1;
                padding: 0.5rem 0.75rem;
                border: 1px solid var(--border-color, #e2e8f0);
                border-radius: 6px;
                font-family: monospace;
                font-size: 0.9rem;
                text-transform: uppercase;
            }

            .color-hex-input:focus {
                outline: none;
                border-color: var(--accent-color, #3b82f6);
            }

            .color-picker-actions {
                display: flex;
                gap: 0.5rem;
                padding: 0.75rem 1rem;
                align-items: center;
            }

            .color-save-form {
                display: flex;
                gap: 0.25rem;
                flex: 1;
            }

            .color-name-input {
                flex: 1;
                padding: 0.4rem 0.6rem;
                border: 1px solid var(--border-color, #e2e8f0);
                border-radius: 6px;
                font-size: 0.85rem;
            }

            .btn-save-color {
                background: var(--success-color, #10b981);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0.4rem;
                cursor: pointer;
                display: flex;
                align-items: center;
            }

            .btn-save-color .material-icons {
                font-size: 1.1rem;
            }

            .btn-toggle-save {
                background: none;
                border: 1px solid var(--border-color, #e2e8f0);
                border-radius: 6px;
                padding: 0.4rem 0.6rem;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 0.25rem;
                font-size: 0.8rem;
                color: var(--text-secondary, #64748b);
            }

            .btn-toggle-save:hover {
                background: var(--bg-color, #f1f5f9);
            }

            .btn-toggle-save .material-icons {
                font-size: 1rem;
            }

            .btn-select-color {
                background: var(--accent-color, #3b82f6);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0.5rem 1rem;
                cursor: pointer;
                font-weight: 500;
                font-size: 0.85rem;
                margin-left: auto;
            }

            .btn-select-color:hover {
                background: #2563eb;
            }
        `;
        document.head.appendChild(style);
    }

    /**
     * Initialize all color inputs
     */
    async function initAll() {
        addStyles();
        await loadSavedColors();

        document.querySelectorAll('input[type="color"]').forEach(input => {
            initColorPicker(input);
        });
    }

    // Initialize
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }

    // Expose for manual use
    window.ColorPicker = {
        init: initColorPicker,
        initAll: initAll,
        loadColors: loadSavedColors
    };
})();
