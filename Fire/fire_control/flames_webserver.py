from flask import Flask
from flask import request
from flask import abort
import json
import logging
import requests
import time
import urllib

import flames_controller
import poofermapping
import pattern_manager
import trigger_integration
from flask_utils import CORSResponse
from flask_utils import JSONResponse

'''
    Webserver for the flame effect controller. In this variant, we're mostly
    interested in sequences - we have CRUD endpoints for sequences, as well
    as commands to run (or stop) a particular sequence. Other endpoints will
    globally disable (or re-enable) particular poofers; note, however that
    the buttons on the sculpture bypass any software control, so if you
    really want to turn a poofer off, you're going to have to go put pink
    tape on the button
'''

PORT = 5001

logger = logging.getLogger("flames")

#app = Flask("flg", static_url_path="", static_folder="/home/flaming/haven/Flames/static")
app = Flask("flg", static_url_path="")


# XXX TODO - function to set the log level

def serve_forever(httpPort=PORT):
    logger.info("FLAMES WebServer: port {}".format(httpPort))
    app.run(host="0.0.0.0", port=httpPort, threaded=True) ## XXX - FIXME - got a broken pipe on the socket that terminated the application (uncaught exception) supposedly this is fixed in flask 0.12

@app.route("/")
def index():
    """Serve the flame control web UI (always fresh — no browser caching)."""
    resp = app.send_static_file('index.html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma']        = 'no-cache'
    resp.headers['Expires']       = '0'
    return resp


@app.after_request
def _disable_static_cache(response):
    """Prevent the browser from caching JS/CSS static assets."""
    if request.path.startswith('/') and any(
            request.path.endswith(ext) for ext in ('.js', '.css')):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma']        = 'no-cache'
        response.headers['Expires']       = '0'
    return response


@app.route("/flame", methods=['GET', 'POST'])
def flame_status():
    ''' GET /flame. Get status of all poofers, any active patterns. (Poofer status 
          is [on|off], [enabled|disabled].)
        POST /flame playState=[pause|play]. Whole sculpture gross control. 
          Pause/Play: Pause all poofing and flame effects (should terminate any 
          current patterns, prevent any poofing until Play is called]
    '''
    if request.method == 'POST':
        if "playState" in request.values:
            playState = request.values["playState"].lower()
            if playState == "pause":
                flames_controller.stopAllLoops()   # cancel autonomous loops before pause
                flames_controller.globalPause()
            elif playState == "play":
                flames_controller.globalRelease()
            else:
                return CORSResponse("Invalid 'playState' value", 400)
        else:
            return CORSResponse("Must have 'playState' value", 400)

        return CORSResponse("Success!", 200)

    else:
        return JSONResponse(json.dumps(get_status()))


@app.route("/flame/poofers/<poofer_id>", methods=['GET', 'POST'])
def specific_flame_status(poofer_id):
    ''' GET /flame/poofers/<poofername>. Get status of particular poofer.
        POST /flame/poofers/<poofername> enabled=[true|false]. Set enabled
         state for individual poofers.
    '''
    if not poofer_id_valid(poofer_id):
        abort(400)
    if request.method == 'POST':
        if not "enabled" in request.values:
            return CORSResponse("'enabled' must be present", 400)

        enabled = request.values["enabled"].lower()
        if enabled == 'true':
            flames_controller.enablePoofer(poofer_id)
        elif enabled == 'false':
            flames_controller.disablePoofer(poofer_id)
        else:
            return CORSResponse("Invalid 'enabled' value", 400)

        return CORSResponse("Success", 200)
    else:
        return JSONResponse(json.dumps(get_poofer_status(poofer_id)))

@app.route("/flame/patterns", methods=['GET','POST'])
def flame_patterns():
    ''' GET /flame/patterns: Get list of all flame patterns, whether active
         or not
        POST /flame/patterns: Creates a new flame pattern from json patterndata
    '''
    if request.method == 'GET':
        return JSONResponse(json.dumps(get_flame_patterns()))
    else:
        if not "patternData" in request.values:
            return CORSResponse("'patternData' must be present", 400)
        else:
            set_flame_pattern(request.values["patternData"])
            return CORSResponse("Success", 200)


