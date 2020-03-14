"""Tests to validate ssl interactions."""
import asyncio
import pytest
from collections import namedtuple

import pylutron_caseta.leap

Pipe = namedtuple('Pipe', ('leap_reader', 'leap_writer',
                           'test_reader', 'test_writer'))


class _PipeTransport(asyncio.Transport):
    def __init__(self):
        super().__init__()
        self._closing = False
        self._extra = {}
        self.other = None
        self._protocol = None

    def close(self):
        self._closing = True
        self.other.get_protocol().connection_lost(None)

    def is_closing(self):
        return self._closing

    def pause_reading(self):
        self.other.get_protocol().pause_writing()

    def resume_reading(self):
        self.other.get_protocol().resume_writing()

    def abort(self):
        self.close()

    def can_write_eof(self):
        return False

    def get_write_buffer_size(self):
        return 0

    def get_write_buffer_limits(self):
        return (0, 0)

    def set_write_buffer_limits(self, high=None, low=None):
        raise NotImplementedError()

    def write(self, data):
        self.other.get_protocol().data_received(data)

    def writelines(self, list_of_data):
        for line in list_of_data:
            self.write(line)

    def write_eof(self):
        raise NotImplementedError()

    def set_protocol(self, protocol):
        self._protocol = protocol

    def get_protocol(self):
        return self._protocol


@pytest.fixture
def pipe(event_loop):
    """Create linked readers and writers for tests."""
    test_reader = asyncio.StreamReader(loop=event_loop)
    impl_reader = asyncio.StreamReader(loop=event_loop)
    test_protocol = asyncio.StreamReaderProtocol(test_reader, loop=event_loop)
    impl_protocol = asyncio.StreamReaderProtocol(impl_reader, loop=event_loop)
    test_pipe = _PipeTransport()
    impl_pipe = _PipeTransport()
    test_pipe.other = impl_pipe
    impl_pipe.other = test_pipe
    test_pipe.set_protocol(test_protocol)
    impl_pipe.set_protocol(impl_protocol)
    test_protocol.connection_made(test_pipe)
    impl_protocol.connection_made(impl_pipe)
    test_writer = asyncio.StreamWriter(test_pipe, test_protocol,
                                       test_reader, loop=event_loop)
    impl_writer = asyncio.StreamWriter(impl_pipe, impl_protocol, impl_reader,
                                       loop=event_loop)
    leap_reader = pylutron_caseta.leap.LeapReader(impl_reader)
    leap_writer = pylutron_caseta.leap.LeapWriter(impl_writer)
    return Pipe(leap_reader, leap_writer, test_reader, test_writer)


@pytest.mark.asyncio
async def test_read(pipe):
    """Test basic object reading."""
    pipe.test_writer.write(b'{"test": true}\r\n')
    result = await pipe.leap_reader.read()
    assert result == {'test': True}


@pytest.mark.asyncio
async def test_read_eof(pipe):
    """Test reading when EOF is encountered."""
    pipe.test_writer.close()
    result = await pipe.leap_reader.read()
    assert result is None


@pytest.mark.asyncio
async def test_read_invalid(pipe):
    """Test reading when invalid data is received."""
    pipe.test_writer.write(b'?')
    pipe.test_writer.close()
    with pytest.raises(ValueError):
        await pipe.leap_reader.read()


@pytest.mark.asyncio
async def test_write(pipe):
    """Test basic object writing."""
    pipe.leap_writer.write({'test': True})
    result = await pipe.test_reader.readline()
    assert result == b'{"test": true}\r\n'


@pytest.mark.asyncio
async def test_wait_for(pipe):
    """Test the wait_for method."""
    pipe.test_writer.write(b'{"test": true}\r\n')
    pipe.test_writer.write(b'{"CommuniqueType": "TheAnswerIs42"}\r\n')
    pipe.test_writer.write(b'{"CommuniqueType": "ReadRequest", '
                           b'"foo": "bar"}\r\n')
    result = await pipe.leap_reader.wait_for('ReadRequest')
    assert result == {'CommuniqueType': 'ReadRequest', 'foo': 'bar'}
