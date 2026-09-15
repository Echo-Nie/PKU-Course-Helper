"""Test-only adapter keeping regression coverage of the historical CLI loops."""
import threading


class LegacyHarnessEngine:
    def __init__(self, config, password, stop_event, log):
        from autoelective.loop import run_iaaa_loop, run_elective_loop, recognizer
        from autoelective.config import AutoElectiveConfig
        from autoelective.environ import Environ
        self.targets = [run_iaaa_loop, run_elective_loop]
        self.recognizer = recognizer
        self.config = AutoElectiveConfig()
        self.environment = Environ()
        self.stop_event = stop_event
        self.failure = None

    def cancel(self):
        self.stop_event.set()

    def run(self):
        from autoelective.environ import EngineCancelled
        def guarded(target):
            try:
                target()
            except EngineCancelled:
                pass
            except BaseException as error:
                self.failure = error
                self.stop_event.set()
        threads = [threading.Thread(target=guarded, args=(target,), daemon=True) for target in self.targets]
        for thread in threads:
            thread.start()
        threads[1].join()
        self.stop_event.set()
        threads[0].join()
        if self.failure:
            raise self.failure

    def snapshot(self):
        from autoelective.desktop.runtime.worker import make_snapshot
        return make_snapshot(self.environment, self.config)

    def close(self):
        self.recognizer.model.closeSession()