@app.route("/flame/patterns/<patternName>", methods=['GET', 'POST', 'DELETE'])
def flame_pattern(patternName):
    ''' POST /flame/patterns/<patternName> active=[true|false] enabled=[true|false] pattern=[pattern]
          active - Start an individual pattern (or stop it if it is currently running).
          enabled - enable/disable a pattern.
          pattern - pattern data, modify existing pattern
    '''
    includesPattern = "pattern" in request.values
    includesEnabled = "enabled" in request.values
    includesActive  = "active"  in request.values

    if request.method == 'POST':
        # modify pattern
        # XXX - this code does not work, does not go through pattern manager
        if  (not includesPattern) and (not patternName_valid(patternName)):
            return CORSResponse("Must have valid 'patternName'", 400)

        if includesPattern:
            patternData = json.loads(request.values["pattern"])
            oldPatternData = None
            for pattern in patternList:
                if pattern["name"] == patternData["name"]:
                    oldPatternData = pattern
                    break;
            if oldPatternData == None:
                patternList.append(patternData)
            else:
                oldPatternData["events"] = patternData["events"]
            savePatternData()

        if includesEnabled:
            enabled = request.values["enabled"].lower()
            enabledValid = param_valid(enabled, ["true", "false"])
        else:
            enabledValid = False
        if includesActive:
            active = request.values["active"].lower()
            activeValid = param_valid(active, ["true", "false"])
        else:
            activeValid = False

        # Optional loop parameters — if supplied with active=true, loop the pattern.
        #   repeat_interval=N  fire on a fixed N-ms clock (clamped to pattern duration)
        #   repeat_gap=N       fire N ms after the previous run ends (0 = back-to-back)
        repeat_interval_ms = None
        repeat_gap_ms = None
        if "repeat_interval" in request.values:
            try:
                repeat_interval_ms = int(request.values["repeat_interval"])
            except ValueError:
                return CORSResponse("'repeat_interval' must be an integer (milliseconds)", 400)
        if "repeat_gap" in request.values:
            try:
                repeat_gap_ms = int(request.values["repeat_gap"])
            except ValueError:
                return CORSResponse("'repeat_gap' must be an integer (milliseconds)", 400)

        if repeat_interval_ms is not None and repeat_gap_ms is not None:
            return CORSResponse("Specify 'repeat_interval' or 'repeat_gap', not both", 400)

        if (not enabledValid and not activeValid):
            abort(400)

        if enabledValid:
            if (enabled == "true"):
                flames_controller.enableFlameEffect(patternName)
            elif (enabled == "false"):
                flames_controller.disableFlameEffect(patternName)
        if activeValid:
            if (active == "true"):
                if repeat_interval_ms is not None or repeat_gap_ms is not None:
                    try:
                        flames_controller.loopFlameEffect(
                            patternName,
                            interval_ms=repeat_interval_ms or 0,
                            gap_ms=repeat_gap_ms or 0
                        )
                    except ValueError as e:
                        return CORSResponse(str(e), 400)
                else:
                    flames_controller.doFlameEffect(patternName)
            elif (active == "false"):
                flames_controller.stopFlameEffect(patternName)   # also cancels any loop

        return CORSResponse("Success", 200)

    elif request.method == "DELETE":
        pattern_manager.deletePattern(patternName)
        pattern_manager.savePatterns()
        return CORSResponse("Success", 200)

    else: # ie, GET
        if (not patternName_valid(patternName)):
            return CORSResponse("Must have valid 'patternName'", 400)
        else:
            if "full" in request.values:
                return JSONResponse(json.dumps(get_pattern(patternName)))
            else:                      
                return JSONResponse(json.dumps(get_pattern_status(patternName)))


@app.route("/flame/patterns/loops/stop", methods=['POST'])
def stop_all_loops():
    '''POST /flame/patterns/loops/stop : Stop all autonomous looping patterns
       without globally pausing the system (scene transition helper).
    '''
    flames_controller.stopAllLoops()
    return CORSResponse("All loops stopped", 200)


