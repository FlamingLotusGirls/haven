// Global data storage
let channelsData = [];
let patternsData = {
    sequences: {},
    patterns: {},
    pattern_mappings: {}
};

let currentEditingSequence = null;
let currentEditingPattern = null;
let hasUnsavedChanges = false;

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    loadAllData();
});

// Utility functions
function showStatus(message, isError = false) {
    const statusDiv = document.getElementById('status');
    statusDiv.innerHTML = `<div class="status ${isError ? 'error' : 'success'}">${message}</div>`;
    setTimeout(() => {
        statusDiv.innerHTML = '';
    }, 3000);
}

function clearInputs(...ids) {
    ids.forEach(id => {
        const element = document.getElementById(id);
        if (element) element.value = '';
    });
}

function markUnsavedChanges() {
    hasUnsavedChanges = true;
    updateSaveButtonText();
}

function clearUnsavedChanges() {
    hasUnsavedChanges = false;
    updateSaveButtonText();
}

function updateSaveButtonText() {
    const saveButton = document.querySelector('button[onclick="saveAllData()"]');
    if (saveButton) {
        if (hasUnsavedChanges) {
            saveButton.innerHTML = '💾 Save All Changes *';
            saveButton.style.backgroundColor = '#dc3545';
            saveButton.style.animation = 'pulse 2s infinite';
        } else {
            saveButton.innerHTML = '💾 Save All Changes';
            saveButton.style.backgroundColor = '#ff6b35';
            saveButton.style.animation = '';
        }
    }
}

// API functions
async function loadAllData() {
    try {
        // Load channels
        const channelsResponse = await fetch('/api/channels');
        channelsData = await channelsResponse.json();
        
        // Load patterns
        const patternsResponse = await fetch('/api/patterns');
        patternsData = await patternsResponse.json();
        
        // Ensure patterns data has proper structure
        if (!patternsData.sequences) patternsData.sequences = {};
        if (!patternsData.patterns) patternsData.patterns = {};
        if (!patternsData.pattern_mappings) patternsData.pattern_mappings = {};
        
        updateAllTables();
        clearUnsavedChanges();
        showStatus('Data loaded successfully');
    } catch (error) {
        showStatus('Error loading data: ' + error.message, true);
    }
}

async function saveAllData() {
    try {
        // Save channels
        await fetch('/api/channels', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(channelsData)
        });
        
        // Save patterns
        await fetch('/api/patterns', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(patternsData)
        });
        
        clearUnsavedChanges();
        showStatus('All data saved successfully');
    } catch (error) {
        showStatus('Error saving data: ' + error.message, true);
    }
}

// Channel mapping functions
function addChannelMapping() {
    const channelIndexStr = document.getElementById('channelIndex').value;
    const solenoidName = document.getElementById('solenoidName').value.trim();
    
    if (!channelIndexStr) {
        showStatus('Please select a channel index', true);
        return;
    }
    
    const channelIndex = parseInt(channelIndexStr);
    
    if (!solenoidName) {
        showStatus('Please enter a solenoid name', true);
        return;
    }
    
    // Check if channel index already exists
    const existingIndex = channelsData.findIndex(item => Array.isArray(item) ? item[0] === channelIndex : item.channel === channelIndex);
    if (existingIndex !== -1) {
        showStatus('Channel index already mapped', true);
        return;
    }
    
    // Add new mapping - using array format as specified in config
    channelsData.push([channelIndex, solenoidName]);
    updateChannelTable();
    clearInputs('solenoidName');
    document.getElementById('channelIndex').value = '';
    markUnsavedChanges();
    showStatus('Channel mapping added');
}

function removeChannelMapping(index) {
    channelsData.splice(index, 1);
    updateChannelTable();
    markUnsavedChanges();
    showStatus('Channel mapping removed');
}

function updateChannelTable() {
    const tbody = document.getElementById('channelTableBody');
    tbody.innerHTML = '';
    
    channelsData.forEach((mapping, index) => {
        const [channelIndex, solenoidName] = mapping;
        const row = tbody.insertRow();
        row.innerHTML = `
            <td>${channelIndex}</td>
            <td id="channelName-${index}">${solenoidName}</td>
            <td>
                <button onclick="editChannelName(${index})">Edit</button>
                <button class="danger" onclick="removeChannelMapping(${index})">Remove</button>
            </td>
        `;
    });
}

