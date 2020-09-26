# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `set_value` (and shortcuts `turn_on` `turn_off`) now take an optional `fade_time` parameter taking a `timedelta` that controls the transition time for lights.
- Shades can be told to raise/lower/stop.

### Changed

- Methods that involve making requests to the Caséta bridge are now asyncio coroutines and must be awaited. Previously, the requests were async, but there was no way to observe the request once it was started.

## Removed

- Support for Python 3.5 and 3.6.

## [0.6.1] - 2020-04-08

### Fixed

- `OSError` is now handled the same as `ConnectionError` because Python sometimes raises `OSError` when it fails to make a connection.
- Users are no longer required to have occupancy sensors.

## [0.6.0] - 2020-03-22

### Added

- Support for occupancy sensors.

### Changed

- `get_lutron_cert.py` now uses LAP pairing instead of requiring Lutron cloud services.

### Fixed

- Associating a scene remote with Caséta no longer prevents pylutron_caseta from starting.

### Removed

- Support for Python 3.4.

## [0.5.1] - 2019-11-19

### Added

- Support for fans.

### Fixed

- TLS SNI is never sent to the Caséta bridge when connecting. The bridge responds with different certificates when SNI is sent, which was causing some users problems with the pairing process.
- Reconnecting after network errors should be more robust.
- pylutron_caseta no longer defaults its own log level to debug.

## [0.5.0] - 2018-04-17

### Added

- An updated version of `get_lutron_cert.py` is now included in the repository. This script is used for pairing with the Caséta bridge.

### Fixed

- Unexpected messages sent by the Caséta bridge during startup no longer prevent pylutron_caseta from initializing.

## [0.4.0] - 2018-03-26

### Changed

- Device names now include the name of the room containing the device.

## [0.3.0] - 2017-11-01

### Changed

- pylutron_caseta now uses LEAP over TLS for connecting to the Caséta bridge. SSH support is removed from pylutron_caseta, matching the removal of SSH support from the Caséta firmware.

## [0.2.8] - 2017-09-01

### Added

- `get_devices_by_domain` returns all devices of a given domain (a domain contains similar device types).

## [0.2.7] - 2017-07-28

### Added

- Support for scenes.

## [0.2.6] - 2017-04-17

### Changed

- pylutron_caseta no longer uses LIP over telnet for communicating with the Caséta bridge.

### Fixed

- Event subscribers are actually notified.

## [0.2.5] - 2017-04-02

### Added

- `get_devices_by_types` returns all devices having one of multiple given types.

## [0.2.4] - 2017-03-27

### Fixed

- paramiko is now automatically installed along with pylutron_caseta.

## [0.2.3] - 2017-03-20

### Added

- `get_devices_by_type` returns all devices of the given type.

## [0.2.0] - 2017-03-16

### Fixed

- Initial device state is no longer unknown.
- Unexpected telnet messages are handled.
- Importing pylutron_caseta no longer enables logging to stdout.

## [0.1.6] - 2017-03-15

### Added

- Ability to subscribe to changes in device state.

## [0.1.0] - 2017-03-15

### Added

- Ability to interact with Caséta bridge using LIP over Telnet and LEAP over SSH.

[unreleased]: https://github.com/gurumitts/pylutron-caseta/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/gurumitts/pylutron-caseta/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/gurumitts/pylutron-caseta/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.2.8...v0.3.0
[0.2.8]: https://github.com/gurumitts/pylutron-caseta/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/gurumitts/pylutron-caseta/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/gurumitts/pylutron-caseta/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/gurumitts/pylutron-caseta/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/gurumitts/pylutron-caseta/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/gurumitts/pylutron-caseta/compare/v0.2.0...v0.2.3
[0.2.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.1.6...v0.2.0
[0.1.6]: https://github.com/gurumitts/pylutron-caseta/compare/0.1.0...v0.1.6
[0.1.0]: https://github.com/gurumitts/pylutron-caseta/releases/tag/0.1.0
