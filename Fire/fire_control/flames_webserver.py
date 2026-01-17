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

        if (not enabledValid and not activeValid):
            abort(400)

        if enabledValid:
            if (enabled == "true"):
                flames_controller.enableFlameEffect(patternName)
            elif (enabled == "false"):
                flames_controller.disableFlameEffect(patternName)
        if activeValid:
            if (active == "true"):
                flames_controller.doFlameEffect(patternName)
            elif (active == "false"):
                flames_controller.stopFlameEffect(patternName)

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


def get_status():
    pooferList = list()
    patternList = list()
    for pooferId in poofermapping.mappings:
        pooferList.append({"id" : pooferId,
                           "enabled": flames_controller.isPooferEnabled(pooferId),
                           "active" : flames_controller.isPooferActive(pooferId)})
    for patternName in pattern_manager.getPatternNames():
        patternList.append({"name" : patternName,
                            "enabled": flames_controller.isFlameEffectEnabled(patternName),
                            "active" : flames_controller.isFlameEffectActive(patternName)})
    return {"globalState": (not flames_controller.isStopped()),
            "poofers":pooferList,
            "patterns":patternList }



def get_poofer_status(poofer_id):
    # there's enabled, and there's active (whether it's currently on)
    pooferStatus = {"enabled": flames_controller.isPooferEnabled(poofer_id),
                    "active" : flames_controller.isPooferActive(poofer_id)}
    return pooferStatus

def get_pattern_status(patternName):
    patternStatus = {"enabled": flames_controller.isFlameEffectEnabled(patternName),
                     "active" : flames_controller.isFlameEffectActive(patternName)}
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
        
        mapping = integration.add_mapping(
            trigger_name, 
            trigger_value, 
            flame_sequence, 
            allow_override,
            trigger_value_min,
            trigger_value_max
        )
        return JSONResponse(json.dumps({'message': 'Mapping created', 'mapping': mapping}))

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
        
        if integration.update_mapping(mapping_id, trigger_name, trigger_value, 
                                      flame_sequence, allow_override,
                                      trigger_value_min, trigger_value_max):
            return CORSResponse("Mapping updated", 200)
        else:
            return CORSResponse("Mapping not found", 404)
    
    else:  # GET
        mappings = integration.get_mappings()
        for mapping in mappings:
            if mapping['id'] == mapping_id:
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