def get_status():
    pooferList = list()
    patternList = list()
    # getLoopingFlameEffects() → {name: {mode, period_ms, pattern_dur_ms, ...}}
    looping = flames_controller.getLoopingFlameEffects()
    for pooferId in poofermapping.mappings:
        pooferList.append({"id" : pooferId,
                           "enabled": flames_controller.isPooferEnabled(pooferId),
                           "active" : flames_controller.isPooferActive(pooferId)})
    for patternName in pattern_manager.getPatternNames():
        entry = {"name"    : patternName,
                 "enabled" : flames_controller.isFlameEffectEnabled(patternName),
                 "active"  : flames_controller.isFlameEffectActive(patternName),
                 "looping" : patternName in looping}
        if patternName in looping:
            entry["loop_info"] = looping[patternName]
        patternList.append(entry)
    return {"globalState": (not flames_controller.isStopped()),
            "poofers" : pooferList,
            "patterns": patternList,
            "looping_patterns": looping}


def get_poofer_status(poofer_id):
    # there's enabled, and there's active (whether it's currently on)
    pooferStatus = {"enabled": flames_controller.isPooferEnabled(poofer_id),
                    "active" : flames_controller.isPooferActive(poofer_id)}
    return pooferStatus

def get_pattern_status(patternName):
    looping = flames_controller.isFlameEffectLooping(patternName)
    patternStatus = {"enabled" : flames_controller.isFlameEffectEnabled(patternName),
                     "active"  : flames_controller.isFlameEffectActive(patternName),
                     "looping" : looping}
    if looping:
        # getLoopingFlameEffects() returns {name: {mode, period_ms, ...}}
        loop_info = flames_controller.getLoopingFlameEffects().get(patternName)
        if loop_info:
            patternStatus["loop_info"] = loop_info
    return patternStatus

def get_pattern(patternName):
    return pattern_manager.getPattern(patternName);

def get_flame_patterns():
    patterns = pattern_manager.getAllPatterns()
    for pattern in patterns: 
        patternName = pattern["name"]
        status = get_pattern_status(patternName)
        for statusKey in status:
            pattern[statusKey] = status[statusKey]
    return patterns

# abort 500 in general? how are errors expected to be propagated in this framework?s
def set_flame_pattern(pattern):
    pattern_manager.addOrModifyPattern(json.loads(pattern))
    pattern_manager.savePatterns()

def poofer_id_valid(id):
    return id in poofermapping.mappings

def patternName_valid(patternName):
    return patternName in pattern_manager.getPatternNames()

def param_valid(value, validValues):
    return value != None and (value.lower() in validValues)

# ---------------------------------------------------------------------------
# Poofer Mapping Endpoints
# ---------------------------------------------------------------------------

@app.route("/flame/poofer-mappings", methods=['GET', 'POST'])
def poofer_mappings():
    '''GET  /flame/poofer-mappings         : Return all current poofer→address mappings.
       POST /flame/poofer-mappings         : Add (or overwrite) a mapping.
         Required fields: name, address
    '''
    if request.method == 'GET':
        return JSONResponse(json.dumps(poofermapping.get_all()))

    # POST – add / overwrite a mapping
    name    = request.values.get('name',    '').strip()
    address = request.values.get('address', '').strip()
    if not name:
        return CORSResponse("'name' must be present and non-empty", 400)
    if not address:
        return CORSResponse("'address' must be present and non-empty", 400)
    try:
        poofermapping.update_mapping(name, address)
        return JSONResponse(json.dumps({'name': name, 'address': address}), 201)
    except ValueError as e:
        return CORSResponse(str(e), 400)


@app.route("/flame/poofer-mappings/reset-defaults", methods=['POST'])
def poofer_mappings_reset_defaults():
    '''POST /flame/poofer-mappings/reset-defaults : Reset all mappings to built-in defaults.'''
    poofermapping.reset_to_defaults()
    return JSONResponse(json.dumps(poofermapping.get_all()))


@app.route("/flame/poofer-mappings/<name>", methods=['PUT', 'DELETE'])
def poofer_mapping(name):
    '''PUT    /flame/poofer-mappings/<name> address=<addr> : Update the address for a mapping.
       DELETE /flame/poofer-mappings/<name>                : Remove a mapping.
    '''
    if request.method == 'PUT':
        address = request.values.get('address', '').strip()
        if not address:
            return CORSResponse("'address' must be present and non-empty", 400)
        try:
            poofermapping.update_mapping(name, address)
            return CORSResponse('Updated', 200)
        except ValueError as e:
            return CORSResponse(str(e), 400)

    # DELETE
    if poofermapping.delete_mapping(name):
        return CORSResponse('Deleted', 200)
    return CORSResponse('Mapping not found', 404)


