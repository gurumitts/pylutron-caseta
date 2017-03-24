"""Tests to validate ssh interactions."""
import pylutron_caseta


def test_ssh_key():
    """Test split_entity_id."""
    assert pylutron_caseta._LUTRON_SSH_KEY is not None
