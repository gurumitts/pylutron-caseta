"""LEAP protocol layer."""

import asyncio
import json
import logging

_LOG = logging.getLogger(__name__)
_DEFAULT_LIMIT = 2 ** 16


@asyncio.coroutine
def open_connection(host=None, port=None, *,
                    loop=None, limit=_DEFAULT_LIMIT, **kwds):
    """Open a stream and wrap it with LEAP."""
    connection = yield from asyncio.open_connection(host, port, loop=loop,
                                                    limit=limit, **kwds)
    return LeapReader(connection[0]), LeapWriter(connection[1])


class LeapReader(object):
    """A wrapper for reading the LEAP protocol."""

    def __init__(self, reader):
        """Initialize the reader."""
        self._reader = reader

    def exception(self):
        """Get the exception."""
        return self._reader.exception()

    @asyncio.coroutine
    def read(self):
        """
        Read a single object.

        If EOF is received, return `None`.

        If invaid data is received, raise ValueError.
        """
        received = yield from self._reader.readline()
        if received == b'':
            return None
        _LOG.debug('received %s', received)
        try:
            return json.loads(received.decode('UTF-8'))
        except ValueError as err:
            _LOG.error("Invalid LEAP response: %s", received)
            self._reader.set_exception(err)
            raise err

    def at_eof(self):
        """Return `True` if the underlying stream is at EOF."""
        return self._reader.at_eof()


class LeapWriter(object):
    """A wrapper for writing the LEAP protocol."""

    def __init__(self, writer):
        """Initialize the writer."""
        self._writer = writer

    def close(self):
        """Close the underlying stream."""
        self._writer.close()

    @asyncio.coroutine
    def drain(self):
        """Let the underlying stream drain its buffer."""
        yield from self._writer.drain()

    def write(self, obj):
        """Write a single object."""
        text = json.dumps(obj).encode('UTF-8')
        _LOG.debug('sending %s', text)
        self._writer.write(text + b'\r\n')

    def write_eof(self):
        """Write EOF to the underlying stream."""
        self._writer.write_eof()
