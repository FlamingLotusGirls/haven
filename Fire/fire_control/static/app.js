// Flame Control Dashboard JavaScript
class FlameController {
    constructor() {
        this.baseUrl = window.location.origin;
        this.init();
    }

    init() {
        this.bindEvents();
        this.loadSystemStatus();
        this.loadPatterns();
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

        // Pattern management
        document.getElementById('addPatternBtn').addEventListener('click', () => this.showPatternModal());
   
        // Modal close buttons
        document.querySelectorAll('.close').forEach(closeBtn => {
            closeBtn.addEventListener('click', (e) => {
                e.target.closest('.modal').style.display = 'none';
            });
        });

        // Close modals when clicking outside
        window.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal')) {
                e.target.style.display = 'none';
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
        globalStatus.textContent = data.globalState ? 'Playing' : 'Paused';
        globalStatus.className = `status-indicator ${data.globalState ? 'enabled' : 'disabled'}`;
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
        const patternsHtml = patterns.map(pattern => `
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
                    <button class="btn btn-sm btn-danger" onclick="flameController.deletePattern('${pattern.name}')">
                        Delete
                    </button>
                </div>
            </div>
        `).join('');
        
        document.getElementById('patternsContainer').innerHTML = patternsHtml || '<div class="info">No patterns found</div>';
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
        const dataInput = document.getElementById('patternData');

        if (pattern) {
            title.textContent = 'Edit Pattern';
            nameInput.value = pattern.name;
            dataInput.value = JSON.stringify(pattern, null, 2);
        } else {
            title.textContent = 'Add New Pattern';
            nameInput.value = '';
            dataInput.value = '{\n  "name": "",\n  "events": []\n}';
        }

        modal.style.display = 'block';
    }

    hidePatternModal() {
        document.getElementById('patternModal').style.display = 'none';
    }

    async savePattern(event) {
        event.preventDefault();
        
        const patternData = document.getElementById('patternData').value;
        
        try {
            const pattern = JSON.parse(patternData);
            
            const response = await fetch(`${this.baseUrl}/flame/patterns`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `patternData=${encodeURIComponent(patternData)}`
            });

            if (response.ok) {
                this.showMessage(`Pattern ${pattern.name} saved`, 'success');
                this.hidePatternModal();
                this.loadPatterns();
            } else {
                this.showMessage('Failed to save pattern', 'error');
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
}

// Initialize the flame controller when the page loads
let flameController;
document.addEventListener('DOMContentLoaded', () => {
    flameController = new FlameController();
});
