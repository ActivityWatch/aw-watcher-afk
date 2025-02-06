from evdev import InputDevice, ecodes, list_devices

def is_keyboard(capabilities):
    if ecodes.EV_KEY not in capabilities:
        return False

    key_codes = set(capabilities[ecodes.EV_KEY])

    required_keys = {ecodes.KEY_A, ecodes.KEY_Z, ecodes.KEY_ENTER}
    if not required_keys.issubset(key_codes):
        return False

    if ecodes.EV_REL in capabilities or ecodes.EV_ABS in capabilities:
        return False

    return True

def is_mouse(capabilities):
    if ecodes.EV_REL not in capabilities and ecodes.EV_ABS not in capabilities:
        return False

    if ecodes.EV_KEY in capabilities:
        key_events = capabilities[ecodes.EV_KEY]
        if ecodes.BTN_MOUSE in key_events or ecodes.BTN_LEFT in key_events:
            return True

    return False

def find_keyboards():

    for path in list_devices():
        try:
            dev = InputDevice(path)
            capabilities = dev.capabilities()

            if is_keyboard(capabilities):
                yield dev.fn
        except OSError:
            continue

def find_mice():

    for path in list_devices():
        try:
            dev = InputDevice(path)
            capabilities = dev.capabilities()

            if is_mouse(capabilities):
                yield dev.fn
        except OSError:
            continue
