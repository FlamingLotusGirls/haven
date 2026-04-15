'''Flame controller. Responsible for high-level management of flame effects. All objects
or modules wanting to know the status of poofers or sequences should call into this module.
Similarly, all objects or modules wanting to change the status of poofers or sequences -
including running a sequence - should call into this module.

Mediates with the low-level flames_drv via a message Queue (flameQueue, for pushing
commands to the low level code) and event listener (for receiving events created by the
flames driver)

Note that at the moment, many event types are not getting created. A more solid architecture
would use the event queue to set state rather than setting state off of the command. But
that seems like a nicety that I can ignore for now.'''

import queue
import json
import logging
import time
from threading import Thread
from threading import Lock
import mock_event_producer as mockDriver
import event_manager
import pattern_manager

#logging.basicConfig()
logger = logging.getLogger("flames")

cmdQueue   = None       # requests from upper level
disabledPoofers = list()
activePoofers = list()
globalEnable = True
disabledFlameEffects = list()
activeFlameEffects = list()
gUseDriver = False

# ── Autonomous loop support ────────────────────────────────────────────────────
_loop_manager = None   # set in init()


class LoopManagerThread(Thread):
    """Background thread that re-fires named flame effects at a fixed interval.

    This provides the 'autonomous pattern' capability needed for scene modes
    like the Shooter, where a repeating chase or burst runs in the background
    independently of trigger events.
    """

    TICK = 0.05   # seconds between loop checks (50 ms resolution)

    def __init__(self):
        Thread.__init__(self)
        self.daemon = True
        self.name = 'flame-loop-manager'
        self._running = False
        self._lock = Lock()
        # { pattern_name: {'interval_ms': int, 'next_fire_time': float} }
        self._looping = {}

    def run(self):
        self._running = True
        logger.info("LoopManagerThread started")
        while self._running:
            now = time.time()
            with self._lock:
                due = [(name, dict(info))
                       for name, info in self._looping.items()
                       if now >= info['next_fire_time']]

            for name, info in due:
                if name not in disabledFlameEffects and globalEnable:
                    msg = {"cmdType": "flameEffectStart", "name": name}
                    if cmdQueue is not None:
                        cmdQueue.put(json.dumps(msg))
                        logger.debug(
                            f"LoopManager: re-firing '{name}' "
                            f"(period={info['period_ms']} ms, mode={info['mode']})"
                        )
                with self._lock:
                    if name in self._looping:
                        self._looping[name]['next_fire_time'] = (
                            now + info['period_ms'] / 1000.0
                        )

            time.sleep(self.TICK)
        logger.info("LoopManagerThread stopped")

    @staticmethod
    def _pattern_duration_ms(name):
        """Return the wall-clock duration of a pattern in milliseconds.

        Duration = max(startTime + duration) across all events.
        Times in the pattern JSON are in *seconds* (despite the old doc saying ms),
        so multiply by 1000 to get ms.
        Returns 0 if the pattern cannot be found or has no events.
        """
        try:
            pattern = pattern_manager.getPattern(name)
            if not pattern or not pattern.get("events"):
                return 0
            return int(
                max(
                    e.get("startTime", 0) + e.get("duration", 0)
                    for e in pattern["events"]
                ) * 1000
            )
        except Exception:
            return 0

    def start_loop(self, name, interval_ms, gap_ms=0):
        """Start (or update) a looping effect.

        Two modes:
          interval_ms > 0, gap_ms == 0 (default):
              Repeat on a fixed clock of *interval_ms* milliseconds, clamped
              to at least (pattern_duration + 100 ms) so the pattern is never
              re-fired while still running.

          gap_ms >= 0, interval_ms == 0:
              Fire again *gap_ms* milliseconds after the pattern finishes.
              gap_ms = 0 means back-to-back with no pause.

        In either case the first fire happens immediately.
        """
        dur_ms = self._pattern_duration_ms(name)
        SAFETY_MS = 100   # buffer to avoid overlapping the tail of a pattern

        if interval_ms > 0:
            # Fixed-clock mode — clamp so we never overlap
            min_interval = dur_ms + SAFETY_MS
            effective_ms = max(int(interval_ms), min_interval)
            if effective_ms != int(interval_ms):
                logger.warning(
                    f"LoopManager: '{name}' repeat_interval {interval_ms} ms < "
                    f"pattern duration {dur_ms} ms — clamping to {effective_ms} ms"
                )
            period_ms = effective_ms
            mode = 'interval'
        else:
            # Gap-after-finish mode
            period_ms = dur_ms + int(gap_ms) + SAFETY_MS
            mode = 'gap'

        with self._lock:
            self._looping[name] = {
                'mode'             : mode,
                'period_ms'        : period_ms,
                'pattern_dur_ms'   : dur_ms,
                'requested_interval': int(interval_ms),
                'gap_ms'           : int(gap_ms),
                'next_fire_time'   : time.time(),   # fire immediately
            }
        logger.info(
            f"LoopManager: started loop '{name}' "
            f"(mode={mode}, period={period_ms} ms, pattern_dur={dur_ms} ms)"
        )

    def stop_loop(self, name):
        """Stop a looping effect (does not affect an already-in-flight pattern)."""
        with self._lock:
            removed = self._looping.pop(name, None)
        if removed:
            logger.info(f"LoopManager: stopped loop '{name}'")

    def stop_all_loops(self):
        """Stop all currently looping effects."""
        with self._lock:
            names = list(self._looping.keys())
            self._looping.clear()
        if names:
            logger.info(f"LoopManager: stopped all loops: {names}")

    def is_looping(self, name):
        with self._lock:
            return name in self._looping

    def get_all_loops(self):
        """Return a snapshot dict of loop info for all active loops.

        Each value is a dict with: mode, period_ms, pattern_dur_ms,
        requested_interval, gap_ms.
        """
        with self._lock:
            return {n: {k: v for k, v in info.items() if k != 'next_fire_time'}
                    for n, info in self._looping.items()}

    def shutdown(self):
        self._running = False


