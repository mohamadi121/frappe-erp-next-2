EXECUTORS = {}
EXECUTORS["asset_movement"] = __import__(__name__ + ".asset_movement", fromlist=["asset_movement"])