function editChannelName(index) {
    const nameCell = document.getElementById(`channelName-${index}`);
    const currentName = channelsData[index][1];
    
    // Replace the cell content with an input field
    nameCell.innerHTML = `
        <input type="text" id="editName-${index}" value="${currentName}" style="width: 150px;">
        <button onclick="saveChannelName(${index})" style="padding: 4px 8px; margin-left: 5px;">Save</button>
        <button onclick="cancelChannelEdit(${index})" style="padding: 4px 8px; margin-left: 5px;">Cancel</button>
    `;
    
    // Focus on the input field
    document.getElementById(`editName-${index}`).focus();
}

function saveChannelName(index) {
    const newName = document.getElementById(`editName-${index}`).value.trim();
    
    if (!newName) {
        showStatus('Please enter a solenoid name', true);
        return;
    }
    
    // Update the data
    channelsData[index][1] = newName;
    
    // Refresh the table
    updateChannelTable();
    markUnsavedChanges();
    showStatus('Channel name updated');
}

function cancelChannelEdit(index) {
    // Simply refresh the table to cancel the edit
    updateChannelTable();
}

// Sequence functions
function createNewSequence() {
    const sequenceName = document.getElementById('sequenceName').value.trim();
    
    if (!sequenceName) {
        showStatus('Please enter a sequence name', true);
        return;
    }
    
    if (patternsData.sequences[sequenceName]) {
        showStatus('Sequence already exists', true);
        return;
    }
    
    currentEditingSequence = sequenceName;
    patternsData.sequences[sequenceName] = [];
    
    showSequenceEditor(sequenceName, []);
    clearInputs('sequenceName');
}

function editSequence(sequenceName) {
    currentEditingSequence = sequenceName;
    showSequenceEditor(sequenceName, patternsData.sequences[sequenceName]);
}

function showSequenceEditor(sequenceName, steps) {
    document.getElementById('currentSequenceName').textContent = sequenceName;
    document.getElementById('sequenceEditor').style.display = 'block';
    
    const stepsDiv = document.getElementById('sequenceSteps');
    stepsDiv.innerHTML = '';
    
    steps.forEach((step, index) => {
        addSequenceStepUI(step, index);
    });
    
    // Update button states after all steps are added
    updateSequenceButtonStates();
}

function addSequenceStep() {
    const step = [true, 500]; // Default: on for 500ms
    const index = document.getElementById('sequenceSteps').children.length;
    addSequenceStepUI(step, index);
}

function addSequenceStepUI(step, index) {
    const stepsDiv = document.getElementById('sequenceSteps');
    const stepDiv = document.createElement('div');
    stepDiv.className = 'sequence-step';
    
    const [state, duration] = step;
    
    stepDiv.innerHTML = `
        <label>Step ${index + 1}:</label>
        <select onchange="updateSequenceStep(${index}, 'state', this.value)">
            <option value="true" ${state ? 'selected' : ''}>ON</option>
            <option value="false" ${!state ? 'selected' : ''}>OFF</option>
        </select>
        <input type="number" value="${duration}" placeholder="Duration (ms)" 
               onchange="updateSequenceStep(${index}, 'duration', parseInt(this.value))">
        <button onclick="moveSequenceStepUp(${index})" ${index === 0 ? 'disabled' : ''}>↑</button>
        <button onclick="moveSequenceStepDown(${index})">↓</button>
        <button class="danger" onclick="removeSequenceStep(${index})">Remove</button>
    `;
    
    stepsDiv.appendChild(stepDiv);
    
    // After all steps are added, update the disabled states
    updateSequenceButtonStates();
}

function updateSequenceButtonStates() {
    const stepsDiv = document.getElementById('sequenceSteps');
    const totalSteps = stepsDiv.children.length;
    
    Array.from(stepsDiv.children).forEach((stepDiv, index) => {
        const upButton = stepDiv.querySelector('button[onclick*="moveSequenceStepUp"]');
        const downButton = stepDiv.querySelector('button[onclick*="moveSequenceStepDown"]');
        
        upButton.disabled = (index === 0);
        downButton.disabled = (index === totalSteps - 1);
    });
}

let tempSequenceSteps = [];

function updateSequenceStep(index, field, value) {
    if (!tempSequenceSteps[index]) {
        tempSequenceSteps[index] = [true, 500];
    }
    
    if (field === 'state') {
        tempSequenceSteps[index][0] = value === 'true';
    } else if (field === 'duration') {
        tempSequenceSteps[index][1] = value;
    }
}

