/**
 * Custom Date/Time Input Components with Calendar Picker
 * Date format: YYYY.MM.DD (typing: 20250121 -> 2025.01.21)
 * Time format: HH:MM (typing: 1830 -> 18:30)
 */

(function() {
    'use strict';

    // Hungarian day and month names (Monday first)
    const DAYS_SHORT = ['H', 'K', 'Sze', 'Cs', 'P', 'Szo', 'V'];
    const MONTHS = ['Január', 'Február', 'Március', 'Április', 'Május', 'Június',
                    'Július', 'Augusztus', 'Szeptember', 'Október', 'November', 'December'];

    /**
     * Create calendar popup HTML
     */
    function createCalendarPopup() {
        const popup = document.createElement('div');
        popup.className = 'calendar-popup';
        popup.innerHTML = `
            <div class="calendar-header">
                <button type="button" class="calendar-nav calendar-prev">&lt;</button>
                <span class="calendar-title"></span>
                <button type="button" class="calendar-nav calendar-next">&gt;</button>
            </div>
            <div class="calendar-weekdays">
                ${DAYS_SHORT.map(d => `<span>${d}</span>`).join('')}
            </div>
            <div class="calendar-days"></div>
        `;
        return popup;
    }

    /**
     * Render calendar days for a given month/year
     */
    function renderCalendar(popup, year, month, selectedDate, onSelect) {
        const titleEl = popup.querySelector('.calendar-title');
        const daysEl = popup.querySelector('.calendar-days');

        titleEl.textContent = `${MONTHS[month]} ${year}`;

        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        // Convert Sunday=0 to Monday-first (Mon=0, Sun=6)
        let startDay = firstDay.getDay() - 1;
        if (startDay < 0) startDay = 6;
        const daysInMonth = lastDay.getDate();

        // Get days from previous month
        const prevMonth = new Date(year, month, 0);
        const daysInPrevMonth = prevMonth.getDate();

        let html = '';

        // Previous month days
        for (let i = startDay - 1; i >= 0; i--) {
            const day = daysInPrevMonth - i;
            html += `<span class="calendar-day other-month" data-date="${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}">${day}</span>`;
        }

        // Current month days
        const today = new Date();
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${year}-${String(month + 1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
            const isToday = today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;
            const isSelected = selectedDate === dateStr;
            let classes = 'calendar-day';
            if (isToday) classes += ' today';
            if (isSelected) classes += ' selected';
            html += `<span class="${classes}" data-date="${dateStr}">${day}</span>`;
        }

        // Next month days
        const totalCells = Math.ceil((startDay + daysInMonth) / 7) * 7;
        const remaining = totalCells - (startDay + daysInMonth);
        for (let day = 1; day <= remaining; day++) {
            html += `<span class="calendar-day other-month">${day}</span>`;
        }

        daysEl.innerHTML = html;

        // Add click handlers
        daysEl.querySelectorAll('.calendar-day:not(.other-month)').forEach(el => {
            el.addEventListener('click', () => {
                onSelect(el.dataset.date);
            });
        });
    }

    /**
     * Initialize date input with auto-formatting and calendar picker
     */
    function initDateInput(input) {
        if (input.dataset.initialized) return;

        // Create wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'date-input-wrapper';
        input.parentNode.insertBefore(wrapper, input);

        // Store original value
        let currentValue = input.value || '';

        // Create visible text input
        const textInput = document.createElement('input');
        textInput.type = 'text';
        textInput.className = input.className;
        textInput.placeholder = 'YYYY.MM.DD';
        textInput.maxLength = 10;

        // Copy attributes
        if (input.required) textInput.required = true;
        if (input.disabled) textInput.disabled = true;
        if (input.readOnly) textInput.readOnly = true;

        // Set initial formatted value
        if (currentValue) {
            textInput.value = formatDateDisplay(currentValue);
        }

        // Create calendar button
        const calendarBtn = document.createElement('button');
        calendarBtn.type = 'button';
        calendarBtn.className = 'calendar-btn';
        calendarBtn.innerHTML = '<span class="material-icons">calendar_today</span>';
        calendarBtn.tabIndex = -1;

        // Create calendar popup
        const popup = createCalendarPopup();

        // Hide original input
        input.style.display = 'none';
        input.dataset.initialized = 'true';

        // Assemble
        wrapper.appendChild(input);
        wrapper.appendChild(textInput);
        wrapper.appendChild(calendarBtn);
        wrapper.appendChild(popup);

        // Calendar state
        let currentYear = new Date().getFullYear();
        let currentMonth = new Date().getMonth();

        // Update hidden input
        function updateHiddenInput(value) {
            const digits = value.replace(/\D/g, '');
            if (digits.length === 8) {
                const year = digits.substring(0, 4);
                const month = digits.substring(4, 6);
                const day = digits.substring(6, 8);
                input.value = `${year}-${month}-${day}`;
            } else {
                input.value = '';
            }
        }

        // Handle text input
        textInput.addEventListener('input', function(e) {
            let value = this.value.replace(/\D/g, '');

            if (value.length >= 4) {
                value = value.substring(0, 4) + '.' + value.substring(4);
            }
            if (value.length >= 7) {
                value = value.substring(0, 7) + '.' + value.substring(7);
            }
            if (value.length > 10) {
                value = value.substring(0, 10);
            }

            this.value = value;
            updateHiddenInput(value);
        });

        // Handle backspace to skip over dots
        textInput.addEventListener('keydown', function(e) {
            if (e.key === 'Backspace') {
                const pos = this.selectionStart;
                // If cursor is right after a dot, delete the character before the dot too
                if (pos > 0 && this.value[pos - 1] === '.') {
                    e.preventDefault();
                    const before = this.value.substring(0, pos - 2);
                    const after = this.value.substring(pos);
                    this.value = before + after;
                    // Reformat
                    let digits = this.value.replace(/\D/g, '');
                    let formatted = digits;
                    if (digits.length >= 4) {
                        formatted = digits.substring(0, 4) + '.' + digits.substring(4);
                    }
                    if (digits.length >= 6) {
                        formatted = formatted.substring(0, 7) + '.' + digits.substring(6);
                    }
                    this.value = formatted;
                    updateHiddenInput(formatted);
                    // Set cursor position
                    const newPos = Math.max(0, pos - 2);
                    this.setSelectionRange(newPos, newPos);
                }
            }
        });

        // Handle paste
        textInput.addEventListener('paste', function(e) {
            e.preventDefault();
            const pastedText = (e.clipboardData || window.clipboardData).getData('text');
            const digits = pastedText.replace(/\D/g, '');

            this.value = '';
            for (let i = 0; i < Math.min(digits.length, 8); i++) {
                this.value += digits[i];
                if (this.value.replace(/\D/g, '').length === 4 || this.value.replace(/\D/g, '').length === 6) {
                    this.value += '.';
                }
            }
            updateHiddenInput(this.value);
        });

        // Show/hide calendar
        function showCalendar() {
            // Parse current value to set calendar position
            if (input.value) {
                const parts = input.value.split('-');
                if (parts.length === 3) {
                    currentYear = parseInt(parts[0]);
                    currentMonth = parseInt(parts[1]) - 1;
                }
            }

            renderCalendar(popup, currentYear, currentMonth, input.value, (dateStr) => {
                input.value = dateStr;
                textInput.value = formatDateDisplay(dateStr);
                hideCalendar();
            });

            popup.classList.add('show');
        }

        function hideCalendar() {
            popup.classList.remove('show');
        }

        // Calendar button click
        calendarBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (popup.classList.contains('show')) {
                hideCalendar();
            } else {
                showCalendar();
            }
        });

        // Navigation
        popup.querySelector('.calendar-prev').addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            currentMonth--;
            if (currentMonth < 0) {
                currentMonth = 11;
                currentYear--;
            }
            renderCalendar(popup, currentYear, currentMonth, input.value, (dateStr) => {
                input.value = dateStr;
                textInput.value = formatDateDisplay(dateStr);
                hideCalendar();
            });
        });

        popup.querySelector('.calendar-next').addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            currentMonth++;
            if (currentMonth > 11) {
                currentMonth = 0;
                currentYear++;
            }
            renderCalendar(popup, currentYear, currentMonth, input.value, (dateStr) => {
                input.value = dateStr;
                textInput.value = formatDateDisplay(dateStr);
                hideCalendar();
            });
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!wrapper.contains(e.target)) {
                hideCalendar();
            }
        });

        // Close on escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                hideCalendar();
            }
        });
    }

    /**
     * Format date from YYYY-MM-DD to YYYY.MM.DD for display
     */
    function formatDateDisplay(isoDate) {
        if (!isoDate) return '';
        const digits = isoDate.replace(/\D/g, '');
        if (digits.length === 8) {
            return digits.substring(0, 4) + '.' + digits.substring(4, 6) + '.' + digits.substring(6, 8);
        }
        return isoDate;
    }

    /**
     * Initialize time input with auto-formatting
     */
    function initTimeInput(input) {
        if (input.dataset.initialized) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'time-input-wrapper';
        input.parentNode.insertBefore(wrapper, input);

        let currentValue = input.value || '';

        const textInput = document.createElement('input');
        textInput.type = 'text';
        textInput.className = input.className;
        textInput.placeholder = 'HH:MM';
        textInput.maxLength = 5;

        if (currentValue) {
            textInput.value = formatTimeDisplay(currentValue);
        }

        input.style.display = 'none';
        input.dataset.initialized = 'true';

        wrapper.appendChild(input);
        wrapper.appendChild(textInput);

        if (input.required) textInput.required = true;
        if (input.disabled) textInput.disabled = true;
        if (input.readOnly) textInput.readOnly = true;

        textInput.addEventListener('input', function(e) {
            let value = this.value.replace(/\D/g, '');

            if (value.length >= 2) {
                value = value.substring(0, 2) + ':' + value.substring(2);
            }
            if (value.length > 5) {
                value = value.substring(0, 5);
            }

            this.value = value;

            const digits = value.replace(/\D/g, '');
            if (digits.length === 4) {
                const hour = digits.substring(0, 2);
                const minute = digits.substring(2, 4);
                if (parseInt(hour) < 24 && parseInt(minute) < 60) {
                    input.value = `${hour}:${minute}`;
                } else {
                    input.value = '';
                }
            } else {
                input.value = '';
            }
        });

        // Handle backspace to skip over colon
        textInput.addEventListener('keydown', function(e) {
            if (e.key === 'Backspace') {
                const pos = this.selectionStart;
                // If cursor is right after a colon, delete the character before the colon too
                if (pos > 0 && this.value[pos - 1] === ':') {
                    e.preventDefault();
                    const before = this.value.substring(0, pos - 2);
                    const after = this.value.substring(pos);
                    this.value = before + after;
                    // Reformat
                    let digits = this.value.replace(/\D/g, '');
                    let formatted = digits;
                    if (digits.length >= 2) {
                        formatted = digits.substring(0, 2) + ':' + digits.substring(2);
                    }
                    this.value = formatted;
                    // Update hidden input
                    if (digits.length === 4) {
                        const hour = digits.substring(0, 2);
                        const minute = digits.substring(2, 4);
                        if (parseInt(hour) < 24 && parseInt(minute) < 60) {
                            input.value = `${hour}:${minute}`;
                        } else {
                            input.value = '';
                        }
                    } else {
                        input.value = '';
                    }
                    // Set cursor position
                    const newPos = Math.max(0, pos - 2);
                    this.setSelectionRange(newPos, newPos);
                }
            }
        });

        textInput.addEventListener('paste', function(e) {
            e.preventDefault();
            const pastedText = (e.clipboardData || window.clipboardData).getData('text');
            const digits = pastedText.replace(/\D/g, '');

            this.value = '';
            for (let i = 0; i < Math.min(digits.length, 4); i++) {
                this.value += digits[i];
                if (this.value.replace(/\D/g, '').length === 2) {
                    this.value += ':';
                }
            }
            this.dispatchEvent(new Event('input'));
        });
    }

    function formatTimeDisplay(time) {
        if (!time) return '';
        const parts = time.split(':');
        if (parts.length >= 2) {
            return parts[0].padStart(2, '0') + ':' + parts[1].padStart(2, '0');
        }
        const digits = time.replace(/\D/g, '');
        if (digits.length >= 4) {
            return digits.substring(0, 2) + ':' + digits.substring(2, 4);
        }
        return time;
    }

    /**
     * Add styles
     */
    function addStyles() {
        if (document.getElementById('datetime-input-styles')) return;

        const style = document.createElement('style');
        style.id = 'datetime-input-styles';
        style.textContent = `
            .date-input-wrapper,
            .time-input-wrapper {
                position: relative;
                display: inline-flex;
                align-items: center;
                width: 100%;
            }

            .date-input-wrapper input[type="text"],
            .time-input-wrapper input[type="text"] {
                flex: 1;
                padding-right: 2.5rem !important;
            }

            .calendar-btn {
                position: absolute;
                right: 4px;
                top: 50%;
                transform: translateY(-50%);
                background: none;
                border: none;
                cursor: pointer;
                padding: 4px;
                color: var(--text-secondary, #64748b);
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 4px;
                transition: all 0.2s;
            }

            .calendar-btn:hover {
                background: var(--border-color, #e2e8f0);
                color: var(--accent-color, #3b82f6);
            }

            .calendar-btn .material-icons {
                font-size: 1.25rem;
            }

            .calendar-popup {
                position: absolute;
                top: 100%;
                left: 0;
                z-index: 1000;
                background: var(--card-bg, #ffffff);
                border: 1px solid var(--border-color, #e2e8f0);
                border-radius: 8px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.15);
                padding: 0.75rem;
                display: none;
                min-width: 280px;
                margin-top: 4px;
            }

            .calendar-popup.show {
                display: block;
            }

            .calendar-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 0.75rem;
                padding-bottom: 0.5rem;
                border-bottom: 1px solid var(--border-color, #e2e8f0);
            }

            .calendar-title {
                font-weight: 600;
                font-size: 0.95rem;
                color: var(--text-primary, #1e293b);
            }

            .calendar-nav {
                background: none;
                border: 1px solid var(--border-color, #e2e8f0);
                width: 28px;
                height: 28px;
                border-radius: 6px;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                color: var(--text-secondary, #64748b);
                font-size: 0.9rem;
                transition: all 0.2s;
            }

            .calendar-nav:hover {
                background: var(--accent-color, #3b82f6);
                border-color: var(--accent-color, #3b82f6);
                color: white;
            }

            .calendar-weekdays {
                display: grid;
                grid-template-columns: repeat(7, 1fr);
                gap: 2px;
                margin-bottom: 0.5rem;
            }

            .calendar-weekdays span {
                text-align: center;
                font-size: 0.75rem;
                font-weight: 600;
                color: var(--text-secondary, #64748b);
                padding: 0.25rem;
            }

            .calendar-days {
                display: grid;
                grid-template-columns: repeat(7, 1fr);
                gap: 2px;
            }

            .calendar-day {
                text-align: center;
                padding: 0.5rem 0.25rem;
                font-size: 0.85rem;
                border-radius: 6px;
                cursor: pointer;
                transition: all 0.15s;
                color: var(--text-primary, #1e293b);
            }

            .calendar-day:hover {
                background: var(--bg-color, #f1f5f9);
            }

            .calendar-day.other-month {
                color: var(--text-secondary, #94a3b8);
                opacity: 0.5;
                cursor: default;
            }

            .calendar-day.today {
                background: var(--bg-color, #f1f5f9);
                font-weight: 600;
            }

            .calendar-day.selected {
                background: var(--accent-color, #3b82f6);
                color: white;
            }

            .calendar-day.selected:hover {
                background: var(--accent-color, #3b82f6);
            }
        `;
        document.head.appendChild(style);
    }

    /**
     * Initialize all date and time inputs
     */
    function initAll() {
        addStyles();

        document.querySelectorAll('input[type="date"]').forEach(input => {
            if (!input.dataset.initialized) {
                initDateInput(input);
            }
        });

        document.querySelectorAll('input[type="time"]').forEach(input => {
            if (!input.dataset.initialized) {
                initTimeInput(input);
            }
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }

    // Re-initialize when new content is added
    const observer = new MutationObserver(function(mutations) {
        let shouldInit = false;
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes.length) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType === 1) {
                        if (node.matches && (node.matches('input[type="date"]') || node.matches('input[type="time"]'))) {
                            shouldInit = true;
                        }
                        if (node.querySelectorAll) {
                            const inputs = node.querySelectorAll('input[type="date"], input[type="time"]');
                            if (inputs.length) shouldInit = true;
                        }
                    }
                });
            }
        });
        if (shouldInit) {
            setTimeout(initAll, 10);
        }
    });

    observer.observe(document.body, { childList: true, subtree: true });

    // Expose for manual use
    window.DateTimeInput = {
        initDate: initDateInput,
        initTime: initTimeInput,
        initAll: initAll
    };
})();