def init(flameQueue, useDriver=True):
    global cmdQueue
    global gUseDriver
    global _loop_manager
    logger.info("Flame Controller Init")
    cmdQueue = flameQueue
    gUseDriver = useDriver

    event_manager.addListener(eventHandler)

    _loop_manager = LoopManagerThread()
    _loop_manager.start()


def shutdown():
    global _loop_manager
    logger.info("Flame Controller Shutdown")
    if _loop_manager is not None:
        _loop_manager.shutdown()
        _loop_manager.join(timeout=2)
        _loop_manager = None


def doFlameEffect(flameEffectName):
    if not flameEffectName in disabledFlameEffects:
        flameEffectMsg = {"cmdType":"flameEffectStart", "name":flameEffectName}
        cmdQueue.put(json.dumps(flameEffectMsg))

def stopFlameEffect(flameEffectName):
    # Also stop any loop for this effect.
    if _loop_manager is not None:
        _loop_manager.stop_loop(flameEffectName)
    flameEffectMsg = {"cmdType":"flameEffectStop", "name":flameEffectName}
    cmdQueue.put(json.dumps(flameEffectMsg))

# ── Autonomous loop public API ─────────────────────────────────────────────────

def loopFlameEffect(flameEffectName, interval_ms=0, gap_ms=0):
    """Start repeating *flameEffectName* autonomously.

    Exactly one of the two modes should be used:

    interval_ms > 0  (fixed-clock mode):
        Re-fire every *interval_ms* ms, automatically clamped to at least
        (pattern_duration + 100 ms) so the pattern can never overlap itself.

    gap_ms >= 0, interval_ms == 0  (back-to-back mode):
        Re-fire *gap_ms* ms after the previous run ends.  gap_ms = 0 means
        literally back-to-back (with a 100 ms safety buffer).

    If both are 0 or both are > 0, ValueError is raised.
    """
    if interval_ms > 0 and gap_ms > 0:
        raise ValueError("Specify either repeat_interval or repeat_gap, not both")
    if interval_ms == 0 and gap_ms == 0:
        # default: back-to-back with no extra gap
        pass  # gap_ms=0 is valid "fire again immediately after pattern ends"
    if flameEffectName in disabledFlameEffects:
        raise ValueError(f"Cannot loop disabled flame effect '{flameEffectName}'")
    if _loop_manager is None:
        raise RuntimeError("LoopManager not initialised — call init() first")
    _loop_manager.start_loop(flameEffectName, interval_ms, gap_ms)

