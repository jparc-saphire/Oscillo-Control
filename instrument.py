"""TEXIO DCS-2000E socket commands and screen/waveform decoding."""

from array import array
from contextlib import contextmanager
import math
import socket
import struct
import sys
from threading import Lock
import zlib


WIDTH, HEIGHT = 800, 480
CHANNELS = (1, 2, 3, 4)
MODELS = {"DCS-2104E", "DCS-2204E"}
SAMPLES_PER_DIVISION = 25
MAX_WAVEFORM_BYTES = 20_000_000


class ProtocolError(RuntimeError):
    pass


class Session:
    def __init__(self, socket_, reader):
        self.socket = socket_
        self.reader = reader

    def send(self, command):
        self.socket.sendall(command.encode("ascii") + b"\n")

    def line(self, limit=1024):
        reply = self.reader.readline(limit + 1)
        if not reply or len(reply) > limit or not reply.endswith(b"\n"):
            raise ProtocolError("Invalid or incomplete oscilloscope response")
        try:
            return reply.decode("ascii").strip()
        except UnicodeDecodeError as error:
            raise ProtocolError("Expected a text response from the oscilloscope") from error

    def query(self, command):
        self.send(command)
        return self.line()

    def block(self, max_size):
        prefix = self.reader.read(2)
        if len(prefix) != 2 or prefix[:1] != b"#" or not b"1" <= prefix[1:] <= b"9":
            raise ProtocolError("Invalid binary block header")
        width = int(prefix[1:])
        digits = self.reader.read(width)
        if len(digits) != width or not digits.isdigit():
            raise ProtocolError("Invalid binary block length")
        size = int(digits)
        if not 0 < size <= max_size:
            raise ProtocolError(f"Unexpected binary block size: {size}")
        data = self.reader.read(size)
        if len(data) != size:
            raise ProtocolError("Incomplete binary block")
        end = self.reader.read(1)
        if end == b"\r":
            end = self.reader.read(1)
        if end != b"\n":
            raise ProtocolError("Binary block is missing its LF terminator")
        return data


def read_number(text):
    try:
        value = float(text)
    except (TypeError, ValueError) as error:
        raise ProtocolError(f"Expected a number from the oscilloscope: {text!r}") from error
    if not math.isfinite(value):
        raise ProtocolError("Non-finite numeric response")
    return value