# Trigger Integration Endpoints

@app.route("/trigger-integration/status", methods=['GET'])
def trigger_integration_status():
    '''GET /trigger-integration/status: Get trigger integration status'''
    integration = trigger_integration.get_integration()
    if integration:
        return JSONResponse(json.dumps(integration.get_status()))
    else:
        return CORSResponse("Trigger integration not initialized", 503)

@app.route("/trigger-integration/triggers", methods=['GET'])
def trigger_integration_triggers():
    '''GET /trigger-integration/triggers: Get available triggers from trigger server'''
    integration = trigger_integration.get_integration()
    if integration:
        triggers = integration.get_available_triggers()
        return JSONResponse(json.dumps({'triggers': triggers}))
    else:
        return CORSResponse("Trigger integration not initialized", 503)

@app.route("/trigger-integration/scenes", methods=['GET'])
def trigger_integration_scenes():
    '''GET /trigger-integration/scenes: Get available scenes from scene service.

    Response JSON:
      { "scenes": [...],             -- scene names from the scene service
        "active_scene": "...",       -- currently active scene
        "configured_scenes": [...] } -- scenes registered in the flames config
    '''
    integration = trigger_integration.get_integration()
    if integration:
        scenes             = integration.get_available_scenes()
        active_scene       = integration.get_active_scene()
        configured_scenes = integration.get_configured_scenes()
        return JSONResponse(json.dumps({
            'scenes':            scenes,
            'active_scene':      active_scene,
            'configured_scenes': configured_scenes,
        }))
    else:
        return CORSResponse("Trigger integration not initialized", 503)

@app.route("/trigger-integration/scenes/active", methods=['GET'])
def trigger_integration_active_scenes():
    '''GET /trigger-integration/scenes/active: Get currently active scene'''
    integration = trigger_integration.get_integration()
    if integration:
        active_scene = integration.get_active_scene()
        return JSONResponse(json.dumps({'active_scene': active_scene}))
    else:
        return CORSResponse("Trigger integration not initialized", 503)


@app.route("/api/refresh-scene", methods=['POST'])
def refresh_scene():
    '''POST /api/refresh-scene: Force an immediate re-fetch of the active
    scene from the scene service and return the result.

    Response JSON:
      { "active_scene": "<name>"|null, "refreshed": true|false }

    "refreshed" is true when the scene service responded with HTTP 200,
    false when it was unreachable (active_scene then reflects the last
    known cached value, which may still be "Unknown" at boot).
    '''
    integration = trigger_integration.get_integration()
    if not integration:
        return CORSResponse("Trigger integration not initialized", 503)

    ok, active_scene = integration.refresh_active_scene()
    return JSONResponse(json.dumps({
        'active_scene': active_scene,
        'refreshed': ok,
    }))

@app.route("/trigger-integration/scenes", methods=['POST'])
def trigger_integration_scenes_create():
    '''POST /trigger-integration/scenes: Register a scene (create an empty config).

    Form param:  scene_name  – name of the scene to register
    '''
    scene_name = request.values.get('scene_name', '').strip()
    if not scene_name:
        return CORSResponse("'scene_name' is required", 400)
    integration = trigger_integration.get_integration()
    if not integration:
        return CORSResponse("Trigger integration not initialized", 503)
    integration.register_scene(scene_name)
    return JSONResponse(json.dumps({'scene_name': scene_name, 'registered': True}), 201)


@app.route("/trigger-integration/scenes/<scene_name>", methods=['DELETE'])
def trigger_integration_scenes_delete(scene_name):
    '''DELETE /trigger-integration/scenes/<name>: Delete a scene and all its mappings.'''
    integration = trigger_integration.get_integration()
    if not integration:
        return CORSResponse("Trigger integration not initialized", 503)
    if integration.delete_scene(scene_name):
        return CORSResponse("Scene deleted", 200)
    return CORSResponse("Scene not found", 404)


