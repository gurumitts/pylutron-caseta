"""Tests to validate low-level network interactions."""
import asyncio
import json
from typing import AsyncGenerator, Iterable, NamedTuple, Tuple

import pytest
import pytest_asyncio

from pylutron_caseta import BridgeDisconnectedError
from pylutron_caseta.leap import LeapProtocol
from pylutron_caseta.messages import Response, ResponseHeader, ResponseStatus


class Pipe(NamedTuple):
    """A LeapProtocol that communicates to a stream reader/writer pair."""

    leap: LeapProtocol
    leap_loop: asyncio.Task
    test_reader: asyncio.StreamReader
    test_writer: asyncio.StreamWriter


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

    def is_closing(self) -> bool:
        return self._closing

    def pause_reading(self):
        self.other.get_protocol().pause_writing()

    def resume_reading(self):
        self.other.get_protocol().resume_writing()

    def abort(self):
        self.close()

    def can_write_eof(self) -> bool:
        return False

    def get_write_buffer_size(self) -> int:
        return 0

    def get_write_buffer_limits(self) -> Tuple[int, int]:
        """Return (0, 0)."""
        return (0, 0)

    def set_write_buffer_limits(self, high=None, low=None):
        raise NotImplementedError()

    def write(self, data: bytes):
        self.other.get_protocol().data_received(data)

    def writelines(self, list_of_data: Iterable[bytes]):
        for line in list_of_data:
            self.write(line)

    def write_eof(self):
        raise NotImplementedError()

    def set_protocol(self, protocol: asyncio.BaseProtocol):
        self._protocol = protocol

    def get_protocol(self) -> asyncio.BaseProtocol:
        return self._protocol


@pytest_asyncio.fixture(name="pipe")
async def fixture_pipe() -> AsyncGenerator[Pipe, None]:
    """Create linked readers and writers for tests."""
    test_reader = asyncio.StreamReader()
    impl_reader = asyncio.StreamReader()
    test_protocol = asyncio.StreamReaderProtocol(test_reader)
    impl_protocol = asyncio.StreamReaderProtocol(impl_reader)
    test_pipe = _PipeTransport()
    impl_pipe = _PipeTransport()
    test_pipe.other = impl_pipe
    impl_pipe.other = test_pipe
    test_pipe.set_protocol(test_protocol)
    impl_pipe.set_protocol(impl_protocol)
    test_protocol.connection_made(test_pipe)
    impl_protocol.connection_made(impl_pipe)
    test_writer = asyncio.StreamWriter(
        test_pipe, test_protocol, test_reader, asyncio.get_running_loop()
    )
    impl_writer = asyncio.StreamWriter(
        impl_pipe, impl_protocol, impl_reader, asyncio.get_running_loop()
    )

    leap = LeapProtocol(impl_reader, impl_writer)
    leap_task = asyncio.create_task(leap.run())

    yield Pipe(leap, leap_task, test_reader, test_writer)

    leap_task.cancel()


@pytest.mark.asyncio
async def test_call(pipe: Pipe):
    """Test basic call and response."""
    task = asyncio.create_task(pipe.leap.request("ReadRequest", "/test"))

    received = json.loads((await pipe.test_reader.readline()).decode("utf-8"))

    # message should contain ClientTag
    tag = received.get("Header", {}).pop("ClientTag", None)
    assert tag
    assert isinstance(tag, str)

    assert received == {"CommuniqueType": "ReadRequest", "Header": {"Url": "/test"}}

    response_obj = {
        "CommuniqueType": "ReadResponse",
        "Header": {"ClientTag": tag, "StatusCode": "200 OK", "Url": "/test"},
        "Body": {"ok": True},
    }
    response_bytes = f"{json.dumps(response_obj)}\r\n".encode("utf-8")
    pipe.test_writer.write(response_bytes)

    result = await task

    assert result == Response(
        Header=ResponseHeader(StatusCode=ResponseStatus(200, "OK"), Url="/test"),
        CommuniqueType="ReadResponse",
        Body={"ok": True},
    )


@pytest.mark.asyncio
async def test_read_eof(pipe):
    """Test reading when EOF is encountered."""
    pipe.test_writer.close()

    await pipe.leap_loop


@pytest.mark.asyncio
async def test_read_invalid(pipe):
    """Test reading when invalid data is received."""
    pipe.test_writer.write(b"?\r\n")

    with pytest.raises(json.JSONDecodeError):
        await pipe.leap_loop


@pytest.mark.asyncio
async def test_busy_close(pipe):
    """Test closing the session while there are in-flight requests."""
    task = asyncio.create_task(pipe.leap.request("ReadRequest", "/test"))

    await pipe.test_reader.readline()
    pipe.test_writer.close()
    await pipe.leap_loop
    pipe.leap.close()

    with pytest.raises(BridgeDisconnectedError):
        await task


