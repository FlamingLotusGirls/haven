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
        this.loadPooferLayout();
        this.loadSceneStatus();
        // Poll scene status every 5 s so the header chip and warning banner
        // update automatically whenever the scene service changes the scene.
        setInterval(() => this.loadSceneStatus(), 5000);
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
                } else if (tabId === 'poofer-mappings') {
                    this.loadPooferMappings();
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
        document.getElementById('refreshScene').addEventListener('click', () => this.refreshScene());
        document.getElementById('refreshPatterns').addEventListener('click', () => this.loadPatterns());

        // Poofer fire/toggle buttons — delegated on the layout container so they
        // work even after loadPooferLayout() rebuilds the DOM from the server.
        // Fire buttons invoke the special '__PooferName' pattern for individual firing.
        const pooferLayout = document.getElementById('poofer-visual-layout');
        if (pooferLayout) {
            pooferLayout.addEventListener('click', (e) => {
                const fireBtn   = e.target.closest('.fire-btn');
                const toggleBtn = e.target.closest('.toggle-btn');
                if (fireBtn) {
                    const pooferId = '__' + fireBtn.getAttribute('data-poofer');
                    this.firePoofer(pooferId, fireBtn);
                } else if (toggleBtn) {
                    const pooferId = toggleBtn.getAttribute('data-poofer');
                    this.togglePoofer(pooferId, toggleBtn);
                }
            });
        }

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

        // Poofer mapping tab buttons
        document.getElementById('pm-add-btn').addEventListener('click', () => this.showPooferAddForm());
        document.getElementById('pm-reset-btn').addEventListener('click', () => this.resetPooferMappingsToDefaults());
        document.getElementById('pm-refresh-btn').addEventListener('click', () => this.loadPooferMappings());
        document.getElementById('pm-add-confirm-btn').addEventListener('click', () => this.submitNewPooferMapping());
        document.getElementById('pm-add-cancel-btn').addEventListener('click', () => this.hidePooferAddForm());

        // Submit add-form on Enter key inside its inputs
        ['pm-new-name', 'pm-new-address'].forEach(id => {
            document.getElementById(id).addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); this.submitNewPooferMapping(); }
                if (e.key === 'Escape') { e.preventDefault(); this.hidePooferAddForm(); }
            });
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

    async toggleRepeat(sequenceId, button) {
        const sequenceItem = button.closest('.sequence-item');
        const modeSelect    = sequenceItem.querySelector('.repeat-mode');
        const intervalInput = sequenceItem.querySelector('.repeat-interval');
        const statusIndicator = sequenceItem.querySelector('.repeat-status');

        if (this.repeatTimers.has(sequenceId)) {
            // ── Stop the server-side loop ──────────────────────────────────
            try {
                const response = await fetch(`${this.baseUrl}/flame/patterns/${sequenceId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'active=false'
                });
                if (response.ok) {
                    this.repeatTimers.delete(sequenceId);
                    button.style.backgroundColor = '';
                    button.style.color = '';
                    button.title = 'Toggle repeat';
                    statusIndicator.textContent = 'Stopped';
                    statusIndicator.className = 'repeat-status stopped';
                    this.showMessage(`Loop stopped for ${sequenceId}`, 'info');
                } else {
                    const txt = await response.text();
                    this.showMessage(`Failed to stop loop: ${txt}`, 'error');
                }
            } catch (error) {
                this.showMessage(`Error stopping loop: ${error.message}`, 'error');
            }
        } else {
            // ── Start a server-side loop ───────────────────────────────────
            const mode    = modeSelect ? modeSelect.value : 'interval';
            const seconds = parseFloat(intervalInput.value);

            if (isNaN(seconds) || seconds < 0) {
                this.showMessage('Time value must be a valid number ≥ 0', 'error');
                return;
            }

            // Convert seconds → milliseconds for the API
            const ms = Math.round(seconds * 1000);
            const param = mode === 'gap'
                ? `active=true&repeat_gap=${ms}`
                : `active=true&repeat_interval=${ms}`;

            try {
                button.disabled = true;
                const response = await fetch(`${this.baseUrl}/flame/patterns/${sequenceId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: param
                });

                if (response.ok) {
                    this.repeatTimers.set(sequenceId, true); // flag only — looping is server-side
                    button.style.backgroundColor = '#28a745';
                    button.style.color = 'white';
                    button.title = 'Stop loop';
                    const modeLabel = mode === 'gap'
                        ? `back-to-back +${seconds}s gap`
                        : `every ${seconds}s`;
                    statusIndicator.textContent = `Looping (${modeLabel})`;
                    statusIndicator.className = 'repeat-status repeating';
                    this.showMessage(`Loop started for ${sequenceId} — ${modeLabel}`, 'success');
                } else {
                    const txt = await response.text();
                    this.showMessage(`Failed to start loop: ${txt}`, 'error');
                }
            } catch (error) {
                this.showMessage(`Error starting loop: ${error.message}`, 'error');
            } finally {
                button.disabled = false;
            }
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

    // =========================================================================
    // Scene Display
    // =========================================================================

    /**
     * Fetch trigger-integration status (includes active_scene AND scene_unconfigured)
     * and update both the scene display pill and the unconfigured-scene banner.
     */
    async loadSceneStatus() {
        try {
            const response = await fetch(`${this.baseUrl}/trigger-integration/status`);
            if (response.ok) {
                const data = await response.json();
                this.displayScene(data.active_scene);
                this.updateUnconfiguredBanner(data.scene_unconfigured, data.active_scene);
            } else {
                this.displayScene(null, /*error=*/true);
                this.updateUnconfiguredBanner(false, null);
            }
        } catch (error) {
            this.displayScene(null, /*error=*/true);
            this.updateUnconfiguredBanner(false, null);
        }
    }

    /**
     * POST /api/refresh-scene — force the flame server to re-fetch from the
     * scene service right now, then update the scene display and banner.
     */
    async refreshScene() {
        const btn = document.getElementById('refreshScene');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '⏳ Refreshing…';

        try {
            const response = await fetch(`${this.baseUrl}/api/refresh-scene`, {
                method: 'POST',
            });

            if (response.ok) {
                const data = await response.json();
                if (data.refreshed) {
                    this.showMessage(`Scene refreshed: ${data.active_scene ?? '(none)'}`, 'success');
                } else {
                    this.showMessage('Scene service unreachable; showing last known scene', 'info');
                }
                // Reload full status so both the scene pill and the banner are updated.
                await this.loadSceneStatus();
            } else {
                this.displayScene(null, /*error=*/true);
                this.updateUnconfiguredBanner(false, null);
                this.showMessage('Failed to refresh scene', 'error');
            }
        } catch (error) {
            this.displayScene(null, /*error=*/true);
            this.updateUnconfiguredBanner(false, null);
            this.showMessage(`Error refreshing scene: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }

    /**
     * Show or hide the full-page unconfigured-scene warning banner.
     *
     * @param {boolean}     unconfigured  - true when scene_unconfigured flag is set
     * @param {string|null} sceneName     - the active scene name (used in the message)
     */
    updateUnconfiguredBanner(unconfigured, sceneName) {
        const banner = document.getElementById('unconfigured-scene-banner');
        const msgEl  = document.getElementById('unconfigured-scene-msg');
        if (!banner) return;

        if (unconfigured && sceneName && sceneName !== 'Unknown') {
            if (msgEl) {
                msgEl.textContent =
                    `The current scene "${sceneName}" has no trigger mappings configured.`;
            }
            banner.style.display = 'flex';
        } else {
            banner.style.display = 'none';
        }
    }

    /**
     * Update both the header scene chip and the System Status card pill.
     *
     * @param {string|null} scene  - scene name, "Unknown", or null
     * @param {boolean}     error  - true when the server is unreachable
     */
    displayScene(scene, error = false) {
        // Helper — applies the same text + class to any element with a scene-value role.
        const applyTo = (el, cardClass) => {
            if (!el) return;
            if (error) {
                el.textContent = 'Error';
                el.className = cardClass + ' scene-error';
            } else if (!scene || scene === 'Unknown') {
                el.textContent = scene || 'Unknown';
                el.className = cardClass + ' scene-unknown';
            } else {
                el.textContent = scene;
                el.className = cardClass + ' scene-known';
            }
        };

        // Header chip (uses hdr-label as base, colour modifier stacked on top)
        applyTo(document.getElementById('headerSceneValue'), 'hdr-label');
        // System Status card pill (keeps its own scene-value base)
        applyTo(document.getElementById('sceneValue'), 'scene-value');
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
        // Also refresh the scene status and unconfigured banner.
        await this.loadSceneStatus();
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
        globalStatus.textContent = data.globalState ? 'Playing' : 'Paused';
        globalStatus.className = 'hdr-label';
        
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

    async showPatternModal(pattern = null) {
        // Fetch the live poofer list from the server every time the modal opens.
        // If this fails we refuse to open the modal rather than silently showing
        // stale / hardcoded data.
        let pooferIds;
        try {
            const resp = await fetch(`${this.baseUrl}/flame/poofer-mappings`);
            if (!resp.ok) {
                throw new Error(`Server returned HTTP ${resp.status}`);
            }
            const mappings = await resp.json();
            pooferIds = Object.keys(mappings).sort();
            if (pooferIds.length === 0) {
                throw new Error('Poofer mappings list is empty');
            }
        } catch (err) {
            this.showMessage(
                `Cannot open pattern editor: failed to load poofer mappings — ${err.message}`,
                'error'
            );
            return;
        }

        // Store for use by addEventRow() and addEventRowIfValid()
        this.currentPooferIds = pooferIds;

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
        
        // If all existing events have poofers selected, add a new row.
        // this.currentPooferIds was populated by showPatternModal() from the server.
        this.addEventRow();
    }

    addEventRow(eventData = null) {
        const eventsContainer = document.getElementById('eventsContainer');
        const eventIndex = eventsContainer.children.length;

        // Use the live poofer IDs fetched from the server by showPatternModal().
        // this.currentPooferIds must be populated before this method is called.
        const validPooferIds = this.currentPooferIds;

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

    // =========================================================================
    // Poofer Mapping Functions
    // =========================================================================

    async loadPooferMappings() {
        const container = document.getElementById('pm-table-container');
        container.innerHTML = '<div class="loading">Loading poofer mappings…</div>';
        try {
            const response = await fetch(`${this.baseUrl}/flame/poofer-mappings`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            this.displayPooferMappings(data);
        } catch (error) {
            container.innerHTML = `<div class="error">Error loading poofer mappings: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    displayPooferMappings(mappings) {
        const container = document.getElementById('pm-table-container');
        const entries = Object.entries(mappings);

        if (entries.length === 0) {
            container.innerHTML = '<div class="empty-state">No poofer mappings defined.</div>';
            return;
        }

        let html = `
            <table class="pm-table">
                <thead>
                    <tr>
                        <th>Poofer Name</th>
                        <th>Address</th>
                        <th>Board (hex)</th>
                        <th>Channel</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
        `;

        for (const [name, address] of entries) {
            const board   = address.length >= 2 ? address.slice(0, 2).toUpperCase() : '??';
            const channel = address.length >= 3 ? address[2]                        : '?';
            html += `
                <tr id="pm-row-${this.escapeHtml(name)}" data-name="${this.escapeHtml(name)}">
                    <td class="pm-name-cell"><strong>${this.escapeHtml(name)}</strong></td>
                    <td class="pm-address-cell">
                        <span class="pm-address-text">${this.escapeHtml(address)}</span>
                        <input class="pm-address-input" type="text" value="${this.escapeHtml(address)}"
                               maxlength="3" size="4" style="display:none"
                               data-original="${this.escapeHtml(address)}">
                    </td>
                    <td class="pm-board-cell">${this.escapeHtml(board)}</td>
                    <td class="pm-channel-cell">${this.escapeHtml(channel)}</td>
                    <td class="pm-actions-cell">
                        <button class="btn btn-primary btn-sm pm-edit-btn"
                                onclick="flameController.startEditPooferMapping('${this.escapeHtml(name)}')">Edit</button>
                        <button class="btn btn-success btn-sm pm-save-btn" style="display:none"
                                onclick="flameController.savePooferMapping('${this.escapeHtml(name)}')">Save</button>
                        <button class="btn btn-secondary btn-sm pm-cancel-btn" style="display:none"
                                onclick="flameController.cancelEditPooferMapping('${this.escapeHtml(name)}')">Cancel</button>
                        <button class="btn btn-danger btn-sm pm-delete-btn"
                                onclick="flameController.deletePooferMapping('${this.escapeHtml(name)}')">Delete</button>
                    </td>
                </tr>
            `;
        }

        html += '</tbody></table>';
        container.innerHTML = html;

        // Allow pressing Enter/Escape inside address inputs
        container.querySelectorAll('.pm-address-input').forEach(input => {
            input.addEventListener('keydown', (e) => {
                const name = input.closest('tr').dataset.name;
                if (e.key === 'Enter')  { e.preventDefault(); this.savePooferMapping(name); }
                if (e.key === 'Escape') { e.preventDefault(); this.cancelEditPooferMapping(name); }
            });
        });
    }

    startEditPooferMapping(name) {
        const row = document.getElementById(`pm-row-${name}`);
        if (!row) return;

        const addrText  = row.querySelector('.pm-address-text');
        const addrInput = row.querySelector('.pm-address-input');
        const editBtn   = row.querySelector('.pm-edit-btn');
        const saveBtn   = row.querySelector('.pm-save-btn');
        const cancelBtn = row.querySelector('.pm-cancel-btn');
        const deleteBtn = row.querySelector('.pm-delete-btn');

        addrText.style.display  = 'none';
        addrInput.style.display = 'inline-block';
        addrInput.focus();
        addrInput.select();

        editBtn.style.display   = 'none';
        saveBtn.style.display   = 'inline-block';
        cancelBtn.style.display = 'inline-block';
        deleteBtn.style.display = 'none';
    }

    cancelEditPooferMapping(name) {
        const row = document.getElementById(`pm-row-${name}`);
        if (!row) return;

        const addrText  = row.querySelector('.pm-address-text');
        const addrInput = row.querySelector('.pm-address-input');
        const editBtn   = row.querySelector('.pm-edit-btn');
        const saveBtn   = row.querySelector('.pm-save-btn');
        const cancelBtn = row.querySelector('.pm-cancel-btn');
        const deleteBtn = row.querySelector('.pm-delete-btn');

        // Restore original value
        addrInput.value = addrInput.dataset.original;

        addrText.style.display  = 'inline';
        addrInput.style.display = 'none';

        editBtn.style.display   = 'inline-block';
        saveBtn.style.display   = 'none';
        cancelBtn.style.display = 'none';
        deleteBtn.style.display = 'inline-block';
    }

    async savePooferMapping(name) {
        const row = document.getElementById(`pm-row-${name}`);
        if (!row) return;

        const addrInput  = row.querySelector('.pm-address-input');
        const newAddress = addrInput.value.trim().toUpperCase();

        try {
            const formData = new FormData();
            formData.append('address', newAddress);

            const response = await fetch(
                `${this.baseUrl}/flame/poofer-mappings/${encodeURIComponent(name)}`,
                { method: 'PUT', body: formData }
            );

            if (response.ok) {
                this.showMessage(`Updated ${name} → ${newAddress}`, 'success');
                // Update the displayed text and board/channel cells in place
                const addrText    = row.querySelector('.pm-address-text');
                const boardCell   = row.querySelector('.pm-board-cell');
                const channelCell = row.querySelector('.pm-channel-cell');

                addrText.textContent    = newAddress;
                addrInput.dataset.original = newAddress;
                boardCell.textContent   = newAddress.slice(0, 2).toUpperCase();
                channelCell.textContent = newAddress[2] || '?';

                this.cancelEditPooferMapping(name); // restore view mode
            } else {
                const errorText = await response.text();
                this.showMessage(`Error: ${errorText}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error saving mapping: ${error.message}`, 'error');
        }
    }

    async deletePooferMapping(name) {
        if (!confirm(`Delete mapping for "${name}"?`)) return;

        try {
            const response = await fetch(
                `${this.baseUrl}/flame/poofer-mappings/${encodeURIComponent(name)}`,
                { method: 'DELETE' }
            );

            if (response.ok) {
                this.showMessage(`Deleted mapping for ${name}`, 'success');
                // Remove the row directly for snappy UX
                const row = document.getElementById(`pm-row-${name}`);
                if (row) row.remove();
            } else {
                const errorText = await response.text();
                this.showMessage(`Error: ${errorText}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error deleting mapping: ${error.message}`, 'error');
        }
    }

    showPooferAddForm() {
        document.getElementById('pm-add-form').style.display = 'block';
        document.getElementById('pm-add-btn').style.display = 'none';
        document.getElementById('pm-add-error').style.display = 'none';
        document.getElementById('pm-new-name').value = '';
        document.getElementById('pm-new-address').value = '';
        document.getElementById('pm-new-name').focus();
    }

    hidePooferAddForm() {
        document.getElementById('pm-add-form').style.display = 'none';
        document.getElementById('pm-add-btn').style.display = 'inline-block';
        document.getElementById('pm-add-error').style.display = 'none';
    }

    async submitNewPooferMapping() {
        const nameInput    = document.getElementById('pm-new-name');
        const addressInput = document.getElementById('pm-new-address');
        const errorDiv     = document.getElementById('pm-add-error');

        const name    = nameInput.value.trim();
        const address = addressInput.value.trim().toUpperCase();

        if (!name) {
            errorDiv.textContent = 'Poofer name is required.';
            errorDiv.style.display = 'block';
            nameInput.focus();
            return;
        }
        if (!address) {
            errorDiv.textContent = 'Address is required.';
            errorDiv.style.display = 'block';
            addressInput.focus();
            return;
        }

        try {
            const formData = new FormData();
            formData.append('name', name);
            formData.append('address', address);

            const response = await fetch(`${this.baseUrl}/flame/poofer-mappings`, {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                this.showMessage(`Added mapping: ${name} → ${address}`, 'success');
                this.hidePooferAddForm();
                this.loadPooferMappings(); // full refresh to show new row in sorted position
            } else {
                const errorText = await response.text();
                errorDiv.textContent = errorText;
                errorDiv.style.display = 'block';
            }
        } catch (error) {
            errorDiv.textContent = `Error: ${error.message}`;
            errorDiv.style.display = 'block';
        }
    }

    async resetPooferMappingsToDefaults() {
        if (!confirm('Reset ALL poofer mappings to built-in defaults? This will overwrite any custom mappings.')) return;

        try {
            const response = await fetch(`${this.baseUrl}/flame/poofer-mappings/reset-defaults`, {
                method: 'POST'
            });

            if (response.ok) {
                const data = await response.json();
                this.showMessage('Poofer mappings reset to defaults', 'success');
                this.displayPooferMappings(data);
            } else {
                const errorText = await response.text();
                this.showMessage(`Error resetting mappings: ${errorText}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error: ${error.message}`, 'error');
        }
    }

    // =========================================================================
    // Trigger Integration Functions 
    // =========================================================================

    /**
     * Fetch with a built-in AbortController timeout so a hung server can't
     * silently block the load path forever.
     *
     * @param {string} url
     * @param {RequestInit} [options]
     * @param {number} [timeoutMs=10000]
     * @returns {Promise<Response>}
     */
    async _fetchWithTimeout(url, options = {}, timeoutMs = 10000) {
        const controller = new AbortController();
        const tid = setTimeout(() => controller.abort(), timeoutMs);
        try {
            return await fetch(url, { ...options, signal: controller.signal });
        } finally {
            clearTimeout(tid);
        }
    }

    /** Entry point called when the user switches to the Triggers tab. */
    async loadTriggerIntegration() {
        // Immediately mark the selector so we can tell the function was called.
        const _sel = document.getElementById('trigger-scene-select');
        if (_sel) { _sel.disabled = true; }

        try { await this.loadTriggerStatus(); }
            catch (e) { console.error('loadTriggerStatus:', e); }

        try { await this.loadAvailableTriggers(); }
            catch (e) { console.error('loadAvailableTriggers:', e); }

        try { await this.loadAvailableSequencesForTriggers(); }
            catch (e) { console.error('loadAvailableSequencesForTriggers:', e); }

        try {
            await this._loadScenesAndMappings();  // builds scene selector + renders table
        } catch (e) {
            console.error('_loadScenesAndMappings:', e);
            // Always leave the selector in a usable state even on hard failure
            this._buildSceneSelector(this.availableScenesData   || [],
                                     this.configuredScenesData || [],
                                     null);
            this._renderSyncWarnings(this.availableScenesData   || [],
                                     this.configuredScenesData || []);
            this._renderMappingsForSelectedScene();
        }

        if (_sel) { _sel.disabled = false; }

        try { this.initTriggerForm(); }
            catch (e) { console.error('initTriggerForm:', e); }

        // Wire up the scene selector and action buttons (idempotent — guarded by dataset flag)
        const sceneSelect = document.getElementById('trigger-scene-select');
        if (sceneSelect && !sceneSelect.dataset.initialized) {
            sceneSelect.dataset.initialized = 'true';
            sceneSelect.addEventListener('change', () => {
                this._selectedScene = sceneSelect.value;
                this._renderMappingsForSelectedScene();
            });
        }
        const dupBtn = document.getElementById('duplicate-scene-btn');
        if (dupBtn && !dupBtn.dataset.initialized) {
            dupBtn.dataset.initialized = 'true';
            dupBtn.addEventListener('click', () => this.duplicateScene());
        }

        // Background poll every 2 minutes: refresh triggers + mappings silently
        if (this.triggerPollInterval) clearInterval(this.triggerPollInterval);
        this.triggerPollInterval = setInterval(async () => {
            await this.loadAvailableTriggers();
            try {
                const r = await fetch(`${this.baseUrl}/trigger-integration/mappings`);
                if (r.ok) {
                    const d = await r.json();
                    this._allMappings = d.mappings || [];
                    this._renderMappingsForSelectedScene();
                }
            } catch (_) {}
        }, 120000);
    }

    /**
     * Fetch scenes + all mappings, populate the scene selector, render the table.
     * Called on tab open and after duplicate/copy operations.
     * Always initialises instance variables so downstream code never sees undefined.
     */
    async _loadScenesAndMappings() {
        // Initialise to safe defaults so we never pass undefined to _buildSceneSelector
        // even when a fetch returns a non-200 status code (which doesn't throw).
        if (!Array.isArray(this.availableScenesData))   this.availableScenesData   = [];
        if (!Array.isArray(this.configuredScenesData)) this.configuredScenesData = [];
        if (!Array.isArray(this._allMappings))         this._allMappings         = [];

        try {
            const sceneResp = await this._fetchWithTimeout(
                `${this.baseUrl}/trigger-integration/scenes`);
            if (sceneResp.ok) {
                const md = await sceneResp.json();
                this.availableScenesData   = md.scenes             || [];
                this.activeSceneData       = md.active_scene       || null;
                this.configuredScenesData  = md.configured_scenes || [];
            } else {
                console.warn(`/trigger-integration/scenes returned ${sceneResp.status}`);
            }
        } catch (err) {
            console.warn('Could not reach /trigger-integration/scenes:', err.message || err);
        }

        try {
            const mapResp = await this._fetchWithTimeout(
                `${this.baseUrl}/trigger-integration/mappings`);
            if (mapResp.ok) {
                const md = await mapResp.json();
                this._allMappings = md.mappings || [];
            } else {
                console.warn(`/trigger-integration/mappings returned ${mapResp.status}`);
            }
        } catch (err) {
            console.warn('Could not reach /trigger-integration/mappings:', err.message || err);
        }

        this._buildSceneSelector(
            this.availableScenesData, this.configuredScenesData, this.activeSceneData);
        this._renderSyncWarnings(this.availableScenesData, this.configuredScenesData);
        this._renderMappingsForSelectedScene();
    }

    /**
     * Rebuild the scene selector dropdown.
     * Sources: scene-service scene list + flame configured-scenes list (union).
     * Options are colour-coded:
     *   default (black) — present in both scene service AND flame config
     *   red             — scene service only (flame config missing)
     *   blue            — flame config only (not in scene service, likely orphaned)
     */
    _buildSceneSelector(sceneServiceScenes, configuredScenes, defaultScene) {
        const select = document.getElementById('trigger-scene-select');
        if (!select) return;

        const msSet  = new Set(sceneServiceScenes  || []);
        const cfgSet = new Set(configuredScenes   || []);
        const allScenes = [...new Set([...msSet, ...cfgSet])].sort();

        const prev = this._selectedScene || select.value || '';
        select.innerHTML = '';

        if (allScenes.length === 0) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = 'No scenes defined';
            select.appendChild(opt);
            this._selectedScene = '';
            return;
        }

        allScenes.forEach(name => {
            const inMS  = msSet.has(name);
            const inCfg = cfgSet.has(name);
            const opt   = document.createElement('option');
            opt.value   = name;
            if (inMS && inCfg) {
                opt.textContent = name;                             // both — standard
            } else if (inMS && !inCfg) {
                opt.textContent  = `${name}  ⚠ (not configured)`;
                opt.style.color  = '#cc0000';                      // scene service only
            } else {
                opt.textContent  = `${name}  (not in scene service)`;
                opt.style.color  = '#0055cc';                      // flame config only
            }
            select.appendChild(opt);
        });

        const toSelect = (defaultScene && allScenes.includes(defaultScene)) ? defaultScene
                       : (prev && allScenes.includes(prev))                 ? prev
                       :                                                       allScenes[0];
        select.value = toSelect;
        this._selectedScene = toSelect;
    }

    /**
     * Render sync-warning banners between the scene selector and the status box.
     * Red  = scenes in scene service with no flame config.
     * Blue = scenes in flame config not present in scene service (orphaned).
     */
    _renderSyncWarnings(sceneServiceScenes, configuredScenes) {
        const container = document.getElementById('scene-sync-warnings');
        if (!container) return;

        const msSet  = new Set(sceneServiceScenes  || []);
        const cfgSet = new Set(configuredScenes   || []);

        const missingConfig  = [...msSet].filter(s => !cfgSet.has(s));
        const orphanedConfig = [...cfgSet].filter(s => !msSet.has(s));

        let html = '';
        if (missingConfig.length > 0) {
            const chips = missingConfig
                .map(s => `<span class="sync-scene-chip sync-chip-red">${this.escapeHtml(s)}</span>`)
                .join(' ');
            html += `<div class="sync-warning sync-warning-red">
                ⚠ <strong>${missingConfig.length} scene${missingConfig.length > 1 ? 's' : ''}
                from the scene service have no flame configuration:</strong> ${chips}
            </div>`;
        }
        if (orphanedConfig.length > 0) {
            const chips = orphanedConfig
                .map(s => `<span class="sync-scene-chip sync-chip-blue">${this.escapeHtml(s)}</span>`)
                .join(' ');
            html += `<div class="sync-warning sync-warning-blue">
                ℹ <strong>${orphanedConfig.length} flame config scene${orphanedConfig.length > 1 ? 's' : ''}
                not found in the scene service:</strong> ${chips}
            </div>`;
        }
        container.innerHTML = html;
    }

    /** Return the currently selected scene name (or null). */
    getSelectedScene() {
        const select = document.getElementById('trigger-scene-select');
        return (select && select.value) ? select.value : (this._selectedScene || null);
    }

    /**
     * Filter `this._allMappings` to the selected scene and render the table.
     * Three states:
     *   1. Scene not in configured_scenes → "not configured" message + Register button
     *   2. Scene configured but 0 mappings → empty-state with Delete Scene option
     *   3. Scene configured with mappings  → normal table
     */
    _renderMappingsForSelectedScene() {
        const scene = this.getSelectedScene();
        const title = document.getElementById('scene-mappings-title');
        if (title) title.textContent = scene ? `Mappings for "${scene}"` : 'Mappings';

        const container = document.getElementById('trigger-mappings-table');

        if (!scene) {
            container.innerHTML = '<div class="empty-state">No scenes available.</div>';
            return;
        }

        const cfgSet = new Set(this.configuredScenesData || []);

        if (!cfgSet.has(scene)) {
            // Not configured at all — dispatch is suppressed for this scene
            container.innerHTML = `
                <div class="scene-not-configured">
                    <p>⚠ This scene has <strong>no flame configuration</strong>.</p>
                    <p>All trigger dispatch is disabled while the flame service has no
                       configuration for this scene. Click below to register it — you can
                       add fire mappings later, or leave it as a quiet scene with no effects.</p>
                    <button class="btn btn-primary"
                            onclick="flameController.registerCurrentScene()">
                        Register Scene (Create Empty Config)
                    </button>
                </div>`;
            return;
        }

        const sceneMappings = (this._allMappings || []).filter(m => m.scene === scene);
        this.displayTriggerMappings(sceneMappings, scene);
    }

    /**
     * Register the currently-selected scene in the flame service (empty config).
     * Called from the "Register Scene" button in the not-configured state.
     */
    async registerCurrentScene() {
        const scene = this.getSelectedScene();
        if (!scene) return;
        try {
            const fd = new FormData();
            fd.append('scene_name', scene);
            const response = await fetch(
                `${this.baseUrl}/trigger-integration/scenes`, { method: 'POST', body: fd });
            if (response.ok) {
                this.showMessage(`Scene "${scene}" registered`, 'success');
                await this._loadScenesAndMappings();
            } else {
                this.showMessage(`Failed to register scene: ${await response.text()}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error: ${error.message}`, 'error');
        }
    }

    async loadTriggerStatus() {
        try {
            const response = await this._fetchWithTimeout(
                `${this.baseUrl}/trigger-integration/status`);
            const status = await response.json();
            const statusBox = document.getElementById('trigger-status-box');
            statusBox.className = status.registered ? 'success' : 'error';
            statusBox.innerHTML = `
                <strong>Integration Status:</strong><br>
                Connected to Trigger Server: <strong>${status.registered ? 'Yes ✓' : 'No ✗'}</strong><br>
                Trigger Server: ${status.trigger_server_url} &nbsp;|&nbsp;
                Listen Port: ${status.listen_port} &nbsp;|&nbsp;
                Active Mappings: ${status.mapping_count} &nbsp;|&nbsp;
                Available Triggers: ${status.available_triggers_count}
            `;
        } catch (_) {
            const statusBox = document.getElementById('trigger-status-box');
            statusBox.className = 'error';
            statusBox.innerHTML = '<strong>Error:</strong> Cannot connect to trigger integration service';
        }
    }

    async loadAvailableTriggers() {
        try {
            const response = await this._fetchWithTimeout(
                `${this.baseUrl}/trigger-integration/triggers`);
            const data = await response.json();
            this.availableTriggersData = data.triggers || [];

            const select = document.getElementById('trigger-name');
            select.innerHTML = '<option value="">Select a trigger...</option>';

            this.availableTriggersData.forEach(trigger => {
                const values = trigger.range && trigger.range.values ? trigger.range.values : [];
                const option = document.createElement('option');
                option.value = trigger.name;
                option.textContent = trigger.device_status === 'offline'
                    ? `${trigger.name} (${trigger.type}) [OFFLINE]`
                    : `${trigger.name} (${trigger.type})`;
                option.dataset.triggerType   = trigger.type;
                option.dataset.triggerValues = JSON.stringify(values);
                option.dataset.deviceStatus  = trigger.device_status || 'unknown';
                select.appendChild(option);
            });

            select.addEventListener('change', () => this.updateTriggerValueField());
        } catch (error) {
            console.error('Error loading triggers:', error);
        }
    }

    async loadAvailableSequencesForTriggers() {
        try {
            const response = await this._fetchWithTimeout(
                `${this.baseUrl}/flame/patterns`);
            const patterns = await response.json();
            this.availablePatternsData = patterns;

            const select = document.getElementById('flame-sequence');
            select.innerHTML = '<option value="">Select a flame sequence...</option>';
            patterns.forEach(pattern => {
                const option = document.createElement('option');
                option.value = pattern.name;
                option.textContent = pattern.display_name || pattern.name;
                select.appendChild(option);
            });
        } catch (error) {
            console.error('Error loading sequences:', error);
        }
    }

    /** Fetch all mappings, cache them, and re-render the current scene's table. */
    async loadTriggerMappings() {
        try {
            const response = await fetch(`${this.baseUrl}/trigger-integration/mappings`);
            if (response.ok) {
                const data = await response.json();
                this._allMappings = data.mappings || [];
            }
        } catch (error) {
            console.error('Error loading mappings:', error);
            document.getElementById('trigger-mappings-table').innerHTML =
                '<div class="empty-state">Error loading mappings</div>';
            return;
        }
        this._renderMappingsForSelectedScene();
    }

    /**
     * Render `mappings` (already filtered to one scene) into the table.
     * No "Scenes" column — the scene context is already clear from the selector.
     */
    displayTriggerMappings(mappings, scene) {
        const container = document.getElementById('trigger-mappings-table');

        if (mappings.length === 0) {
            container.innerHTML = `<div class="empty-state">No mappings configured for
                "<strong>${this.escapeHtml(scene || '')}</strong>" yet.<br>
                Click <strong>+ Add Mapping for this Scene</strong> above to create the first one.</div>`;
            return;
        }

        let html = '<table><thead><tr>'
            + '<th>Trigger</th><th>Value</th><th>Flame Sequence</th>'
            + '<th>Override</th><th>Actions</th>'
            + '</tr></thead><tbody>';

        mappings.forEach(mapping => {
            const trigger = this.availableTriggersData?.find(t => t.name === mapping.trigger_name);
            let triggerDisplay;
            if (!trigger) {
                triggerDisplay = `${this.escapeHtml(mapping.trigger_name)} <em style="color:#dc3545;">[Not Found]</em>`;
            } else if (trigger.device_status === 'offline') {
                triggerDisplay = `${this.escapeHtml(mapping.trigger_name)} <em style="color:#999;">[Offline]</em>`;
            } else {
                triggerDisplay = this.escapeHtml(mapping.trigger_name);
            }

            let valueDisplay;
            if (mapping.trigger_value_min !== undefined && mapping.trigger_value_max !== undefined) {
                valueDisplay = `${mapping.trigger_value_min} – ${mapping.trigger_value_max}`;
            } else if (mapping.trigger_value_min !== undefined) {
                valueDisplay = `≥ ${mapping.trigger_value_min}`;
            } else if (mapping.trigger_value_max !== undefined) {
                valueDisplay = `≤ ${mapping.trigger_value_max}`;
            } else if (mapping.trigger_value) {
                valueDisplay = this.escapeHtml(mapping.trigger_value);
            } else {
                valueDisplay = '<em>any</em>';
            }

            let seqDisplay = this.escapeHtml(mapping.flame_sequence);
            if (this.availablePatternsData) {
                const pat = this.availablePatternsData.find(p => p.name === mapping.flame_sequence);
                if (pat && pat.display_name) seqDisplay = this.escapeHtml(pat.display_name);
            }

            html += `<tr>`
                + `<td>${triggerDisplay}</td>`
                + `<td>${valueDisplay}</td>`
                + `<td>${seqDisplay}</td>`
                + `<td>${mapping.allow_override ? 'Yes' : 'No'}</td>`
                + `<td>`
                + `<button class="btn btn-primary btn-sm" onclick="flameController.editTriggerMapping(${mapping.id})">Edit</button>`
                + `<button class="btn btn-danger btn-sm" onclick="flameController.deleteTriggerMapping(${mapping.id})">Delete</button>`
                + `</td></tr>`;
        });

        html += '</tbody></table>';
        container.innerHTML = html;
    }

    initTriggerForm() {
        const form = document.getElementById('triggerMappingForm');
        if (form && !form.dataset.initialized) {
            form.dataset.initialized = 'true';
            form.addEventListener('submit', (e) => this.saveTriggerMapping(e));

            document.getElementById('cancel-trigger-btn')
                ?.addEventListener('click', () => this.resetTriggerForm());

            const addBtn = document.getElementById('add-trigger-mapping-btn');
            if (addBtn && !addBtn.dataset.initialized) {
                addBtn.dataset.initialized = 'true';
                addBtn.addEventListener('click', () => {
                    const badge = document.getElementById('trigger-form-scene');
                    if (badge) badge.textContent = this.getSelectedScene() || '—';
                    document.getElementById('trigger-form-title').textContent = 'Add New Mapping';
                    document.getElementById('trigger-mapping-id').value = '';
                    document.getElementById('trigger-mapping-form-container').style.display = 'block';
                    document.getElementById('cancel-trigger-btn').style.display = 'inline-block';
                    addBtn.style.display = 'none';
                });
            }
        }
    }

    async saveTriggerMapping(event) {
        event.preventDefault();

        const mappingId    = document.getElementById('trigger-mapping-id').value;
        const triggerName  = document.getElementById('trigger-name').value;
        const flameSeq     = document.getElementById('flame-sequence').value;
        const allowOverride = document.getElementById('allow-override').checked;

        // Scene is whatever was shown in the form badge when the form was opened
        const sceneBadge   = document.getElementById('trigger-form-scene');
        const scene = (sceneBadge && sceneBadge.textContent && sceneBadge.textContent !== '—')
            ? sceneBadge.textContent
            : this.getSelectedScene();

        if (!scene) {
            this.showMessage('No scene selected — please select a scene first', 'error');
            return;
        }

        const triggerSelect   = document.getElementById('trigger-name');
        const selectedOption  = triggerSelect.options[triggerSelect.selectedIndex];
        const triggerType     = selectedOption?.dataset.triggerType;

        const formData = new FormData();
        formData.append('trigger_name',   triggerName);
        formData.append('flame_sequence', flameSeq);
        formData.append('allow_override', allowOverride ? 'true' : 'false');
        formData.append('scene', scene);

        if (triggerType === 'Continuous') {
            const minField = document.getElementById('trigger-value-min');
            const maxField = document.getElementById('trigger-value-max');
            if (minField && minField.value !== '') formData.append('trigger_value_min', minField.value);
            if (maxField && maxField.value !== '') formData.append('trigger_value_max', maxField.value);
        } else {
            formData.append('trigger_value', document.getElementById('trigger-value')?.value || '');
        }

        try {
            const url    = mappingId
                ? `${this.baseUrl}/trigger-integration/mappings/${mappingId}`
                : `${this.baseUrl}/trigger-integration/mappings`;
            const method = mappingId ? 'PUT' : 'POST';

            const response = await fetch(url, { method, body: formData });
            if (response.ok) {
                this.showMessage(mappingId ? 'Mapping updated!' : 'Mapping created!', 'success');
                this.resetTriggerForm();
                // Re-fetch both configured_scenes AND mappings so the "not configured"
                // block disappears immediately after the first mapping is saved.
                await this._loadScenesAndMappings();
                await this.loadTriggerStatus();
            } else {
                this.showMessage(`Error: ${await response.text()}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error: ${error.message}`, 'error');
        }
    }

    async editTriggerMapping(id) {
        try {
            const response = await fetch(`${this.baseUrl}/trigger-integration/mappings/${id}`);
            const mapping  = await response.json();

            document.getElementById('trigger-mapping-form-container').style.display = 'block';
            document.getElementById('add-trigger-mapping-btn').style.display = 'none';
            document.getElementById('trigger-form-title').textContent = 'Edit Mapping';
            document.getElementById('trigger-mapping-id').value = mapping.id;

            // Scene badge — use mapping.scene or current scene
            const scene = mapping.scene || this.getSelectedScene();
            const badge = document.getElementById('trigger-form-scene');
            if (badge) badge.textContent = scene || '—';

            document.getElementById('trigger-name').value = mapping.trigger_name;
            this.updateTriggerValueField();

            const trigType = document.getElementById('trigger-name')
                .options[document.getElementById('trigger-name').selectedIndex]
                ?.dataset.triggerType;

            if (trigType === 'Continuous') {
                const minF = document.getElementById('trigger-value-min');
                const maxF = document.getElementById('trigger-value-max');
                if (minF) minF.value = mapping.trigger_value_min || '';
                if (maxF) maxF.value = mapping.trigger_value_max || '';
            } else {
                const vf = document.getElementById('trigger-value');
                if (vf) vf.value = mapping.trigger_value || '';
            }

            document.getElementById('flame-sequence').value = mapping.flame_sequence;
            document.getElementById('allow-override').checked = mapping.allow_override;
            document.getElementById('cancel-trigger-btn').style.display = 'inline-block';
            document.querySelector('#triggerMappingForm button[type="submit"]').textContent = 'Update Mapping';
            document.getElementById('trigger-form-title').scrollIntoView({ behavior: 'smooth' });
        } catch (error) {
            this.showMessage(`Error loading mapping: ${error.message}`, 'error');
        }
    }

    async deleteTriggerMapping(id) {
        if (!confirm('Are you sure you want to delete this mapping?')) return;
        try {
            const response = await fetch(
                `${this.baseUrl}/trigger-integration/mappings/${id}`, { method: 'DELETE' });
            if (response.ok) {
                this.showMessage('Mapping deleted', 'success');
                await this.loadTriggerMappings();
                await this.loadTriggerStatus();
            } else {
                this.showMessage('Error deleting mapping', 'error');
            }
        } catch (error) {
            this.showMessage(`Error: ${error.message}`, 'error');
        }
    }

    updateTriggerValueField() {
        const triggerSelect  = document.getElementById('trigger-name');
        const selectedOption = triggerSelect.options[triggerSelect.selectedIndex];
        if (!selectedOption || !selectedOption.value) return;

        const triggerType   = selectedOption.dataset.triggerType;
        const triggerValues = JSON.parse(selectedOption.dataset.triggerValues || '[]');
        const trigger       = this.availableTriggersData.find(t => t.name === selectedOption.value);

        const valueContainer = document.getElementById('trigger-value').parentElement;
        const label          = valueContainer.querySelector('label');

        if (triggerType === 'Continuous') {
            const currentMin = document.getElementById('trigger-value-min')?.value || '';
            const currentMax = document.getElementById('trigger-value-max')?.value || '';
            let helpText = 'Specify min and/or max to define a range.';
            if (trigger?.range?.min !== undefined && trigger?.range?.max !== undefined) {
                helpText = `Valid range: ${trigger.range.min} to ${trigger.range.max}. Specify min and/or max.`;
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
            const oldField = document.getElementById('trigger-value');
            if (oldField) oldField.style.display = 'none';

        } else if (triggerType === 'On/Off' || triggerValues.length > 0) {
            const currentValue = document.getElementById('trigger-value')?.value || '';
            let selectHtml = '<select id="trigger-value" class="form-control"><option value="">Any value</option>';
            if (triggerType === 'On/Off') {
                selectHtml += '<option value="On">On</option><option value="Off">Off</option>';
            } else {
                triggerValues.forEach(v => {
                    selectHtml += `<option value="${this.escapeHtml(v)}">${this.escapeHtml(v)}</option>`;
                });
            }
            selectHtml += '</select>';
            valueContainer.innerHTML = '';
            label.textContent = 'Trigger Value (optional)';
            valueContainer.appendChild(label);
            valueContainer.insertAdjacentHTML('beforeend', selectHtml);
            valueContainer.insertAdjacentHTML('beforeend',
                '<div class="help-text">Leave empty to trigger on any value</div>');
            if (currentValue) document.getElementById('trigger-value').value = currentValue;

        } else {
            const currentValue = document.getElementById('trigger-value')?.value || '';
            let helpText = 'Leave empty to trigger on any value';
            if (trigger?.range?.min !== undefined && trigger?.range?.max !== undefined) {
                helpText = `Valid range: ${trigger.range.min} to ${trigger.range.max}. Leave empty for any value.`;
            }
            valueContainer.innerHTML = '';
            label.textContent = 'Trigger Value (optional)';
            valueContainer.appendChild(label);
            valueContainer.insertAdjacentHTML('beforeend',
                `<input type="text" id="trigger-value" placeholder="e.g., 0.5" value="${currentValue}">`);
            valueContainer.insertAdjacentHTML('beforeend',
                `<div class="help-text">${helpText}</div>`);
        }
    }

    async refreshMappings() {
        const btn = document.getElementById('refresh-mappings-btn');
        const orig = btn ? btn.textContent : '';
        if (btn) { btn.disabled = true; btn.textContent = '⟳ Refreshing...'; }
        await this.loadAvailableTriggers();
        await this.loadTriggerMappings();
        await this.loadTriggerStatus();
        setTimeout(() => {
            if (btn) { btn.disabled = false; btn.textContent = orig; }
            this.showMessage('Trigger mappings refreshed', 'success');
        }, 400);
    }

    resetTriggerForm() {
        document.getElementById('triggerMappingForm').reset();
        document.getElementById('trigger-form-title').textContent = 'Add New Mapping';
        document.getElementById('trigger-mapping-id').value = '';
        document.getElementById('cancel-trigger-btn').style.display = 'none';
        document.querySelector('#triggerMappingForm button[type="submit"]').textContent = 'Save Mapping';

        const badge = document.getElementById('trigger-form-scene');
        if (badge) badge.textContent = this.getSelectedScene() || '—';

        // Restore trigger-value field to a plain text input
        const valueField = document.getElementById('trigger-value');
        const minField   = document.getElementById('trigger-value-min');
        const maxField   = document.getElementById('trigger-value-max');
        let valueContainer = valueField?.parentElement
            ?? minField?.closest('.form-group')
            ?? maxField?.closest('.form-group');
        if (valueContainer) {
            const label = valueContainer.querySelector('label');
            valueContainer.innerHTML = '';
            if (label) { label.textContent = 'Trigger Value (optional)'; valueContainer.appendChild(label); }
            else valueContainer.insertAdjacentHTML('beforeend', '<label for="trigger-value">Trigger Value (optional)</label>');
            valueContainer.insertAdjacentHTML('beforeend',
                '<input type="text" id="trigger-value" placeholder="e.g., On, Off, 5">');
            valueContainer.insertAdjacentHTML('beforeend',
                '<div class="help-text">Leave empty to trigger on any value</div>');
        }

        document.getElementById('trigger-mapping-form-container').style.display = 'none';
        document.getElementById('add-trigger-mapping-btn').style.display = 'block';
    }

    /**
     * Duplicate all mappings for the currently selected scene to a new scene name.
     * Prompts the user for the target name via window.prompt.
     */
    async duplicateScene() {
        const fromScene = this.getSelectedScene();
        if (!fromScene) { this.showMessage('Select a scene to duplicate', 'error'); return; }

        const raw = window.prompt(`Duplicate all mappings from "${fromScene}" to a new scene name:`, '');
        if (!raw || !raw.trim()) return;
        const toScene = raw.trim();
        if (toScene === fromScene) {
            this.showMessage('New scene name must differ from the source', 'error');
            return;
        }

        const btn  = document.getElementById('duplicate-scene-btn');
        const orig = btn?.textContent;
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Duplicating…'; }

        try {
            const fd = new FormData();
            fd.append('from_scene', fromScene);
            fd.append('to_scene',   toScene);
            const response = await fetch(
                `${this.baseUrl}/trigger-integration/mappings/copy-scene`,
                { method: 'POST', body: fd }
            );
            if (response.ok) {
                const data = await response.json();
                if (data.copied_count > 0) {
                    this.showMessage(
                        `Duplicated ${data.copied_count} mapping${data.copied_count !== 1 ? 's' : ''} to "${toScene}"`,
                        'success');
                    this._selectedScene = toScene;       // switch to the new scene
                    await this._loadScenesAndMappings();
                } else {
                    this.showMessage(`No mappings found for "${fromScene}" — nothing to duplicate.`, 'info');
                }
            } else {
                this.showMessage(`Duplicate failed: ${await response.text()}`, 'error');
            }
        } catch (error) {
            this.showMessage(`Error: ${error.message}`, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = orig; }
        }
    }


    // =========================================================================
    // Poofer Visual Layout
    // =========================================================================

    /**
     * Fetch /flame/poofer-mappings and build the Individual Poofers section
     * dynamically. Poofers are bucketed by their first letter:
     *   C → Cockatoo, O → Osprey, M → Magpie, P → Perch, anything else → Other.
     *
     * Display label: if the name contains an underscore (e.g. C_HAIR1) the part
     * after the first underscore is used (HAIR1); otherwise the full name is shown.
     *
     * Fire buttons invoke the '__PooferName' system pattern; toggle buttons call
     * the enable/disable API. Both are handled via event delegation set up in
     * bindEvents() so this method can safely replace innerHTML without re-binding.
     */
    async loadPooferLayout() {
        const container = document.getElementById('poofer-visual-layout');
        if (!container) return;

        let mappings;
        try {
            const resp = await fetch(`${this.baseUrl}/flame/poofer-mappings`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            mappings = await resp.json();
        } catch (err) {
            container.innerHTML =
                `<div class="error">Failed to load poofer layout: ${this.escapeHtml(err.message)}</div>`;
            return;
        }

        // Section definitions — order controls display order.
        const SECTIONS = [
            { prefix: 'C', label: '🦜 Cockatoo', cssClass: 'cockatoo-group' },
            { prefix: 'O', label: '🦅 Osprey',   cssClass: 'osprey-group'   },
            { prefix: 'M', label: '🐦‍⬛ Magpie',  cssClass: 'magpie-group'   },
            { prefix: 'P', label: '🪶 Perch',    cssClass: 'perch-group'    },
        ];

        // Group poofer names by their first letter (case-insensitive).
        const groups = {};
        SECTIONS.forEach(s => { groups[s.prefix] = []; });
        groups['_other'] = [];

        Object.keys(mappings).sort().forEach(name => {
            const key = name[0].toUpperCase();
            if (Object.prototype.hasOwnProperty.call(groups, key)) {
                groups[key].push(name);
            } else {
                groups['_other'].push(name);
            }
        });

        // Label to display inside each poofer card:
        // strip the leading 'PREFIX_' portion if an underscore is present.
        const pooferLabel = name => {
            const idx = name.indexOf('_');
            return idx !== -1 ? name.slice(idx + 1) : name;
        };

        // Build one poofer-item card (matching the CSS structure used by styles.css).
        const buildItem = name => `
            <div class="poofer-item" data-poofer="${name}">
                <div class="fire-icon">🔥</div>
                <span class="poofer-label">${this.escapeHtml(pooferLabel(name))}</span>
                <div class="poofer-controls">
                    <button class="fire-btn btn-fire" data-poofer="${name}">🔥 Fire</button>
                    <button class="toggle-btn" data-poofer="${name}">Disable</button>
                    <span class="status-dot"></span>
                </div>
            </div>`;

        let html = '<div class="sculpture-layout">';

        SECTIONS.forEach(({ prefix, label, cssClass }) => {
            const poofers = groups[prefix];
            if (poofers.length === 0) return;
            html += `<div class="poofer-group ${cssClass}">`;
            html += `<h3>${label}</h3>`;
            html += `<div class="poofer-grid">`;
            poofers.forEach(name => { html += buildItem(name); });
            html += `</div></div>`;
        });

        if (groups['_other'].length > 0) {
            html += `<div class="poofer-group other-group"><h3>🔧 Other</h3>`;
            html += `<div class="poofer-grid">`;
            groups['_other'].forEach(name => { html += buildItem(name); });
            html += `</div></div>`;
        }

        html += '</div>';
        container.innerHTML = html;
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