@app.route("/trigger-integration/mappings/copy-scene", methods=['POST'])
def copy_scene_mappings():
    '''POST /trigger-integration/mappings/copy-scene
    Form params:
      from_scene  – name of the source scene to copy from
      to_scene    – name of the target scene to copy to

    Duplicates all trigger mappings from from_scene into to_scene.
    The new scene is registered (even if from_scene is empty / quiet).

    Response JSON: {"from_scene": "...", "to_scene": "...", "copied_count": N}
    '''
    from_scene = request.values.get('from_scene', '').strip()
    to_scene   = request.values.get('to_scene',   '').strip()
    if not from_scene:
        return CORSResponse("'from_scene' is required", 400)
    if not to_scene:
        return CORSResponse("'to_scene' is required", 400)
    if from_scene == to_scene:
        return CORSResponse("'from_scene' and 'to_scene' must differ", 400)

    integration = trigger_integration.get_integration()
    if not integration:
        return CORSResponse("Trigger integration not initialized", 503)

    copied = integration.copy_scene_mappings(from_scene, to_scene)
    return JSONResponse(json.dumps({
        'from_scene': from_scene,
        'to_scene': to_scene,
        'copied_count': copied,
    }))


@app.route("/trigger-integration/mappings", methods=['GET', 'POST'])
def trigger_integration_mappings():
    '''GET /trigger-integration/mappings: Get all trigger-to-flame mappings
       POST /trigger-integration/mappings: Create new mapping
    '''
    integration = trigger_integration.get_integration()
    if not integration:
        return CORSResponse("Trigger integration not initialized", 503)
    
    if request.method == 'GET':
        mappings = integration.get_mappings()
        return JSONResponse(json.dumps({'mappings': mappings}))
    else:  # POST
        if not "trigger_name" in request.values:
            return CORSResponse("'trigger_name' must be present", 400)
        if not "flame_sequence" in request.values:
            return CORSResponse("'flame_sequence' must be present", 400)
        
        trigger_name = request.values["trigger_name"]
        flame_sequence = request.values["flame_sequence"]
        allow_override = request.values.get("allow_override", "false").lower() == "true"
        
        # Handle both discrete value and continuous range
        trigger_value = request.values.get("trigger_value", None)
        trigger_value_min = request.values.get("trigger_value_min", None)
        trigger_value_max = request.values.get("trigger_value_max", None)
        
        # The scene this mapping belongs to (required in the new data model)
        scene = request.values.get('scene', '').strip()
        if not scene:
            return CORSResponse("'scene' is required", 400)

        mapping = integration.add_mapping(
            scene,
            trigger_name,
            trigger_value,
            flame_sequence,
            allow_override,
            trigger_value_min,
            trigger_value_max,
        )
        return JSONResponse(json.dumps({'message': 'Mapping created', 'mapping': mapping}), 201)

@app.route("/trigger-integration/mappings/<int:mapping_id>", methods=['GET', 'PUT', 'DELETE'])
def trigger_integration_mapping(mapping_id):
    '''GET /trigger-integration/mappings/<id>: Get specific mapping
       PUT /trigger-integration/mappings/<id>: Update mapping
       DELETE /trigger-integration/mappings/<id>: Delete mapping
    '''
    integration = trigger_integration.get_integration()
    if not integration:
        return CORSResponse("Trigger integration not initialized", 503)
    
    if request.method == 'DELETE':
        if integration.delete_mapping(mapping_id):
            return CORSResponse("Mapping deleted", 200)
        else:
            return CORSResponse("Mapping not found", 404)
    
    elif request.method == 'PUT':
        trigger_name = request.values.get("trigger_name")
        trigger_value = request.values.get("trigger_value")
        flame_sequence = request.values.get("flame_sequence")
        allow_override = None
        if "allow_override" in request.values:
            allow_override = request.values["allow_override"].lower() == "true"
        
        # Handle range values for continuous triggers
        trigger_value_min = request.values.get("trigger_value_min", None)
        trigger_value_max = request.values.get("trigger_value_max", None)

        # Optional scene move (moving a mapping to a different scene)
        scene = request.values.get("scene", None)
        if scene is not None:
            scene = scene.strip() or None

        if integration.update_mapping(
                mapping_id,
                scene=scene,
                trigger_name=trigger_name,
                trigger_value=trigger_value,
                flame_sequence=flame_sequence,
                allow_override=allow_override,
                trigger_value_min=trigger_value_min,
                trigger_value_max=trigger_value_max):
            return CORSResponse("Mapping updated", 200)
        else:
            return CORSResponse("Mapping not found", 404)

    else:  # GET
        mapping = integration.get_mapping(mapping_id)
        if mapping:
            return JSONResponse(json.dumps(mapping))
        return CORSResponse("Mapping not found", 404)

