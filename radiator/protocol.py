"""Minimal BS2 Pro HID framing. See docs/RESEARCH.md for references."""


def build_report(command, payload=b"", size=23):
    payload = bytes(payload)
    length = 2 + len(payload)
    frame = bytes((0x5A, 0xA5, command, length)) + payload
    frame += bytes(((command + length + sum(payload)) & 255,))
    report = b"\x02" + frame
    if len(report) > size:
        raise ValueError("Report too long")
    return report.ljust(size, b"\0")


def parse_report(data):
    data = bytes(data)
    offset = 0 if data[:2] == b"\x5a\xa5" else 1
    frame = data[offset:]
    if len(frame) < 5 or frame[:2] != b"\x5a\xa5":
        return None
    length = frame[3]
    if length < 2 or len(frame) < length + 3:
        return None
    if sum(frame[2:2 + length]) & 255 != frame[2 + length]:
        return None
    return frame[2], frame[4:2 + length]