def requested_number(value, lower, upper):
    if type(value) not in (str, int, float):
        raise ValueError("Enter a number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError("Enter a number") from error
    if not math.isfinite(number) or not lower <= number <= upper:
        raise ValueError(f"Value must be between {lower:g} and {upper:g}")
    return f"{number:.12g}"


def channel_number(value):
    if type(value) is not int or value not in CHANNELS:
        raise ValueError("Choose CH1 through CH4")
    return value


def choice(value, allowed):
    if not isinstance(value, str) or value.upper() not in allowed:
        raise ValueError("Choose one of: " + ", ".join(allowed))
    return value.upper()


def read_identity(session):
    identity = session.query("*IDN?").split(",")
    if (len(identity) < 4 or identity[0].strip().upper() != "TEXIO"
            or identity[1].strip().upper() not in MODELS):
        raise ProtocolError("The address did not identify as a supported TEXIO four-channel scope")
    return {"model": identity[1].strip(), "firmware": identity[3].strip()}


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def screen_png(runs):
    """Decode the little-endian RGB565 RLE format in manual §3-7-9."""
    if not runs or len(runs) % 4:
        raise ProtocolError("Invalid screen data length")

    pixels = WIDTH * HEIGHT
    rgb = bytearray()
    for count, color in struct.iter_unpack("<HH", runs):
        if len(rgb) // 3 + count > pixels:
            raise ProtocolError("Decoded screen exceeds its dimensions")
        pixel = bytes(((color >> 11) * 255 // 31,
                       ((color >> 5) & 63) * 255 // 63,
                       (color & 31) * 255 // 31))
        rgb.extend(pixel * count)

    if len(rgb) != pixels * 3:
        raise ProtocolError("Incomplete screen")
    stride = WIDTH * 3
    rows = b"".join(b"\0" + rgb[i:i + stride] for i in range(0, len(rgb), stride))
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
            + png_chunk(b"IDAT", zlib.compress(rows, 3)) + png_chunk(b"IEND", b""))


class Waveform:
    def __init__(self, header, block):
        try:
            self.interval = read_number(header["Sampling Period"])
            self.scale = read_number(header["Vertical Scale"]) / SAMPLES_PER_DIVISION
            declared_samples = int(header["Memory Length"])
            self.unit = header["Vertical Units"]
        except (KeyError, ValueError) as error:
            raise ProtocolError("Incomplete waveform metadata") from error
        if self.interval <= 0 or self.scale <= 0 or not self.unit or len(block) != declared_samples * 2:
            raise ProtocolError("Inconsistent waveform metadata or sample count")
        self.samples = array("h")
        self.samples.frombytes(block)
        # DCS-2204E waveform samples are signed big-endian shorts.
        if sys.byteorder == "little":
            self.samples.byteswap()

    def preview(self, bins=800):
        """Keep minima and maxima in time order so brief pulses remain visible."""
        samples = self.samples
        step = max(1, math.ceil(len(samples) / bins))
        points = []
        for start in range(0, len(samples), step):
            batch = samples[start:start + step]
            low = batch.index(min(batch))
            high = batch.index(max(batch))
            for offset in sorted({low, high}):
                points.append([(start + offset) * self.interval, batch[offset] * self.scale])
        return {"count": len(samples), "interval": self.interval, "unit": self.unit, "points": points}


NUMERIC_ACTIONS = {
    "channel-scale": (":CHANnel{channel}:SCALe", 1e-6, 1e6),
    "channel-position": (":CHANnel{channel}:POSition", -1e6, 1e6),
    "time-scale": (":TIMebase:SCALe", 1e-9, 100),
    "time-position": (":TIMebase:POSition", -1e6, 1e6),
    "trigger-level": (":TRIGger:LEVel", -1e6, 1e6),
}

CHOICE_ACTIONS = {
    "trigger-source": (":TRIGger:SOURce", ("CH1", "CH2", "CH3", "CH4", "EXT", "LINE")),
    "trigger-slope": (":TRIGger:EDGe:SLOP", ("RISE", "FALL", "EITHER")),
    "trigger-mode": (":TRIGger:MODe", ("AUTO", "NORMAL")),
}
ACQUISITION = {"run": ":RUN", "stop": ":STOP", "single": ":SINGle"}


class Oscilloscope:
    def __init__(self, address, port, timeout=5):
        self.address = address
        self.port = port
        self.timeout = timeout
        self.lock = Lock()

    @contextmanager
    def connection(self):
        with self.lock, socket.create_connection((self.address, self.port), self.timeout) as conn:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with conn.makefile("rb") as reader:
                session = Session(conn, reader)
                identity = read_identity(session)
                yield session, identity

    def state(self):
        with self.connection() as (session, identity):
            query = session.query
            channels = []
            for ch in CHANNELS:
                prefix = f":CHANnel{ch}:"
                channels.append({
                    "enabled": query(prefix + "DISPlay?") == "ON",
                    "scale": read_number(query(prefix + "SCALe?")),
                    "position": read_number(query(prefix + "POSition?")),
                })
            kind = query(":TRIGger:TYPe?").upper()
            return {
                **identity, "channels": channels,
                "time_scale": read_number(query(":TIMebase:SCALe?")),
                "time_position": read_number(query(":TIMebase:POSition?")),
                "trigger": {
                    "type": kind,
                    "source": query(":TRIGger:SOURce?").upper(),
                    "slope": query(":TRIGger:EDGe:SLOP?").upper() if kind == "EDGE" else None,
                    "level": read_number(query(":TRIGger:LEVel?")),
                    "mode": query(":TRIGger:MODe?").upper(),
                },
            }

    def screenshot(self):
        with self.connection() as (session, _):
            session.send(":DISPlay:OUTPut?")
            block = session.block(WIDTH * HEIGHT * 4)
        return screen_png(block)

    def waveform(self, channel):
        channel_number(channel)
        with self.connection() as (session, _):
            if session.query(f":ACQuire{channel}:STATe?") not in ("1", "+1"):
                raise ProtocolError(f"CH{channel} has no acquired waveform yet")
            if session.query(":HEADer?").upper() != "ON":
                raise ProtocolError("Enable waveform headers on the instrument before exporting samples")
            session.send(f":ACQuire{channel}:MEMory?")
            line = session.line(8192)
            header = dict(field.split(",", 1) for field in line.split(";") if "," in field)
            block = session.block(MAX_WAVEFORM_BYTES)
        return Waveform(header, block)

    def operate(self, action, channel=None, value=None):
        if not isinstance(action, str):
            raise ValueError("Select an operation")
        numeric = action in NUMERIC_ACTIONS
        if numeric:
            command, lower, upper = NUMERIC_ACTIONS[action]
            if "{channel}" in command:
                command = command.format(channel=channel_number(channel))
            setting = requested_number(value, lower, upper)
        elif action in CHOICE_ACTIONS:
            command, allowed = CHOICE_ACTIONS[action]
            setting = choice(value, allowed)
        elif action == "channel-display":
            command = f":CHANnel{channel_number(channel)}:DISPlay"
            setting = choice(value, ("ON", "OFF"))
        elif action == "trigger-edge":
            command, setting = ":TRIGger:TYPe", "EDGE"
        elif action in ACQUISITION:
            command, setting = ACQUISITION[action], None
        else:
            raise ValueError("Unknown operation")

        with self.connection() as (session, _):
            if action == "trigger-slope" and session.query(":TRIGger:TYPe?").upper() != "EDGE":
                raise ValueError("Select edge triggering before changing the slope")
            if setting is None:
                session.send(command)
                # The front panel shows the acquisition state. A query synchronizes the
                # command stream without waiting for a SINGLE acquisition to trigger.
                read_identity(session)
                return None
            session.send(f"{command} {setting}")
            current = session.query(command + "?")
            return read_number(current) if numeric else current.upper()
