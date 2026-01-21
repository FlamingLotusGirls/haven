// Flame Control Dashboard JavaScript
class FlameController {
    constructor() {
        this.baseUrl = window.location.origin;
        this.repeatTimers = new Map(); // Store active repeat timers
        this.triggerPollInterval = null; // For periodic trigger status updates
        this.init();
    }

    init() {
        this.bindEvents();
        this.initTabs();
        this.loadSystemStatus();
        this.loadPatterns();
    }

    initTabs() {
        // Tab switching
        document.querySelectorAll('.tab-button').forEach(button => {
            button.addEventListener('click', (e) => {
                const tabId = e.target.getAttribute('data-tab');
                this.switchTab(tabId);
                
                // Load data when switching to specific tabs
                if (tabId === 'patterns') {
                    this.loadPatterns();
                } else if (tabId === 'triggers') {
                    this.loadTriggerIntegration();
                }
            });
        });
    }

    switchTab(tabId) {
        // Hide all tabs
        document.querySelectorAll('.tab-content').forEach(tab => {
            tab.classList.remove('active');
        });
        
        // Remove active class from all buttons
        document.querySelectorAll('.tab-button').forEach(button => {
            button.classList.remove('active');
        });
        
        // Show selected tab
        const selectedTab = document.getElementById(`tab-${tabId}`);
        if (selectedTab) {
            selectedTab.classList.add('active');
        }
        
        // Set active button
        const selectedButton = document.querySelector(`[data-tab="${tabId}"]`);
        if (selectedButton) {
            selectedButton.classList.add('active');
        }
        
        // Stop trigger polling if switching away from triggers tab
        if (tabId !== 'triggers' && this.triggerPollInterval) {
            clearInterval(this.triggerPollInterval);
            this.triggerPollInterval = null;
        }
    }