function moveSequenceStepUp(index) {
    if (index === 0) return; // Can't move first item up
    
    const stepsDiv = document.getElementById('sequenceSteps');
    const currentSteps = Array.from(stepsDiv.children).map(stepDiv => {
        const select = stepDiv.querySelector('select');
        const input = stepDiv.querySelector('input');
        return [select.value === 'true', parseInt(input.value)];
    });
    
    // Swap with previous step
    [currentSteps[index - 1], currentSteps[index]] = [currentSteps[index], currentSteps[index - 1]];
    
    // Re-render all steps
    stepsDiv.innerHTML = '';
    currentSteps.forEach((step, i) => addSequenceStepUI(step, i));
}

function moveSequenceStepDown(index) {
    const stepsDiv = document.getElementById('sequenceSteps');
    const currentSteps = Array.from(stepsDiv.children).map(stepDiv => {
        const select = stepDiv.querySelector('select');
        const input = stepDiv.querySelector('input');
        return [select.value === 'true', parseInt(input.value)];
    });
    
    if (index === currentSteps.length - 1) return; // Can't move last item down
    
    // Swap with next step
    [currentSteps[index], currentSteps[index + 1]] = [currentSteps[index + 1], currentSteps[index]];
    
    // Re-render all steps
    stepsDiv.innerHTML = '';
    currentSteps.forEach((step, i) => addSequenceStepUI(step, i));
}

function removeSequenceStep(index) {
    const stepsDiv = document.getElementById('sequenceSteps');
    stepsDiv.removeChild(stepsDiv.children[index]);
    
    // Re-render all steps with updated indices
    const currentSteps = Array.from(stepsDiv.children).map((stepDiv, i) => {
        const select = stepDiv.querySelector('select');
        const input = stepDiv.querySelector('input');
        return [select.value === 'true', parseInt(input.value)];
    });
    
    currentSteps.splice(index, 1);
    stepsDiv.innerHTML = '';
    currentSteps.forEach((step, i) => addSequenceStepUI(step, i));
}

function saveSequence() {
    const stepsDiv = document.getElementById('sequenceSteps');
    const steps = Array.from(stepsDiv.children).map(stepDiv => {
        const select = stepDiv.querySelector('select');
        const input = stepDiv.querySelector('input');
        return [select.value === 'true', parseInt(input.value) || 500];
    });
    
    patternsData.sequences[currentEditingSequence] = steps;
    cancelSequenceEdit();
    updateSequenceTable();
    markUnsavedChanges();
    showStatus('Sequence saved');
}

function cancelSequenceEdit() {
    document.getElementById('sequenceEditor').style.display = 'none';
    currentEditingSequence = null;
    tempSequenceSteps = [];
}

function removeSequence(sequenceName) {
    if (confirm(`Delete sequence "${sequenceName}"?`)) {
        delete patternsData.sequences[sequenceName];
        
        // Remove sequence from any patterns that use it
        Object.keys(patternsData.patterns).forEach(patternName => {
            patternsData.patterns[patternName] = patternsData.patterns[patternName].filter(
                seq => seq[2] !== sequenceName  // seq[2] is sequence name in pattern
            );
        });
        
        updateSequenceTable();
        updatePatternTable();
        markUnsavedChanges();
        showStatus('Sequence removed');
    }
}

function updateSequenceTable() {
    const tbody = document.getElementById('sequenceTableBody');
    tbody.innerHTML = '';
    
    Object.entries(patternsData.sequences).forEach(([name, steps], index) => {
        const row = tbody.insertRow();
        const stepsText = steps.map(([state, duration]) => 
            `${state ? 'ON' : 'OFF'}:${duration}ms`
        ).join(', ');
        
        row.innerHTML = `
            <td id="sequenceName-${index}">${name}</td>
            <td>${stepsText}</td>
            <td>
                <button onclick="editSequence('${name}')">Edit</button>
                <button onclick="renameSequence('${name}', ${index})">Rename</button>
                <button class="danger" onclick="removeSequence('${name}')">Remove</button>
            </td>
        `;
    });
}

function renameSequence(oldName, index) {
    const nameCell = document.getElementById(`sequenceName-${index}`);
    
    // Replace the cell content with an input field
    nameCell.innerHTML = `
        <input type="text" id="editSequenceName-${index}" value="${oldName}" style="width: 150px;">
        <button onclick="saveSequenceName('${oldName}', ${index})" style="padding: 4px 8px; margin-left: 5px;">Save</button>
        <button onclick="cancelSequenceRename(${index})" style="padding: 4px 8px; margin-left: 5px;">Cancel</button>
    `;
    
    // Focus on the input field
    document.getElementById(`editSequenceName-${index}`).focus();
}

