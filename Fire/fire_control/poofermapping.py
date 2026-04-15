import json
import logging
from threading import Lock

logger = logging.getLogger('flames')

MAPPINGS_FILE = "poofer_mappings.json"
_lock = Lock()

# Default mappings used when no JSON file is present.
# First two chars of the address = board ID (hex); third char = channel.
# See: http://flg.waywardengineer.com/index.php?title=Bang_(!)_Protocol
_DEFAULTS = {
    'C1':     "011", 'C2': "012", 'C3': "013", 'C4': "014",
    'C5':     "015", 'C6': "016",
    'C_HAIR1':"017", 'C_HAIR2': "018",
    'C_HAIR3':"021", 'C_HAIR4': "022",
    'O_EYES': "031", 'O_WINGS': "032",
    'O1':     "033", 'O2': "034", 'O3': "035",
    'M_TAIL': "041", 'M1': "042", 'M2': "043", 'M3': "044",
    'P1':     "051", 'P2': "052", 'P3': "053", 'P4': "054",
}

# The live mappings dict. Updated in-place so that modules that imported it via
#   from poofermapping import mappings as pooferMapping
# see runtime changes without re-importing.
mappings = dict(_DEFAULTS)


def init(mappings_file=MAPPINGS_FILE):
    """Load poofer mappings from JSON, falling back to defaults if absent."""
    try:
        with open(mappings_file, 'r') as f:
            data = json.load(f)
        with _lock:
            mappings.clear()
            mappings.update(data)
        logger.info(f"Loaded {len(mappings)} poofer mappings from {mappings_file}")
    except FileNotFoundError:
        logger.info(f"No poofer mappings file at '{mappings_file}'; using defaults and saving.")
        save(mappings_file)
    except Exception as e:
        logger.error(f"Error loading poofer mappings from '{mappings_file}': {e}; using defaults")


def save(mappings_file=MAPPINGS_FILE):
    """Persist current mappings to JSON. Returns True on success."""
    try:
        with _lock:
            data = dict(mappings)
        with open(mappings_file, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
        logger.info(f"Saved {len(data)} poofer mappings to {mappings_file}")
        return True
    except Exception as e:
        logger.error(f"Error saving poofer mappings: {e}")
        return False


def get_all():
    """Return a sorted, thread-safe copy of all current mappings."""
    with _lock:
        return dict(sorted(mappings.items()))


def validate_address(address):
    """Return True if address is a valid 3-character board+channel string.
    Format: 2-char hex board address + 1-char alphanumeric channel (e.g. '011', '02A').
    """
    if not isinstance(address, str) or len(address) != 3:
        return False
    try:
        int(address[:2], 16)   # board portion must be hex
    except ValueError:
        return False
    return address[2].isalnum()


def update_mapping(name, address):
    """Add or update a poofer → board address mapping.

    name    - poofer name, e.g. 'C1'
    address - 3-char string: 2-char hex board + 1-char channel, e.g. '011'

    Raises ValueError for empty name or invalid address format.
    Persists to JSON automatically.
    """
    if not name or not name.strip():
        raise ValueError("Poofer name must not be empty")
    if not validate_address(address):
        raise ValueError(
            f"Address {address!r} is invalid. "
            "Must be exactly 3 characters: 2-char hex board address + 1-char channel "
            "(e.g. '011' = board 01, channel 1)."
        )
    with _lock:
        mappings[name] = address
    save()
    logger.info(f"Updated poofer mapping: {name!r} -> {address!r}")


def delete_mapping(name):
    """Remove a poofer mapping by name. Returns True if found and deleted."""
    with _lock:
        if name not in mappings:
            return False
        del mappings[name]
    save()
    logger.info(f"Deleted poofer mapping: {name!r}")
    return True


def reset_to_defaults(mappings_file=MAPPINGS_FILE):
    """Reset all mappings back to the built-in defaults and persist to JSON."""
    with _lock:
        mappings.clear()
        mappings.update(_DEFAULTS)
    save(mappings_file)
    logger.info("Reset poofer mappings to defaults")
