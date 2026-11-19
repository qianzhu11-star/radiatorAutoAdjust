import os


def normalize(path):
    return os.path.normcase(os.path.normpath(path)).casefold()


def active_games(games, processes):
    active = []
    for game in games:
        if not game.get("enabled", True):
            continue
        names = {x.casefold() for x in game.get("process_names", [])}
        paths = {normalize(x) for x in game.get("executables", [])}
        path_names = {os.path.basename(x).casefold() for x in game.get("executables", [])}
        for process in processes:
            name, path = process["name"].casefold(), process.get("path", "")
            if name in names or (path and normalize(path) in paths) or (not path and name in path_names):
                active.append(game["name"])
                break
    return active


class GearPolicy:
    def __init__(self, exit_delay=10):
        self.exit_delay = exit_delay
        self.last_active = None

    def desired(self, playing, now):
        if playing:
            self.last_active = now
            return 3
        if self.last_active is not None and now - self.last_active < self.exit_delay:
            return 3
        return 2
