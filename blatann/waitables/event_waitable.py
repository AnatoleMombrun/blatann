from blatann.waitables.waitable import Waitable


class EventWaitable(Waitable):
    def __init__(self, event):
        """
        :type event: blatann.event_type.Event
        """
        super(EventWaitable, self).__init__()
        self._event = event
        self._event.register(self._on_event)

    def _on_event(self, *args):
        self._event.deregister(self._on_event)
        self._notify(*args)

    def _on_timeout(self):
        self._event.deregister(self._on_event)

    def wait(self, timeout=None, exception_on_timeout=True):
        res = super(EventWaitable, self).wait(timeout, exception_on_timeout)
        if res is None:  # Timeout, send None, None for the sender and event_args
            return None, None
        return res