def stopLoopFlameEffect(flameEffectName):
    """Stop the autonomous loop for *flameEffectName* (does not abort in-flight pattern)."""
    if _loop_manager is not None:
        _loop_manager.stop_loop(flameEffectName)

def stopAllLoops():
    """Stop every autonomous loop.  Called on global pause or scene change."""
    if _loop_manager is not None:
        _loop_manager.stop_all_loops()

def isFlameEffectLooping(flameEffectName):
    return _loop_manager is not None and _loop_manager.is_looping(flameEffectName)

def getLoopingFlameEffects():
    """Return a dict of {pattern_name: interval_ms} for all active loops."""
    if _loop_manager is None:
        return {}
    return _loop_manager.get_all_loops()


def disableFlameEffect(flameEffectName):
    if not flameEffectName in disabledFlameEffects:
        disabledFlameEffects.append(flameEffectName)
    stopFlameEffect(flameEffectName)

def enableFlameEffect(flameEffectName):
    if flameEffectName in disabledFlameEffects:
        disabledFlameEffects.remove(flameEffectName)

def isFlameEffectActive(flameEffectName):
    return flameEffectName in activeFlameEffects

def isFlameEffectEnabled(flameEffectName):
    return not flameEffectName in disabledFlameEffects

def disablePoofer(pooferId):
    if not pooferId in disabledPoofers:
        disabledPoofers.append(pooferId)
        if gUseDriver:
            flameEffectMsg = {"cmdType":"pooferDisable", "name":pooferId}
            cmdQueue.put(json.dumps(flameEffectMsg))
        else:
            mockDriver.disablePoofer(pooferId)

def enablePoofer(pooferId):
    if pooferId in disabledPoofers:
        disabledPoofers.remove(pooferId)
        if gUseDriver:
            flameEffectMsg = {"cmdType":"pooferEnable", "name":pooferId}
            cmdQueue.put(json.dumps(flameEffectMsg))
        else:
            mockDriver.enablePoofer(pooferId)

def isPooferEnabled(pooferId):
    return not (pooferId in disabledPoofers)

def isPooferActive(pooferId):
    return pooferId in activePoofers

def globalPause():
    global globalEnable
    flameEffectMsg = {"cmdType":"stop"}
    globalEnable = False
    cmdQueue.put(json.dumps(flameEffectMsg))

def globalRelease():
    global globalEnable
    globalEnable = True
    flameEffectMsg = {"cmdType":"resume"}
    cmdQueue.put(json.dumps(flameEffectMsg))

def isStopped():
    return not globalEnable

def getDisabledPoofers():
    return disabledPoofers

def getDisabledFlameEffects():
    return disabledFlameEffects

def eventHandler(msg):
    msgType = msg["msgType"]
    id = msg["id"]
    if (msgType == "poofer_on"):
        if not id in activePoofers:
            activePoofers.append(id)
    elif (msgType == "poofer_off"):
        try:
            activePoofers.remove(id)
        except:
            pass

if __name__ == "__main__":
    import mock_event_producer
    import time
    import queue

    logging.basicConfig(format='%(asctime)-15s %(levelname)s %(module)s %(lineno)d:  %(message)s', level=logging.DEBUG)

    try:

        event_manager.init()
        mock_event_producer.init()
        init(queue.Queue())

        while(True):
            time.sleep(10)

    except Exception as e:
        print(f"Exception occurs! {e}")
    except KeyboardInterrupt:
        print("Keyboard Interrupt!")

    event_manager.shutdown()
    mock_event_producer.shutdown()
    logger.info("??? shutdown ???")
    shutdown()