    bindEvents() {
        // Global controls
        document.getElementById('globalPlay').addEventListener('click', () => this.setGlobalState('play'));
        document.getElementById('globalPause').addEventListener('click', () => this.setGlobalState('pause'));
        document.getElementById('refreshStatus').addEventListener('click', () => this.loadSystemStatus());
        document.getElementById('refreshPatterns').addEventListener('click', () => this.loadPatterns());

        // Poofer toggle buttons
        document.querySelectorAll('.toggle-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const pooferId = e.target.getAttribute('data-poofer');
                this.togglePoofer(pooferId, e.target);
            });
        });

        // Poofer fire buttons
        document.querySelectorAll('.fire-btn').forEach(btn => {
            // Minor hack - the API to fire the poofer actually invokes a special
            // sequence just for that poofer. Said sequence has '__' in front of the poofer 
            // name
            btn.addEventListener('click', (e) => {
                const pooferId = '__' + e.target.getAttribute('data-poofer');
                this.firePoofer(pooferId, e.target);
            });
        });

        // Sequence buttons
        document.querySelectorAll('.sequence-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const sequenceId = e.target.getAttribute('data-sequence');
                this.fireSequence(sequenceId, e.target);
            });
        });

        // Repeat buttons
        document.querySelectorAll('.repeat-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const sequenceId = e.target.getAttribute('data-sequence');
                this.toggleRepeat(sequenceId, e.target);
            });
        });

        // Pattern management
        document.getElementById('addPatternBtn').addEventListener('click', () => this.showPatternModal());
        document.getElementById('patternForm').addEventListener('submit', (e) => this.savePattern(e));
        document.getElementById('cancelPattern').addEventListener('click', () => this.hidePatternModal());
        document.getElementById('addEventBtn').addEventListener('click', () => this.addEventRowIfValid());
   
        // Modal close buttons
        document.querySelectorAll('.close').forEach(closeBtn => {
            closeBtn.addEventListener('click', (e) => {
                const modal = e.target.closest('.modal');
                modal.style.display = 'none';
                // Restore body scroll
                document.body.classList.remove('modal-open');
            });
        });

        // Close modals when clicking outside
        window.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                e.target.style.display = 'none';
                // Restore body scroll
                document.body.classList.remove('modal-open');
            }
        });

        // Initialize by calling system status
        this.loadSystemStatus();
    }

    async setGlobalState(state) {
        try {
            const response = await fetch(`${this.baseUrl}/flame`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `playState=${state}`
            });

            if (response.ok) {
                this.showMessage(`Global state set to ${state}`, 'success');
                this.loadSystemStatus();
            } else {
                this.showMessage(`Failed to set global state to ${state}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error: ${error.message}`, 'error');
        }
    }

    async togglePoofer(pooferId, button) {
        var newTextContext = button.textContext;
        try {
            // First get current status
            const statusResponse = await fetch(`${this.baseUrl}/flame/poofers/${pooferId}`);
            const status = await statusResponse.json();
            
            // Toggle the enabled state
            const newState = !status.enabled;
            
            button.disabled = true;
            button.textContent = 'Working...';

            const response = await fetch(`${this.baseUrl}/flame/poofers/${pooferId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `enabled=${newState}`
            });

            if (response.ok) {
                this.showMessage(`Poofer ${pooferId} ${newState ? 'enabled' : 'disabled'}`, 'success');
                this.updatePooferStatus(pooferId, newState);
                if (newState) {
                    newTextContext = "Disable";
                } else {
                    newTextContext = "Enable";
                }
            } else {
                this.showMessage(`Failed to toggle poofer ${pooferId}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error toggling poofer ${pooferId}: ${error.message}`, 'error');
        } finally {
            button.disabled = false;
            button.textContent = newTextContext;
        }
    }

    async firePoofer(pooferId, button) {
        const originalTextContent = button.textContent;
        try {
            button.disabled = true;
            button.textContent = 'Firing...';

            const response = await fetch(`${this.baseUrl}/flame/patterns/${pooferId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `active=true`
            });

            if (response.ok) {
                this.showMessage(`Poofer ${pooferId} fired!`, 'success');
                // Visual feedback - make fire icon glow briefly
                const pooferItem = document.querySelector(`[data-poofer="${pooferId}"]`);
                if (pooferItem) {
                    const fireIcon = pooferItem.querySelector('.fire-icon');
                    fireIcon.style.filter = 'drop-shadow(0 0 20px rgba(255, 69, 0, 1)) brightness(1.5)';
                    fireIcon.style.transform = 'scale(1.2)';
                    
                    setTimeout(() => {
                        fireIcon.style.filter = 'drop-shadow(0 0 10px rgba(255, 69, 0, 0.7))';
                        fireIcon.style.transform = 'scale(1)';
                    }, 1000);
                }
            } else {
                this.showMessage(`Failed to fire poofer ${pooferId}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error firing poofer ${pooferId}: ${error.message}`, 'error');
        } finally {
            button.disabled = false;
            button.textContent = originalTextContent;
        }
    }

    async fireSequence(sequenceId, button) {
        const originalText = button.textContent;
        const originalBgColor = button.style.backgroundColor;
        const originalTextColor = button.style.color;
        
        try {
            button.disabled = true;
            button.textContent = 'Firing...';
            
            // Add glow effect with color changes
            button.style.boxShadow = '0 0 20px rgba(255, 69, 0, 0.8)';
            button.style.transform = 'scale(1.05)';
            button.style.backgroundColor = '#ff4500';
            button.style.color = 'white';

            const response = await fetch(`${this.baseUrl}/flame/patterns/${sequenceId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `active=true`
            });

            if (response.ok) {
                this.showMessage(`Sequence ${sequenceId} fired!`, 'success');
            } else {
                this.showMessage(`Failed to fire sequence ${sequenceId}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error firing sequence ${sequenceId}: ${error.message}`, 'error');
        } finally {
            button.disabled = false;
            button.textContent = originalText;
            
            // Remove glow effect after a brief delay
            setTimeout(() => {
                button.style.boxShadow = '';
                button.style.transform = '';
                button.style.backgroundColor = originalBgColor;
                button.style.color = originalTextColor;
            }, 1000);
        }
    }

    toggleRepeat(sequenceId, button) {
        const sequenceItem = button.closest('.sequence-item');
        const intervalInput = sequenceItem.querySelector('.repeat-interval');
        const statusIndicator = sequenceItem.querySelector('.repeat-status');
        
        if (this.repeatTimers.has(sequenceId)) {
            // Stop repeating
            clearInterval(this.repeatTimers.get(sequenceId));
            this.repeatTimers.delete(sequenceId);
            
            // Update UI
            button.style.backgroundColor = '';
            button.style.color = '';
            button.title = 'Toggle repeat';
            statusIndicator.textContent = 'Stopped';
            statusIndicator.className = 'repeat-status stopped';
            
            this.showMessage(`Repeat stopped for ${sequenceId}`, 'info');
        } else {
            // Start repeating
            const interval = parseInt(intervalInput.value) * 1000; // Convert to milliseconds
            
            if (interval < 1000) {
                this.showMessage('Repeat interval must be at least 1 second', 'error');
                return;
            }
            
            // Update button appearance
            button.style.backgroundColor = '#28a745';
            button.style.color = 'white';
            button.title = 'Stop repeat';
            statusIndicator.textContent = `Repeating (${intervalInput.value}s)`;
            statusIndicator.className = 'repeat-status repeating';
            
            // Start the repeat timer
            const timerId = setInterval(async () => {
                try {
                    const response = await fetch(`${this.baseUrl}/flame/patterns/${sequenceId}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                        },
                        body: `active=true`
                    });
                    
                    if (!response.ok) {
                        console.error(`Failed to fire sequence ${sequenceId} during repeat`);
                    }
                } catch (error) {
                    console.error(`Error firing sequence ${sequenceId} during repeat:`, error);
                }
            }, interval);
            
            this.repeatTimers.set(sequenceId, timerId);
            this.showMessage(`Repeat started for ${sequenceId} every ${intervalInput.value} seconds`, 'success');
        }
    }

    updatePooferStatus(pooferId, enabled) {
        const pooferItem = document.querySelector(`[data-poofer="${pooferId}"]`);
        if (pooferItem) {
            const statusDot = pooferItem.querySelector('.status-dot');
            const fireIcon = pooferItem.querySelector('.fire-icon');
            
            if (enabled) {
                statusDot.classList.add('enabled');
                statusDot.classList.remove('disabled');
                fireIcon.style.opacity = '1';
                fireIcon.style.filter = 'brightness(1.2)';
            } else {
                statusDot.classList.add('disabled');
                statusDot.classList.remove('enabled');
                fireIcon.style.opacity = '0.5';
                fireIcon.style.filter = 'grayscale(1)';
            }
        }
    }

    async loadSystemStatus() {
        try {
            const response = await fetch(`${this.baseUrl}/flame`);
            const data = await response.json();
            
            this.displaySystemStatus(data);
            this.updatePooferStatuses(data.poofers);
        } catch (error) {
            document.getElementById('systemStatus').innerHTML = `<div class="error">Error loading status: ${error.message}</div>`;
        }
    }

    displaySystemStatus(data) {
        const statusHtml = `
            <div class="status-grid">
                <div class="status-item">
                    <strong>Global State:</strong> 
                    <span class="${data.globalState ? 'enabled' : 'disabled'}">
                        ${data.globalState ? 'Playing' : 'Paused'}
                    </span>
                </div>
                <div class="status-item">
                    <strong>Active Poofers:</strong> ${data.poofers.filter(p => p.active).length}
                </div>
                <div class="status-item">
                    <strong>Enabled Poofers:</strong> ${data.poofers.filter(p => p.enabled).length}
                </div>
                <div class="status-item">
                    <strong>Active Patterns:</strong> ${data.patterns.filter(p => p.active).length}
                </div>
            </div>
        `;
        document.getElementById('systemStatus').innerHTML = statusHtml;
        
        const globalStatus = document.getElementById('globalStatus');
        globalStatus.textContent = `Status: ${data.globalState ? 'Playing' : 'Paused'}`;
        globalStatus.className = `status-indicator ${data.globalState ? 'enabled' : 'disabled'}`;
        
        // Update button visibility based on state
        const playBtn = document.getElementById('globalPlay');
        const pauseBtn = document.getElementById('globalPause');
        
        if (data.globalState) {
            // System is playing, show pause button
            playBtn.style.display = 'none';
            pauseBtn.style.display = 'inline-block';
        } else {
            // System is paused, show play button
            playBtn.style.display = 'inline-block';
            pauseBtn.style.display = 'none';
        }
    }

    updatePooferStatuses(poofers) {
        poofers.forEach(poofer => {
            this.updatePooferStatus(poofer.id, poofer.enabled);
        });
    }

    async loadPatterns() {
        try {
            const response = await fetch(`${this.baseUrl}/flame/patterns`);
            const patterns = await response.json();
            
            this.displayPatterns(patterns);
        } catch (error) {
            document.getElementById('patternsContainer').innerHTML = `<div class="error">Error loading patterns: ${error.message}</div>`;
        }
    }

    displayPatterns(patterns) {
        // Filter out patterns that begin with "__"
        const filteredPatterns = patterns.filter(pattern => !pattern.name.startsWith('__'));
        
        const patternsHtml = filteredPatterns.map(pattern => `
            <div class="pattern-item">
                <div class="pattern-info">
                    <strong>${pattern.name}</strong>
                    <span class="pattern-status ${pattern.enabled ? 'enabled' : 'disabled'}">
                        ${pattern.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                    ${pattern.active ? '<span class="pattern-active">Active</span>' : ''}
                </div>
                <div class="pattern-controls">
                    <button class="btn btn-sm" onclick="flameController.togglePattern('${pattern.name}', 'enabled')">
                        ${pattern.enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button class="btn btn-sm" onclick="flameController.togglePattern('${pattern.name}', 'active')">
                        ${pattern.active ? 'Stop' : 'Start'}
                    </button>
                    <button class="btn btn-sm btn-primary" onclick="flameController.editPattern('${pattern.name}')">
                        Edit
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="flameController.deletePattern('${pattern.name}')">
                        Delete
                    </button>
                </div>
            </div>
        `).join('');
        
        document.getElementById('patternsContainer').innerHTML = patternsHtml || '<div class="info">No user patterns found</div>';
    }

    async togglePattern(patternName, property) {
        try {
            // Get current status first
            const statusResponse = await fetch(`${this.baseUrl}/flame/patterns/${patternName}`);
            const status = await statusResponse.json();
            
            const newValue = !status[property];
            
            const response = await fetch(`${this.baseUrl}/flame/patterns/${patternName}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `${property}=${newValue}`
            });

            if (response.ok) {
                this.showMessage(`Pattern ${patternName} ${property} set to ${newValue}`, 'success');
                this.loadPatterns();
            } else {
                this.showMessage(`Failed to update pattern ${patternName}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error updating pattern: ${error.message}`, 'error');
        }
    }

    async editPattern(patternName) {
        try {
            // Fetch the existing pattern data with 'full' parameter to get events
            const response = await fetch(`${this.baseUrl}/flame/patterns/${patternName}?full=true`);
            
            if (response.ok) {
                const patternData = await response.json();
                // Open the modal with the existing pattern data
                this.showPatternModal(patternData);
            } else {
                this.showMessage(`Failed to load pattern ${patternName}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error loading pattern: ${error.message}`, 'error');
        }
    }

    async deletePattern(patternName) {
        if (!confirm(`Are you sure you want to delete pattern "${patternName}"?`)) {
            return;
        }

        try {
            const response = await fetch(`${this.baseUrl}/flame/patterns/${patternName}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.showMessage(`Pattern ${patternName} deleted`, 'success');
                this.loadPatterns();
            } else {
                this.showMessage(`Failed to delete pattern ${patternName}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error deleting pattern: ${error.message}`, 'error');
        }
    }

    showPatternModal(pattern = null) {
        const modal = document.getElementById('patternModal');
        const title = document.getElementById('modalTitle');
        const nameInput = document.getElementById('patternName');
        const eventsContainer = document.getElementById('eventsContainer');

        if (pattern) {
            title.textContent = 'Edit Pattern';
            nameInput.value = pattern.name;
            // Load existing events
            eventsContainer.innerHTML = '';
            pattern.events.forEach(event => {
                this.addEventRow(event);
            });
        } else {
            title.textContent = 'Add New Pattern';
            nameInput.value = '';
            eventsContainer.innerHTML = '';
            // Add one empty event row to start
            this.addEventRow();
        }

        // Prevent body scroll
        document.body.classList.add('modal-open');
        modal.style.display = 'block';
    }

    hidePatternModal() {
        document.getElementById('patternModal').style.display = 'none';
        // Clear events container
        document.getElementById('eventsContainer').innerHTML = '';
        // Restore body scroll
        document.body.classList.remove('modal-open');
    }

    addEventRowIfValid() {
        // Check if all existing event rows have poofers selected
        const existingRows = document.querySelectorAll('.event-row');
        
        for (let row of existingRows) {
            const pooferSelect = row.querySelector('.event-poofer-id');
            if (!pooferSelect.value) {
                this.showMessage('Please select a poofer for all existing events before adding a new one', 'error');
                // Highlight the empty select field
                pooferSelect.style.borderColor = '#dc3545';
                pooferSelect.focus();
                
                // Remove highlight after 3 seconds
                setTimeout(() => {
                    pooferSelect.style.borderColor = '';
                }, 3000);
                
                return;
            }
        }
        
        // If all existing events have poofers selected, add a new row
        this.addEventRow();
    }

    addEventRow(eventData = null) {
        const eventsContainer = document.getElementById('eventsContainer');
        const eventIndex = eventsContainer.children.length;
        
        // Valid poofer IDs from poofermapping.py
        const validPooferIds = [
            'C1', 'C2', 'C3', 'C4', 'C5', 'C6',
            'C_HAIR1', 'C_HAIR2', 'C_HAIR3', 'C_HAIR4',
            'O_EYES', 'O_WINGS', 'O1', 'O2', 'O3',
            'M_TAIL', 'M1', 'M2', 'M3',
            'P1', 'P2', 'P3', 'P4'
        ];

        const eventRow = document.createElement('div');
        eventRow.className = 'event-row';
        eventRow.innerHTML = `
            <div class="event-fields">
                <div class="field-group">
                    <label>Poofer ID:</label>
                    <select class="event-poofer-id" required>
                        <option value="">Select Poofer</option>
                        ${validPooferIds.map(id => 
                            `<option value="${id}" ${eventData && eventData.ids && eventData.ids.includes(id) ? 'selected' : ''}>${id}</option>`
                        ).join('')}
                    </select>
                </div>
                <div class="field-group">
                    <label>Start Time (seconds):</label>
                    <input type="number" class="event-start-time" step="0.1" min="0" value="${eventData ? eventData.startTime : 0}" required>
                </div>
                <div class="field-group">
                    <label>Duration (seconds):</label>
                    <input type="number" class="event-duration" step="0.1" min="0.1" value="${eventData ? eventData.duration : 0.5}" required>
                </div>
                <div class="field-group">
                    <button type="button" class="btn btn-danger btn-sm remove-event">Remove</button>
                </div>
            </div>
        `;

        // Add event listener for remove button
        eventRow.querySelector('.remove-event').addEventListener('click', () => {
            eventRow.remove();
        });

        eventsContainer.appendChild(eventRow);
    }

    async savePattern(event) {
        event.preventDefault();
        
        const patternName = document.getElementById('patternName').value.trim();
        if (!patternName) {
            this.showMessage('Pattern name is required', 'error');
            return;
        }

        // Validate that user patterns cannot start with "__"
        if (patternName.startsWith('__')) {
            this.showMessage('Pattern names cannot start with "__" - this prefix is reserved for system patterns', 'error');
            // Highlight the pattern name field
            const nameInput = document.getElementById('patternName');
            nameInput.style.borderColor = '#dc3545';
            nameInput.focus();
            
            // Remove highlight after 3 seconds
            setTimeout(() => {
                nameInput.style.borderColor = '';
            }, 3000);
            
            return;
        }

        // Check for duplicate pattern names (case-insensitive) when creating new patterns
        const modalTitle = document.getElementById('modalTitle').textContent;
        const isEditing = modalTitle === 'Edit Pattern';
        
        if (!isEditing) {
            try {
                const response = await fetch(`${this.baseUrl}/flame/patterns`);
                const existingPatterns = await response.json();
                
                // Check if pattern name already exists (case-insensitive)
                const duplicatePattern = existingPatterns.find(pattern => 
                    pattern.name.toLowerCase() === patternName.toLowerCase()
                );
                
                if (duplicatePattern) {
                    this.showMessage(`A pattern named "${duplicatePattern.name}" already exists. Please choose a different name.`, 'error');
                    // Highlight the pattern name field
                    const nameInput = document.getElementById('patternName');
                    nameInput.style.borderColor = '#dc3545';
                    nameInput.focus();
                    
                    // Remove highlight after 3 seconds
                    setTimeout(() => {
                        nameInput.style.borderColor = '';
                    }, 3000);
                    
                    return;
                }
            } catch (error) {
                this.showMessage(`Error checking for duplicate patterns: ${error.message}`, 'error');
                return;
            }
        }

        // Collect events from the form
        const eventRows = document.querySelectorAll('.event-row');
        const events = [];
        
        for (let row of eventRows) {
            const pooferId = row.querySelector('.event-poofer-id').value;
            const startTime = parseFloat(row.querySelector('.event-start-time').value);
            const duration = parseFloat(row.querySelector('.event-duration').value);
            
            if (!pooferId) {
                this.showMessage('All events must have a poofer ID selected', 'error');
                return;
            }
            
            if (isNaN(startTime) || startTime < 0) {
                this.showMessage('Start time must be a valid number >= 0', 'error');
                return;
            }
            
            if (isNaN(duration) || duration <= 0) {
                this.showMessage('Duration must be a valid number > 0', 'error');
                return;
            }

            events.push({
                ids: [pooferId],
                startTime: startTime,
                duration: duration
            });
        }

        if (events.length === 0) {
            this.showMessage('At least one event is required', 'error');
            return;
        }

        const patternData = {
            name: patternName,
            events: events,
            modifiable: true
        };
        
        try {
            const response = await fetch(`${this.baseUrl}/flame/patterns`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `patternData=${encodeURIComponent(JSON.stringify(patternData))}`
            });

            if (response.ok) {
                this.showMessage(`Pattern "${patternName}" saved successfully`, 'success');
                this.hidePatternModal();
                this.loadPatterns();
            } else {
                const errorText = await response.text();
                this.showMessage(`Failed to save pattern: ${errorText}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error saving pattern: ${error.message}`, 'error');
        }
    }

    // External API Demo Functions
    async fetchExternalData() {
        const apiUrl = document.getElementById('apiUrl').value;
        if (!apiUrl) {
            this.showMessage('Please enter an API URL', 'error');
            return;
        }

        try {
            const response = await fetch(apiUrl);
            const data = await response.json();
            
            this.displayExternalData(data, apiUrl);
        } catch (error) {
            this.showMessage(`Error fetching external data: ${error.message}`, 'error');
        }
    }

    displayExternalData(data, apiUrl) {
        const container = document.getElementById('externalApiData');
        
        // Handle both single objects and arrays
        const items = Array.isArray(data) ? data.slice(0, 5) : [data]; // Show first 5 items if array
        
        const html = `
            <div class="api-results">
                <h4>Data from: ${apiUrl}</h4>
                ${items.map((item, index) => `
                    <div class="api-item">
                        <div class="api-item-header">
                            <strong>Item ${Array.isArray(data) ? item.id || index + 1 : 1}</strong>
                            <div class="api-item-controls">
                                <button class="btn btn-sm" onclick="flameController.editApiItem(${JSON.stringify(item).replace(/"/g, '&quot;')})">Edit</button>
                                <button class="btn btn-sm btn-danger" onclick="flameController.deleteApiItem('${apiUrl}', ${item.id || index + 1})">Delete</button>
                            </div>
                        </div>
                        <div class="api-item-content">
                            <pre>${JSON.stringify(item, null, 2)}</pre>
                        </div>
                    </div>
                `).join('')}
                ${Array.isArray(data) && data.length > 5 ? `<div class="info">Showing 5 of ${data.length} items</div>` : ''}
            </div>
        `;
        
        container.innerHTML = html;
    }

    showApiModal(item = null) {
        const modal = document.getElementById('apiModal');
        const title = document.getElementById('apiModalTitle');
        const titleInput = document.getElementById('apiTitle');
        const bodyInput = document.getElementById('apiBody');
        const userIdInput = document.getElementById('apiUserId');

        if (item) {
            title.textContent = 'Edit API Data';
            titleInput.value = item.title || '';
            bodyInput.value = item.body || '';
            userIdInput.value = item.userId || 1;
        } else {
            title.textContent = 'Create New API Data';
            titleInput.value = '';
            bodyInput.value = '';
            userIdInput.value = 1;
        }

        modal.style.display = 'block';
    }

    hideApiModal() {
        document.getElementById('apiModal').style.display = 'none';
    }

    editApiItem(item) {
        this.showApiModal(item);
    }

    async deleteApiItem(baseUrl, itemId) {
        if (!confirm(`Are you sure you want to delete item ${itemId}?`)) {
            return;
        }

        try {
            const response = await fetch(`${baseUrl}/${itemId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.showMessage(`Item ${itemId} deleted`, 'success');
                this.fetchExternalData(); // Refresh the data
            } else {
                this.showMessage(`Failed to delete item ${itemId}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error deleting item: ${error.message}`, 'error');
        }
    }

    async saveApiData(event) {
        event.preventDefault();
        
        const apiUrl = document.getElementById('apiUrl').value;
        const title = document.getElementById('apiTitle').value;
        const body = document.getElementById('apiBody').value;
        const userId = document.getElementById('apiUserId').value;

        const data = {
            title: title,
            body: body,
            userId: parseInt(userId)
        };

        try {
            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data)
            });

            if (response.ok) {
                const result = await response.json();
                this.showMessage(`API data created with ID: ${result.id}`, 'success');
                this.hideApiModal();
                this.fetchExternalData(); // Refresh the data
            } else {
                this.showMessage('Failed to create API data', 'error');
            }
        } catch (error) {
            this.showMessage(`Error creating API data: ${error.message}`, 'error');
        }
    }

    showMessage(message, type = 'info') {
        // Create a temporary message element
        const messageEl = document.createElement('div');
        messageEl.className = `message message-${type}`;
        messageEl.textContent = message;
        messageEl.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 10px 20px;
            border-radius: 4px;
            color: white;
            z-index: 1000;
            background-color: ${type === 'success' ? '#28a745' : type === 'error' ? '#dc3545' : '#17a2b8'};
        `;

        document.body.appendChild(messageEl);

        // Remove after 3 seconds
        setTimeout(() => {
            if (messageEl.parentNode) {
                messageEl.parentNode.removeChild(messageEl);
            }
        }, 3000);
    }

    // Trigger Integration Functions
    async loadTriggerIntegration() {
        await this.loadTriggerStatus();
        await this.loadAvailableTriggers();
        await this.loadAvailableSequencesForTriggers();
        await this.loadTriggerMappings();
        this.initTriggerForm();
        
        // Start periodic polling for trigger status updates (every 2 minutes)
        if (this.triggerPollInterval) {
            clearInterval(this.triggerPollInterval);
        }
        this.triggerPollInterval = setInterval(async () => {
            // Silently update trigger data in background
            await this.loadAvailableTriggers();
            await this.loadTriggerMappings();
        }, 120000); // 2 minutes in milliseconds
    }

    async loadTriggerStatus() {
        try {
            const response = await fetch(`${this.baseUrl}/trigger-integration/status`);
            const status = await response.json();
            
            const statusBox = document.getElementById('trigger-status-box');
            const statusClass = status.registered ? 'success' : 'error';
            statusBox.className = statusClass;
            statusBox.innerHTML = `
                <strong>Integration Status:</strong><br>
                Connected to Trigger Server: <strong>${status.registered ? 'Yes ✓' : 'No ✗'}</strong><br>
                Trigger Server: ${status.trigger_server_url}<br>
                Listen Port: ${status.listen_port}<br>
                Active Mappings: ${status.mapping_count}<br>
                Available Triggers: ${status.available_triggers_count}
            `;
        } catch (error) {
            const statusBox = document.getElementById('trigger-status-box');
            statusBox.className = 'error';
            statusBox.innerHTML = `<strong>Error:</strong> Cannot connect to trigger integration service`;
        }
    }

    async loadAvailableTriggers() {
        try {
            const response = await fetch(`${this.baseUrl}/trigger-integration/triggers`);
            const data = await response.json();
            this.availableTriggersData = data.triggers || [];
            
            console.log('Loaded triggers:', this.availableTriggersData);
            
            const select = document.getElementById('trigger-name');
            select.innerHTML = '<option value="">Select a trigger...</option>';
            
            this.availableTriggersData.forEach(trigger => {
                // Extract values from range.values for discrete triggers
                const values = trigger.range && trigger.range.values ? trigger.range.values : [];
                console.log(`Trigger: ${trigger.name}, Type: ${trigger.type}, Range:`, trigger.range, 'Values:', values);
                
                const option = document.createElement('option');
                option.value = trigger.name;
                
                // Add OFFLINE indicator to text for offline triggers
                if (trigger.device_status === 'offline') {
                    option.textContent = `${trigger.name} (${trigger.type}) [OFFLINE]`;
                } else {
                    option.textContent = `${trigger.name} (${trigger.type})`;
                }
                
                // Store trigger data for later use
                option.dataset.triggerType = trigger.type;
                option.dataset.triggerValues = JSON.stringify(values);
                option.dataset.deviceStatus = trigger.device_status || 'unknown';
                select.appendChild(option);
            });
            
            // Add change listener to update value field based on trigger type
            select.addEventListener('change', () => this.updateTriggerValueField());
        } catch (error) {
            console.error('Error loading triggers:', error);
        }
    }

    async loadAvailableSequencesForTriggers() {
        try {
            const response = await fetch(`${this.baseUrl}/flame/patterns`);
            const patterns = await response.json();
            
            // Store patterns for later lookup of display names
            this.availablePatternsData = patterns;
            
            const select = document.getElementById('flame-sequence');
            select.innerHTML = '<option value="">Select a flame sequence...</option>';
            
            patterns.forEach(pattern => {
                const option = document.createElement('option');
                option.value = pattern.name;
                // Use display_name if available, otherwise use name
                option.textContent = pattern.display_name || pattern.name;
                select.appendChild(option);
            });
        } catch (error) {
            console.error('Error loading sequences:', error);
        }
    }

    async loadTriggerMappings() {
        try {
            const response = await fetch(`${this.baseUrl}/trigger-integration/mappings`);
            const data = await response.json();
            const mappings = data.mappings || [];
            
            this.displayTriggerMappings(mappings);
        } catch (error) {
            console.error('Error loading mappings:', error);
            document.getElementById('trigger-mappings-table').innerHTML = 
                '<div class="empty-state">Error loading mappings</div>';
        }
    }

    displayTriggerMappings(mappings) {
        const container = document.getElementById('trigger-mappings-table');
        
        if (mappings.length === 0) {
            container.innerHTML = '<div class="empty-state">No mappings configured yet. Create one above!</div>';
            return;
        }
        
        let html = '<table>';
        html += '<thead><tr>';
        html += '<th>Trigger Name</th>';
        html += '<th>Trigger Value</th>';
        html += '<th>Flame Sequence</th>';
        html += '<th>Allow Override</th>';
        html += '<th>Actions</th>';
        html += '</tr></thead><tbody>';
        
        mappings.forEach(mapping => {
            // Check if trigger exists and its status
            const trigger = this.availableTriggersData?.find(t => t.name === mapping.trigger_name);
            let triggerNameDisplay;
            let triggerStyle = '';
            
            if (!trigger) {
                // Trigger not found in available triggers - red text for name only
                triggerNameDisplay = `${this.escapeHtml(mapping.trigger_name)} [Not Found]`;
                triggerStyle = 'color: #dc3545;';
            } else if (trigger.device_status === 'offline') {
                // Trigger exists but is offline - grey text with [Offline] indicator
                triggerNameDisplay = `${this.escapeHtml(mapping.trigger_name)} [Offline]`;
                triggerStyle = 'color: #999;';
            } else {
                // Trigger exists and is online
                triggerNameDisplay = this.escapeHtml(mapping.trigger_name);
            }
            
            html += `<tr>`;
            html += `<td style="${triggerStyle}">${triggerNameDisplay}</td>`;
            
            // Format trigger value display based on whether it's a range or single value
            let valueDisplay;
            if (mapping.trigger_value_min !== undefined && mapping.trigger_value_max !== undefined) {
                // Both min and max specified
                valueDisplay = `${mapping.trigger_value_min} - ${mapping.trigger_value_max}`;
            } else if (mapping.trigger_value_min !== undefined) {
                // Only min specified
                valueDisplay = `≥ ${mapping.trigger_value_min}`;
            } else if (mapping.trigger_value_max !== undefined) {
                // Only max specified
                valueDisplay = `≤ ${mapping.trigger_value_max}`;
            } else if (mapping.trigger_value) {
                // Single discrete value
                valueDisplay = this.escapeHtml(mapping.trigger_value);
            } else {
                // No value specified - any value
                valueDisplay = '<em>any</em>';
            }
            
            html += `<td>${valueDisplay}</td>`;
            
            // Look up display name for the flame sequence
            let sequenceDisplay = this.escapeHtml(mapping.flame_sequence);
            if (this.availablePatternsData) {
                const pattern = this.availablePatternsData.find(p => p.name === mapping.flame_sequence);
                if (pattern && pattern.display_name) {
                    sequenceDisplay = this.escapeHtml(pattern.display_name);
                }
            }
            
            html += `<td>${sequenceDisplay}</td>`;
            html += `<td>${mapping.allow_override ? 'Yes' : 'No'}</td>`;
            html += `<td>`;
            html += `<button class="btn btn-primary btn-sm" onclick="flameController.editTriggerMapping(${mapping.id})">Edit</button>`;
            html += `<button class="btn btn-danger btn-sm" onclick="flameController.deleteTriggerMapping(${mapping.id})">Delete</button>`;
            html += `</td>`;
            html += '</tr>';
        });
        
        html += '</tbody></table>';
        container.innerHTML = html;
    }

    initTriggerForm() {
        const form = document.getElementById('triggerMappingForm');
        if (form && !form.dataset.initialized) {
            form.dataset.initialized = 'true';
            form.addEventListener('submit', (e) => this.saveTriggerMapping(e));
            
            const cancelBtn = document.getElementById('cancel-trigger-btn');
            if (cancelBtn) {
                cancelBtn.addEventListener('click', () => this.resetTriggerForm());
            }
            
            // Add reveal button handler
            const addBtn = document.getElementById('add-trigger-mapping-btn');
            if (addBtn && !addBtn.dataset.initialized) {
                addBtn.dataset.initialized = 'true';
                addBtn.addEventListener('click', () => {
                    document.getElementById('trigger-mapping-form-container').style.display = 'block';
                    document.getElementById('cancel-trigger-btn').style.display = 'inline-block';
                    addBtn.style.display = 'none';
                });
            }
        }
    }

    async saveTriggerMapping(event) {
        event.preventDefault();
        
        const mappingId = document.getElementById('trigger-mapping-id').value;
        const triggerName = document.getElementById('trigger-name').value;
        const flameSequence = document.getElementById('flame-sequence').value;
        const allowOverride = document.getElementById('allow-override').checked;
        
        // Determine trigger type
        const triggerSelect = document.getElementById('trigger-name');
        const selectedOption = triggerSelect.options[triggerSelect.selectedIndex];
        const triggerType = selectedOption?.dataset.triggerType;
        
        const formData = new FormData();
        formData.append('trigger_name', triggerName);
        formData.append('flame_sequence', flameSequence);
        formData.append('allow_override', allowOverride ? 'true' : 'false');
        
        // Handle continuous triggers with min/max range
        if (triggerType === 'Continuous') {
            const minField = document.getElementById('trigger-value-min');
            const maxField = document.getElementById('trigger-value-max');
            
            if (minField && minField.value !== '') {
                formData.append('trigger_value_min', minField.value);
            }
            if (maxField && maxField.value !== '') {
                formData.append('trigger_value_max', maxField.value);
            }
            
            console.log('Saving continuous trigger mapping:', { 
                mappingId, triggerName, 
                min: minField?.value, max: maxField?.value,
                flameSequence, allowOverride 
            });
        } else {
            // Handle discrete triggers with single value
            const triggerValue = document.getElementById('trigger-value')?.value || '';
            formData.append('trigger_value', triggerValue);
            
            console.log('Saving discrete trigger mapping:', { 
                mappingId, triggerName, triggerValue, flameSequence, allowOverride 
            });
        }
        
        try {
            let url, method;
            if (mappingId) {
                url = `${this.baseUrl}/trigger-integration/mappings/${mappingId}`;
                method = 'PUT';
            } else {
                url = `${this.baseUrl}/trigger-integration/mappings`;
                method = 'POST';
            }
            
            console.log('Request:', method, url);
            
            const response = await fetch(url, {
                method: method,
                body: formData
            });
            
            console.log('Response status:', response.status);
            
            if (response.ok) {
                const responseText = await response.text();
                console.log('Response:', responseText);
                this.showMessage(mappingId ? 'Mapping updated!' : 'Mapping created!', 'success');
                this.resetTriggerForm();
                this.loadTriggerMappings();
                this.loadTriggerStatus();
            } else {
                const errorText = await response.text();
                console.error('Error response:', errorText);
                this.showMessage(`Error: ${errorText}`, 'error');
            }
        } catch (error) {
            console.error('Exception:', error);
            this.showMessage(`Error: ${error.message}`, 'error');
        }
    }

    async editTriggerMapping(id) {
        try {
            const response = await fetch(`${this.baseUrl}/trigger-integration/mappings/${id}`);
            const mapping = await response.json();
            
            // Show the form and hide the button
            document.getElementById('trigger-mapping-form-container').style.display = 'block';
            document.getElementById('add-trigger-mapping-btn').style.display = 'none';
            
            document.getElementById('trigger-form-title').textContent = 'Edit Mapping';
            document.getElementById('trigger-mapping-id').value = mapping.id;
            document.getElementById('trigger-name').value = mapping.trigger_name;
            
            // Trigger the field update to show proper fields for this trigger type
            this.updateTriggerValueField();
            
            // Populate values based on trigger type
            const triggerSelect = document.getElementById('trigger-name');
            const selectedOption = triggerSelect.options[triggerSelect.selectedIndex];
            const triggerType = selectedOption?.dataset.triggerType;
            
            if (triggerType === 'Continuous') {
                // Set min/max values for continuous triggers
                const minField = document.getElementById('trigger-value-min');
                const maxField = document.getElementById('trigger-value-max');
                if (minField) minField.value = mapping.trigger_value_min || '';
                if (maxField) maxField.value = mapping.trigger_value_max || '';
            } else {
                // Set single value for discrete triggers
                const valueField = document.getElementById('trigger-value');
                if (valueField) valueField.value = mapping.trigger_value || '';
            }
            
            document.getElementById('flame-sequence').value = mapping.flame_sequence;
            document.getElementById('allow-override').checked = mapping.allow_override;
            document.getElementById('cancel-trigger-btn').style.display = 'inline-block';
            document.querySelector('#triggerMappingForm button[type="submit"]').textContent = 'Update Mapping';
            
            // Scroll to form
            document.getElementById('trigger-form-title').scrollIntoView({ behavior: 'smooth' });
        } catch (error) {
            this.showMessage(`Error loading mapping: ${error.message}`, 'error');
        }
    }

    async deleteTriggerMapping(id) {
        if (!confirm('Are you sure you want to delete this mapping?')) {
            return;
        }
        
        try {
            const response = await fetch(`${this.baseUrl}/trigger-integration/mappings/${id}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.showMessage('Mapping deleted', 'success');
                this.loadTriggerMappings();
                this.loadTriggerStatus();
            } else {
                this.showMessage('Error deleting mapping', 'error');
            }
        } catch (error) {
            this.showMessage(`Error: ${error.message}`, 'error');
        }
    }

    updateTriggerValueField() {
        const triggerSelect = document.getElementById('trigger-name');
        const selectedOption = triggerSelect.options[triggerSelect.selectedIndex];
        
        if (!selectedOption || !selectedOption.value) {
            return;
        }
        
        const triggerType = selectedOption.dataset.triggerType;
        const triggerValues = JSON.parse(selectedOption.dataset.triggerValues || '[]');
        
        // Get the full trigger data to access range info
        const triggerName = selectedOption.value;
        const trigger = this.availableTriggersData.find(t => t.name === triggerName);
        
        const valueContainer = document.getElementById('trigger-value').parentElement;
        const label = valueContainer.querySelector('label');
        
        // Replace the input with appropriate field based on trigger type
        if (triggerType === 'Continuous') {
            // For continuous triggers, show min/max range fields
            const currentMin = document.getElementById('trigger-value-min')?.value || '';
            const currentMax = document.getElementById('trigger-value-max')?.value || '';
            
            let helpText = 'Specify min and/or max to define a range. Leave both empty to trigger on any value.';
            if (trigger && trigger.range) {
                const min = trigger.range.min;
                const max = trigger.range.max;
                if (min !== undefined && max !== undefined) {
                    helpText = `Valid range: ${min} to ${max}. Specify min and/or max for your trigger range.`;
                }
            }
            
            valueContainer.innerHTML = '';
            label.textContent = 'Trigger Value Range';
            valueContainer.appendChild(label);
            valueContainer.insertAdjacentHTML('beforeend', `
                <div class="range-inputs">
                    <div class="range-field">
                        <label for="trigger-value-min">Minimum (optional):</label>
                        <input type="number" id="trigger-value-min" step="any" placeholder="Min value" value="${currentMin}">
                    </div>
                    <div class="range-field">
                        <label for="trigger-value-max">Maximum (optional):</label>
                        <input type="number" id="trigger-value-max" step="any" placeholder="Max value" value="${currentMax}">
                    </div>
                </div>
                <div class="help-text">${helpText}</div>
            `);
            
            // Hide the old trigger-value field if it exists
            const oldField = document.getElementById('trigger-value');
            if (oldField) {
                oldField.style.display = 'none';
            }
            
        } else if (triggerType === 'On/Off' || (triggerValues && triggerValues.length > 0)) {
            // Create dropdown for discrete triggers
            const currentValue = document.getElementById('trigger-value')?.value || '';
            
            let selectHtml = '<select id="trigger-value" class="form-control">';
            selectHtml += '<option value="">Any value</option>';
            
            if (triggerType === 'On/Off') {
                selectHtml += '<option value="On">On</option>';
                selectHtml += '<option value="Off">Off</option>';
            } else {
                triggerValues.forEach(val => {
                    selectHtml += `<option value="${this.escapeHtml(val)}">${this.escapeHtml(val)}</option>`;
                });
            }
            
            selectHtml += '</select>';
            
            valueContainer.innerHTML = '';
            label.textContent = 'Trigger Value (optional)';
            valueContainer.appendChild(label);
            valueContainer.insertAdjacentHTML('beforeend', selectHtml);
            valueContainer.insertAdjacentHTML('beforeend', 
                '<div class="help-text">Leave empty to trigger on any value</div>');
            
            // Set the current value if it exists
            if (currentValue) {
                document.getElementById('trigger-value').value = currentValue;
            }
        } else {
            // Text input for other discrete triggers
            const currentValue = document.getElementById('trigger-value')?.value || '';
            
            let helpText = 'Leave empty to trigger on any value';
            if (trigger && trigger.range) {
                const min = trigger.range.min;
                const max = trigger.range.max;
                if (min !== undefined && max !== undefined) {
                    helpText = `Valid range: ${min} to ${max}. Leave empty for any value.`;
                }
            }
            
            valueContainer.innerHTML = '';
            label.textContent = 'Trigger Value (optional)';
            valueContainer.appendChild(label);
            valueContainer.insertAdjacentHTML('beforeend', 
                '<input type="text" id="trigger-value" placeholder="e.g., 0.5" value="' + currentValue + '">');
            valueContainer.insertAdjacentHTML('beforeend', 
                `<div class="help-text">${helpText}</div>`);
        }
    }

    async refreshMappings() {
        const refreshBtn = document.getElementById('refresh-mappings-btn');
        const originalText = refreshBtn.textContent;
        const originalBg = refreshBtn.style.backgroundColor;
        
        // Disable button and show loading state
        refreshBtn.disabled = true;
        refreshBtn.textContent = '⟳ Refreshing...';
        refreshBtn.style.backgroundColor = '#6c757d';
        refreshBtn.style.cursor = 'not-allowed';
        
        // Reload trigger data and mappings
        await this.loadAvailableTriggers();
        await this.loadTriggerMappings();
        await this.loadTriggerStatus();
        
        // Re-enable button after a brief delay
        setTimeout(() => {
            refreshBtn.disabled = false;
            refreshBtn.textContent = originalText;
            refreshBtn.style.backgroundColor = originalBg || '';
            refreshBtn.style.cursor = 'pointer';
            this.showMessage('Trigger mappings refreshed successfully', 'success');
        }, 500);
    }

    resetTriggerForm() {
        document.getElementById('triggerMappingForm').reset();
        document.getElementById('trigger-form-title').textContent = 'Add New Mapping';
        document.getElementById('trigger-mapping-id').value = '';
        document.getElementById('cancel-trigger-btn').style.display = 'none';
        document.querySelector('#triggerMappingForm button[type="submit"]').textContent = 'Add Mapping';
        
        // Reset trigger value field to text input
        // Need to handle both continuous (min/max fields) and discrete (single value field) triggers
        const valueField = document.getElementById('trigger-value');
        const minField = document.getElementById('trigger-value-min');
        const maxField = document.getElementById('trigger-value-max');
        
        let valueContainer;
        if (valueField) {
            valueContainer = valueField.parentElement;
        } else if (minField) {
            valueContainer = minField.closest('.form-group');
        } else if (maxField) {
            valueContainer = maxField.closest('.form-group');
        }
        
        if (valueContainer) {
            const label = valueContainer.querySelector('label');
            
            valueContainer.innerHTML = '';
            if (label) {
                label.textContent = 'Trigger Value (optional)';
                valueContainer.appendChild(label);
            } else {
                valueContainer.insertAdjacentHTML('beforeend', '<label for="trigger-value">Trigger Value (optional)</label>');
            }
            valueContainer.insertAdjacentHTML('beforeend', 
                '<input type="text" id="trigger-value" placeholder="e.g., On, Off, 5">');
            valueContainer.insertAdjacentHTML('beforeend',
                '<div class="help-text">Leave empty to trigger on any value</div>');
        }
        
        // Hide form and show button again
        document.getElementById('trigger-mapping-form-container').style.display = 'none';
        document.getElementById('add-trigger-mapping-btn').style.display = 'block';
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize the flame controller when the page loads
let flameController;
document.addEventListener('DOMContentLoaded', () => {
    flameController = new FlameController();
});
