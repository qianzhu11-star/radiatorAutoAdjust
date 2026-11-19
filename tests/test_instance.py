import unittest
import uuid

from radiator.instance import ShowRequest, request_show


class ReopenWindowTests(unittest.TestCase):
    def test_signal_delivered_once_and_handle_cleaned_up(self):
        name = "Local\\BS2ProTest-" + uuid.uuid4().hex
        self.assertFalse(request_show(name))
        listener = ShowRequest(name)
        try:
            self.assertFalse(listener.requested())
            self.assertTrue(request_show(name))
            self.assertTrue(listener.requested())
            self.assertFalse(listener.requested())
        finally:
            listener.close()
        self.assertFalse(request_show(name))


if __name__ == "__main__":
    unittest.main()