def shutdown():
    logger.info("Flames webserver shutdown")
    flames_drv.shutdown()
    flames_controller.shutdown()
    event_manager.shutdown()
    pattern_manager.shutdown()
    trigger_integration.shutdown()

production = True

if __name__ == "__main__":
    import argparse
    from threading import Thread
    import event_manager
    import queue
    import flames_drv
    
    parser = argparse.ArgumentParser(description='Flame Control Web Server')
    parser.add_argument('--port', type=int, default=PORT,
                        help=f'Port to run the web server on (default: {PORT})')
    args = parser.parse_args()
    
    httpPort = args.port
    
    print("flame api!!")

    logging.basicConfig(format='%(asctime)-15s %(levelname)s %(module)s %(lineno)d: %(message)s', level=logging.DEBUG)

    poofermapping.init()
    #pattern_manager.init("./pattern_test_2.json")
    pattern_manager.init("./std_sequences.json")
    event_manager.init()

    commandQueue = queue.Queue()
    flames_drv.init(commandQueue, ".") # XXX FIXME. Homedir may not be "." Take from args?:
    flames_controller.init(commandQueue)
    
    # Initialize trigger integration
    trigger_integration.init(trigger_server_url="http://localhost:5002", listen_port=6000)
    logger.info(f"Production is {production}")

    if production:
        try:
            serve_forever(httpPort)
        except Exception as e:
            logger.error(f"Webserver gets exception {e}")
            shutdown()
    else:
        flaskThread = Thread(target=serve_forever) #, args=[5000, "localhost", 9000])
        flaskThread.start()

        time.sleep(5)
        print("About to make request!")

        baseURL = 'http://localhost:' + str(PORT) + "/"

        print("Setting playstate to Pause")
        r = requests.post(baseURL + "flame", data={"playState":"pause"})
        print(r.status_code)

        r = requests.get(baseURL + "flame")
        print(r.status_code)
        print(r.json())

        print("Setting playstate to Play")
        r = requests.post(baseURL + "flame", data={"playState":"play"})
        print(r.status_code)

        r = requests.get(baseURL + "flame")
        print(r.status_code)
        print(r.json())

        print("Get poofers")
        r = requests.get(baseURL + "flame/poofers/1_T1")
        print(r.status_code)
        print(r.json())

        print("Set poofer enabled/disabled")
        r = requests.post(baseURL + "flame/poofers/1_T1", data={"enabled":"false"})

        r = requests.get(baseURL + "flame/poofers/1_T1")
        print(r.status_code)
        print(r.json())

        r = requests.post(baseURL + "flame/poofers/1_T1", data={"enabled":"true"})

        r = requests.get(baseURL + "flame/poofers/1_T1")
        print(r.status_code)
        print(r.json())

        print("Set pattern enabled/disabled")
        r = requests.post(baseURL + "flame/patterns/Firefly_3_chase", data={"enabled":"false"})

        r = requests.get(baseURL + "flame/patterns/Firefly_3_chase")
        print(r.status_code)
        print(r.json())

        r = requests.post(baseURL + "flame/patterns/Firefly_3_chase", data={"enabled":"true"})

        r = requests.get(baseURL + "flame/patterns/Firefly_3_chase")
        print(r.status_code)
        print(r.json())

        print("Set pattern active")
        r = requests.post(baseURL + "flame/patterns/Firefly_3_chase", data={"active":"true"})

        print("Set pattern inactive")
        r = requests.post(baseURL + "flame/patterns/Firefly_3_chase", data={"active":"false"})

        shutdown()
