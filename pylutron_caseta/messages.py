"""Models for messages exchanged with the bridge."""

from typing import NamedTuple, Optional


class ResponseStatus:
    """A response status split into its code and message parts."""

    def __init__(self, code: Optional[int], message: str):
        """Create a new ResponseStatus."""
        self.code = code
        self.message = message

    @classmethod
    def from_str(cls, data: str) -> "ResponseStatus":
        """Convert a str to a ResponseStatus."""
        space = data.find(" ")
        if space == -1:
            code = None
        else:
            try:
                code = int(data[:space])
                data = data[space + 1 :]
            except ValueError:
                code = None

        return ResponseStatus(code, data)

    def is_successful(self) -> bool:
        """Check if the status code is in the range [200, 300)."""
        return self.code is not None and self.code >= 200 and self.code < 300

    def __repr__(self):
        """Get a string representation of the ResponseStatus."""
        return f"ResponseStatus({self.code!r}, {self.message!r})"

    def __str__(self):
        """Format the response status as a string in the LEAP header format."""
        return f"{self.code} {self.message}"

    def __eq__(self, other):
        """Check if this ResponseStatus is equal to another ResponseStatus."""
        return (
            isinstance(other, ResponseStatus)
            and self.code == other.code
            and self.message == other.message
        )


class ResponseHeader(NamedTuple):
    """A LEAP response header."""

    # pylint: disable=invalid-name

    StatusCode: Optional[ResponseStatus] = None
    Url: Optional[str] = None
    MessageBodyType: Optional[str] = None

    @classmethod
    def from_json(cls, data: dict) -> "ResponseHeader":
        """Convert a JSON dictionary to a ResponseHeader."""
        status = data.get("StatusCode", None)
        StatusCode = ResponseStatus.from_str(status) if status is not None else None

        return ResponseHeader(
            StatusCode=StatusCode,
            Url=data.get("Url", None),
            MessageBodyType=data.get("MessageBodyType", None),
        )


class Response(NamedTuple):
    """A LEAP response."""

    # pylint: disable=invalid-name

    Header: ResponseHeader
    CommuniqueType: Optional[str] = None
    Body: Optional[dict] = {}

    @classmethod
    def from_json(cls, data: dict) -> "Response":
        """Convert a JSON dictionary to a Response."""
        return Response(
            Header=ResponseHeader.from_json(data.get("Header", {})),
            CommuniqueType=data.get("CommuniqueType", None),
            Body=data.get("Body", None),
        )