function saveSequenceName(oldName, index) {
    const newName = document.getElementById(`editSequenceName-${index}`).value.trim();
    
    if (!newName) {
        showStatus('Please enter a sequence name', true);
        return;
    }
    
    if (newName === oldName) {
        cancelSequenceRename(index);
        return;
    }
    
    if (patternsData.sequences[newName]) {
        showStatus('Sequence name already exists', true);
        return;
    }
    
    // Preserve sequence order by rebuilding the object with the same order
    const sequenceEntries = Object.entries(patternsData.sequences);
    const newSequences = {};
    
    sequenceEntries.forEach(([key, value]) => {
        if (key === oldName) {
            newSequences[newName] = value;
        } else {
            newSequences[key] = value;
        }
    });
    
    patternsData.sequences = newSequences;
    
    // Update all patterns that reference this sequence
    Object.keys(patternsData.patterns).forEach(patternName => {
        patternsData.patterns[patternName] = patternsData.patterns[patternName].map(seq => {
            if (seq[2] === oldName) {  // seq[2] is sequence name in pattern
                return [seq[0], seq[1], newName];
            }
            return seq;
        });
    });
    
    // Refresh tables
    updateSequenceTable();
    updatePatternTable();
    markUnsavedChanges();
    showStatus('Sequence renamed');
}

function cancelSequenceRename(index) {
    // Simply refresh the table to cancel the rename
    updateSequenceTable();
}

// Pattern functions
function createNewPattern() {
    const patternName = document.getElementById('patternName').value.trim();
    
    if (!patternName) {
        showStatus('Please enter a pattern name', true);
        return;
    }
    
    if (patternsData.patterns[patternName]) {
        showStatus('Pattern already exists', true);
        return;
    }
    
    currentEditingPattern = patternName;
    patternsData.patterns[patternName] = [];
    
    showPatternEditor(patternName, []);
    clearInputs('patternName');
}

function editPattern(patternName) {
    currentEditingPattern = patternName;
    showPatternEditor(patternName, patternsData.patterns[patternName]);
}

function showPatternEditor(patternName, sequences) {
    document.getElementById('currentPatternName').textContent = patternName;
    document.getElementById('patternEditor').style.display = 'block';
    
    const sequencesDiv = document.getElementById('patternSequences');
    sequencesDiv.innerHTML = '';
    
    sequences.forEach((seq, index) => {
        addPatternSequenceUI(seq, index);
    });
    
    updatePatternSelect();
}

function addPatternSequence() {
    const seq = ["", 0, ""]; // [solenoid, delay, sequence]
    const index = document.getElementById('patternSequences').children.length;
    addPatternSequenceUI(seq, index);
}

function addPatternSequenceUI(seq, index) {
    const sequencesDiv = document.getElementById('patternSequences');
    const seqDiv = document.createElement('div');
    seqDiv.className = 'pattern-sequence';
    
    const [solenoid, delay, sequenceName] = seq;
    
    // Get available solenoids from channel mappings
    const solenoidOptions = channelsData.map(([_, name]) => 
        `<option value="${name}" ${name === solenoid ? 'selected' : ''}>${name}</option>`
    ).join('');
    
    // Get available sequences
    const sequenceOptions = Object.keys(patternsData.sequences).map(name =>
        `<option value="${name}" ${name === sequenceName ? 'selected' : ''}>${name}</option>`
    ).join('');
    
    seqDiv.innerHTML = `
        <label>Pattern Sequence ${index + 1}:</label>
        <select onchange="updatePatternSequence(${index}, 'solenoid', this.value)">
            <option value="">Select Solenoid</option>
            ${solenoidOptions}
        </select>
        <input type="number" value="${delay}" placeholder="Delay (ms)" 
               onchange="updatePatternSequence(${index}, 'delay', parseInt(this.value))">
        <select onchange="updatePatternSequence(${index}, 'sequence', this.value)">
            <option value="">Select Sequence</option>
            ${sequenceOptions}
        </select>
        <button class="danger" onclick="removePatternSequence(${index})">Remove</button>
    `;
    
    sequencesDiv.appendChild(seqDiv);
}

let tempPatternSequences = [];

function updatePatternSequence(index, field, value) {
    if (!tempPatternSequences[index]) {
        tempPatternSequences[index] = ["", 0, ""];
    }
    
    if (field === 'solenoid') {
        tempPatternSequences[index][0] = value;
    } else if (field === 'delay') {
        tempPatternSequences[index][1] = value;
    } else if (field === 'sequence') {
        tempPatternSequences[index][2] = value;
    }
}

