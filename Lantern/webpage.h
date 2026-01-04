#ifndef WEBPAGE_H
#define WEBPAGE_H

// HTML webpage with UI
const char* htmlPage = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
    <title>LED Controller</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .container {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 15px;
            padding: 30px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
        }
        .color-section {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .control-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 10px;
            font-weight: bold;
            font-size: 16px;
        }
        .color-picker {
            width: 100%;
            height: 60px;
            border-radius: 10px;
            border: 3px solid rgba(255, 255, 255, 0.3);
            cursor: pointer;
        }
        input[type="number"] {
            width: 100%;
            padding: 10px;
            border-radius: 5px;
            border: none;
            background: rgba(255, 255, 255, 0.2);
            color: white;
            font-size: 16px;
        }
        .hsv-display {
            margin-top: 10px;
            padding: 10px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 5px;
            font-family: monospace;
            font-size: 14px;
        }
        button {
            width: 100%;
            padding: 15px;
            margin-top: 15px;
            border: none;
            border-radius: 10px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s;
        }
        button:hover {
            transform: scale(1.05);
        }
        button:active {
            transform: scale(0.95);
        }
        .status {
            text-align: center;
            margin-top: 20px;
            padding: 10px;
            border-radius: 5px;
            background: rgba(255, 255, 255, 0.2);
            display: none;
        }
        .status.success {
            background: rgba(76, 175, 80, 0.3);
        }
        .status.error {
            background: rgba(244, 67, 54, 0.3);
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>WS2812 LED Controller</h1>
        
        <div class="color-section">
            <h2>Color A</h2>
            <div class="control-group">
                <label>Choose Color:</label>
                <input type="color" id="colorPickerA" value="#0000ff" oninput="updateFromPickerA()" class="color-picker">
            </div>
            <div class="hsv-display">HSV: <span id="hsvA-display">H:160 S:255 V:255</span></div>
            <button onclick="setColorA()">Set Color A</button>
        </div>
        
        <div class="color-section">
            <h2>Color B</h2>
            <div class="control-group">
                <label>Choose Color:</label>
                <input type="color" id="colorPickerB" value="#ff0000" oninput="updateFromPickerB()" class="color-picker">
            </div>
            <div class="hsv-display">HSV: <span id="hsvB-display">H:0 S:255 V:255</span></div>
            <button onclick="setColorB()">Set Color B</button>
        </div>
        
        <div class="color-section">
            <h2>Transition Settings</h2>
            <div class="control-group">
                <label>Transition Time (milliseconds):</label>
                <input type="number" id="transitionTime" value="20000" min="100" max="300000">
            </div>
            <button onclick="setTransitionTime()">Set Transition Time</button>
        </div>
        
        <div class="status" id="status"></div>
    </div>
    
    <script>
        // Store current HSV values
        let colorA_hsv = {h: 160, s: 255, v: 255};
        let colorB_hsv = {h: 0, s: 255, v: 255};
        
        // RGB to HSV conversion
        function rgbToHsv(r, g, b) {
            r /= 255;
            g /= 255;
            b /= 255;
            
            const max = Math.max(r, g, b);
            const min = Math.min(r, g, b);
            const diff = max - min;
            
            let h = 0;
            let s = max === 0 ? 0 : diff / max;
            let v = max;
            
            if (diff !== 0) {
                if (max === r) {
                    h = ((g - b) / diff + (g < b ? 6 : 0)) / 6;
                } else if (max === g) {
                    h = ((b - r) / diff + 2) / 6;
                } else {
                    h = ((r - g) / diff + 4) / 6;
                }
            }
            
            return {
                h: Math.round(h * 255),
                s: Math.round(s * 255),
                v: Math.round(v * 255)
            };
        }
        
        // HSV to RGB conversion (for display)
        function hsvToRgb(h, s, v) {
            h = h / 255;
            s = s / 255;
            v = v / 255;
            
            let r, g, b;
            let i = Math.floor(h * 6);
            let f = h * 6 - i;
            let p = v * (1 - s);
            let q = v * (1 - f * s);
            let t = v * (1 - (1 - f) * s);
            
            switch (i % 6) {
                case 0: r = v; g = t; b = p; break;
                case 1: r = q; g = v; b = p; break;
                case 2: r = p; g = v; b = t; break;
                case 3: r = p; g = q; b = v; break;
                case 4: r = t; g = p; b = v; break;
                case 5: r = v; g = p; b = q; break;
            }
            
            return {
                r: Math.round(r * 255),
                g: Math.round(g * 255),
                b: Math.round(b * 255)
            };
        }
        
        // Convert hex color to RGB
        function hexToRgb(hex) {
            const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
            return result ? {
                r: parseInt(result[1], 16),
                g: parseInt(result[2], 16),
                b: parseInt(result[3], 16)
            } : null;
        }
        
        function updateFromPickerA() {
            const hex = document.getElementById('colorPickerA').value;
            const rgb = hexToRgb(hex);
            if (rgb) {
                colorA_hsv = rgbToHsv(rgb.r, rgb.g, rgb.b);
                document.getElementById('hsvA-display').textContent = 
                    `H:${colorA_hsv.h} S:${colorA_hsv.s} V:${colorA_hsv.v}`;
            }
        }
        
        function updateFromPickerB() {
            const hex = document.getElementById('colorPickerB').value;
            const rgb = hexToRgb(hex);
            if (rgb) {
                colorB_hsv = rgbToHsv(rgb.r, rgb.g, rgb.b);
                document.getElementById('hsvB-display').textContent = 
                    `H:${colorB_hsv.h} S:${colorB_hsv.s} V:${colorB_hsv.v}`;
            }
        }
        
        function showStatus(message, isError = false) {
            const status = document.getElementById('status');
            status.textContent = message;
            status.className = 'status ' + (isError ? 'error' : 'success');
            status.style.display = 'block';
            setTimeout(() => {
                status.style.display = 'none';
            }, 3000);
        }
        
        async function setColorA() {
            try {
                const response = await fetch(`/api/colorA?h=${colorA_hsv.h}&s=${colorA_hsv.s}&v=${colorA_hsv.v}`, {
                    method: 'POST'
                });
                const data = await response.json();
                showStatus(data.message);
            } catch (error) {
                showStatus('Error setting Color A', true);
            }
        }
        
        async function setColorB() {
            try {
                const response = await fetch(`/api/colorB?h=${colorB_hsv.h}&s=${colorB_hsv.s}&v=${colorB_hsv.v}`, {
                    method: 'POST'
                });
                const data = await response.json();
                showStatus(data.message);
            } catch (error) {
                showStatus('Error setting Color B', true);
            }
        }
        
        async function setTransitionTime() {
            const time = document.getElementById('transitionTime').value;
            
            try {
                const response = await fetch(`/api/transition?time=${time}`, {
                    method: 'POST'
                });
                const data = await response.json();
                showStatus(data.message);
            } catch (error) {
                showStatus('Error setting transition time', true);
            }
        }
        
        // Load current values on page load
        async function loadCurrentValues() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                colorA_hsv = data.colorA;
                colorB_hsv = data.colorB;
                
                // Convert HSV to RGB for color picker
                const rgbA = hsvToRgb(colorA_hsv.h, colorA_hsv.s, colorA_hsv.v);
                const hexA = '#' + [rgbA.r, rgbA.g, rgbA.b].map(x => {
                    const hex = x.toString(16);
                    return hex.length === 1 ? '0' + hex : hex;
                }).join('');
                document.getElementById('colorPickerA').value = hexA;
                
                const rgbB = hsvToRgb(colorB_hsv.h, colorB_hsv.s, colorB_hsv.v);
                const hexB = '#' + [rgbB.r, rgbB.g, rgbB.b].map(x => {
                    const hex = x.toString(16);
                    return hex.length === 1 ? '0' + hex : hex;
                }).join('');
                document.getElementById('colorPickerB').value = hexB;
                
                document.getElementById('transitionTime').value = data.transitionTime;
                
                document.getElementById('hsvA-display').textContent = 
                    `H:${colorA_hsv.h} S:${colorA_hsv.s} V:${colorA_hsv.v}`;
                document.getElementById('hsvB-display').textContent = 
                    `H:${colorB_hsv.h} S:${colorB_hsv.s} V:${colorB_hsv.v}`;
            } catch (error) {
                console.error('Error loading current values:', error);
            }
        }
        
        // Initialize on page load
        loadCurrentValues();
    </script>
</body>
</html>
)rawliteral";

#endif // WEBPAGE_H