@pytest.mark.asyncio
async def test_unsolicited(pipe):
    """Test subscribing and unsubscribing unsolicited message handlers."""
    handler1_message = None
    handler2_message = None
    handler2_called = asyncio.Event()

    def handler1(response):
        nonlocal handler1_message
        handler1_message = response

    def handler2(response):
        nonlocal handler2_message
        handler2_message = response
        handler2_called.set()

    pipe.leap.subscribe_unsolicited(handler1)
    pipe.leap.subscribe_unsolicited(handler2)

    response_dict = {
        "CommuniqueType": "ReadResponse",
        "Header": {"StatusCode": "200 OK", "Url": "/test"},
        "Body": {"Index": 0},
    }
    response_bytes = f"{json.dumps(response_dict)}\r\n".encode("utf-8")
    pipe.test_writer.write(response_bytes)
    response = Response.from_json(response_dict)

    await asyncio.wait_for(handler2_called.wait(), 1.0)
    handler2_called.clear()

    assert handler1_message == response, "handler1 did not receive correct message"
    assert handler2_message == response, "handler2 did not receive correct message"

    pipe.leap.unsubscribe_unsolicited(handler1)

    response_dict["Body"]["Index"] = 1
    response_bytes = f"{json.dumps(response_dict)}\r\n".encode("utf-8")
    pipe.test_writer.write(response_bytes)
    response = Response.from_json(response_dict)

    await asyncio.wait_for(handler2_called.wait(), 1.0)

    assert handler1_message != response, "handler1 was not unsubscribed"
    assert handler2_message == response, "handler2 did not receive correct message"


@pytest.mark.asyncio
async def test_subscribe_tagged(pipe: Pipe):
    """
    Test subscribing to a topic and receiving responses.

    Unlike with unsolicited subscriptions, when the client sends a SubscribeRequest,
    the server sends back all events related to that subscription with the same tag
    value.
    """
    handler_message = None
    handler_called = asyncio.Event()

    def handler(response):
        nonlocal handler_message
        handler_message = response
        handler_called.set()

    task = asyncio.create_task(pipe.leap.subscribe("/test", handler))

    received = json.loads((await pipe.test_reader.readline()).decode("utf-8"))

    # message should contain ClientTag
    tag = received.get("Header", {}).pop("ClientTag", None)
    assert tag
    assert isinstance(tag, str)

    assert received == {
        "CommuniqueType": "SubscribeRequest",
        "Header": {"Url": "/test"},
    }

    response_obj = {
        "CommuniqueType": "SubscribeResponse",
        "Header": {"ClientTag": tag, "StatusCode": "200 OK", "Url": "/test"},
        "Body": {"ok": True},
    }
    response_bytes = f"{json.dumps(response_obj)}\r\n".encode("utf-8")
    pipe.test_writer.write(response_bytes)

    result, received_tag = await task

    assert result == Response(
        Header=ResponseHeader(StatusCode=ResponseStatus(200, "OK"), Url="/test"),
        CommuniqueType="SubscribeResponse",
        Body={"ok": True},
    )
    assert received_tag == tag

    # Now that the client has subscribed, send an event to the handler.
    response_obj = {
        "CommuniqueType": "ReadResponse",
        "Header": {"ClientTag": tag, "StatusCode": "200 OK", "Url": "/test"},
        "Body": {"ok": True},
    }
    response_bytes = f"{json.dumps(response_obj)}\r\n".encode("utf-8")
    pipe.test_writer.write(response_bytes)

    await asyncio.wait_for(handler_called.wait(), 1.0)
    assert handler_message == Response(
        Header=ResponseHeader(StatusCode=ResponseStatus(200, "OK"), Url="/test"),
        CommuniqueType="ReadResponse",
        Body={"ok": True},
    )


@pytest.mark.asyncio
async def test_subscribe_tagged_404(pipe: Pipe):
    """Test subscribing to a topic that does not exist."""

    def _handler(_: Response):
        pass

    task = asyncio.create_task(pipe.leap.subscribe("/test", _handler))

    received = json.loads((await pipe.test_reader.readline()).decode("utf-8"))

    tag = received.get("Header", {}).pop("ClientTag", None)
    response_obj = {
        "CommuniqueType": "SubscribeResponse",
        "Header": {"ClientTag": tag, "StatusCode": "404 Not Found", "Url": "/test"},
    }
    response_bytes = f"{json.dumps(response_obj)}\r\n".encode("utf-8")
    pipe.test_writer.write(response_bytes)

    result, _ = await task

    assert result == Response(
        Header=ResponseHeader(StatusCode=ResponseStatus(404, "Not Found"), Url="/test"),
        CommuniqueType="SubscribeResponse",
        Body=None,
    )

    # The subscription should not be registered.
    assert {} == pipe.leap._tagged_subscriptions  # pylint: disable=protected-access