function removePatternSequence(index) {
    const sequencesDiv = document.getElementById('patternSequences');
    sequencesDiv.removeChild(sequencesDiv.children[index]);
    
    // Re-render all sequences with updated indices
    const currentSeqs = Array.from(sequencesDiv.children).map((seqDiv, i) => {
        const selects = seqDiv.querySelectorAll('select');
        const input = seqDiv.querySelector('input');
        return [selects[0].value, parseInt(input.value) || 0, selects[1].value];
    });
    
    currentSeqs.splice(index, 1);
    sequencesDiv.innerHTML = '';
    currentSeqs.forEach((seq, i) => addPatternSequenceUI(seq, i));
}

function savePattern() {
    const sequencesDiv = document.getElementById('patternSequences');
    const sequences = Array.from(sequencesDiv.children).map(seqDiv => {
        const selects = seqDiv.querySelectorAll('select');
        const input = seqDiv.querySelector('input');
        return [selects[0].value, parseInt(input.value) || 0, selects[1].value];
    });
    
    patternsData.patterns[currentEditingPattern] = sequences;
    cancelPatternEdit();
    updatePatternTable();
    updatePatternSelect();
    markUnsavedChanges();
    showStatus('Pattern saved');
}

function cancelPatternEdit() {
    document.getElementById('patternEditor').style.display = 'none';
    currentEditingPattern = null;
    tempPatternSequences = [];
}

function removePattern(patternName) {
    if (confirm(`Delete pattern "${patternName}"?`)) {
        delete patternsData.patterns[patternName];
        
        // Remove pattern from mappings
        Object.keys(patternsData.pattern_mappings).forEach(buttonIndex => {
            if (patternsData.pattern_mappings[buttonIndex] === patternName) {
                delete patternsData.pattern_mappings[buttonIndex];
            }
        });
        
        updatePatternTable();
        updatePatternSelect();
        updateMappingTable();
        markUnsavedChanges();
        showStatus('Pattern removed');
    }
}

function updatePatternTable() {
    const tbody = document.getElementById('patternTableBody');
    tbody.innerHTML = '';
    
    Object.entries(patternsData.patterns).forEach(([name, sequences]) => {
        const row = tbody.insertRow();
        const sequencesText = sequences.map(([solenoid, delay, seq]) => 
            `${solenoid}+${delay}ms→${seq}`
        ).join(', ');
        
        row.innerHTML = `
            <td>${name}</td>
            <td>${sequencesText}</td>
            <td>
                <button onclick="editPattern('${name}')">Edit</button>
                <button class="danger" onclick="removePattern('${name}')">Remove</button>
            </td>
        `;
    });
}

// Pattern mapping functions
function addPatternMapping() {
    const buttonIndex = parseInt(document.getElementById('buttonIndex').value);
    const patternName = document.getElementById('patternSelect').value;
    
    if (isNaN(buttonIndex) || buttonIndex < 0) {
        showStatus('Please enter a valid button index', true);
        return;
    }
    
    if (!patternName) {
        showStatus('Please select a pattern', true);
        return;
    }
    
    patternsData.pattern_mappings[buttonIndex] = patternName;
    updateMappingTable();
    clearInputs('buttonIndex');
    document.getElementById('patternSelect').value = '';
    markUnsavedChanges();
    showStatus('Button mapping added');
}

function removePatternMapping(buttonIndex) {
    delete patternsData.pattern_mappings[buttonIndex];
    updateMappingTable();
    markUnsavedChanges();
    showStatus('Button mapping removed');
}

function updateMappingTable() {
    const tbody = document.getElementById('mappingTableBody');
    tbody.innerHTML = '';
    
    Object.entries(patternsData.pattern_mappings).forEach(([buttonIndex, patternName]) => {
        const row = tbody.insertRow();
        row.innerHTML = `
            <td>${buttonIndex}</td>
            <td>${patternName}</td>
            <td>
                <button class="danger" onclick="removePatternMapping('${buttonIndex}')">Remove</button>
            </td>
        `;
    });
}

function updatePatternSelect() {
    const select = document.getElementById('patternSelect');
    const currentValue = select.value;
    
    select.innerHTML = '<option value="">Select Pattern</option>';
    Object.keys(patternsData.patterns).forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        if (name === currentValue) option.selected = true;
        select.appendChild(option);
    });
}

// Update all tables
function updateAllTables() {
    updateChannelTable();
    updateSequenceTable();
    updatePatternTable();
    updateMappingTable();
    updatePatternSelect();
}
