# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Optional callback for connection establishment.
- Support for SerenaEssentialsRollerShade.

## [0.23.0] - 2025-01-05

### Added

- Support for Lumaris RGB + Tunable White Tape Light.
- Support for wood tilt blinds (Sivoia?).

## [0.22.0] - 2024-10-04

### Added

- Support for Triathalon Essentials roller shades.

## [0.21.1] - 2024-08-11

### Fixed

- Connecting to the bridge no longer does blocking file I/O in the async event loop.

## [0.21.0] - 2024-07-04

### Added

- Support for PowPak0-10V dimmers.

## [0.20.0] - 2024-02-22

### Added

- Support for over 99 areas.

### Fixed

- An error would occur if a button group contained no buttons.

## [0.19.0] - 2024-01-27

### Added

- Support for Lumaris Tape Light and Ketra color.

## [0.18.3] - 2023-10-07

### Fixed

- Reconnecting could sometimes fail.

## [0.18.2] - 2023-09-03

### Added

- Support for Palladiom Wire-Free shades.

### Fixed

- Restored support for Wall Mounted Motion Sensor on RA3 23.4 firmware.

## [0.18.1] - 2023-02-03

### Fixed

- Increased maximum message size for compatibility with 22.08.16f000 firmware.

## [0.18.0] - 2022-01-17

### Added

- Support for Sunnata hybrid keypads.

## [0.17.1] - 2022-10-23

### Fixed

- Now discovers the complete area list with working parent_area relationship.

## [0.17.0] - 2022-10-18

### Added

- Support for RadioRA 2 PhantomKeypad.

### Fixed

- leap-scan now detects devices besides Caseta.

## [0.16.0] - 2022-09-28

### Changed

- The `name` field on QSX and RadioRA 3 devices now more closely matches the format of the name field on Caseta devices.

### Added

- Devices now have an `area` field containing the area ID and a `device_name` field containing the name of the device without any prefixes or suffixes added by this library. These fields should be used instead of trying to parse the same values out of the `name` field.

## [0.15.2] - 2022-09-19

### Added

- Support for new Claro and Diva devices on Caseta.

## [0.15.1] - 2022-09-10

### Changed

- To match the previous behavior with Caseta, the `name` field on the button devices created for QSX and RadioRA 3 no longer contains the button name. The button name is still available in the `button_name` field.

## [0.15.0] - 2022-09-10

### Added

- Support for HomeWorks QSX and RadioRA 3.
- Support for RadioRA 2 InLineDimmer and InLineSwitch.

## [0.14.0] - 2022-06-18

### Added

- Support for Serena tilt-only wood blinds.
- New command line tools: lap-pair, leap-scan, leap.
- Occupancy sensors are linked using `device['occupancy_sensors']` and `group['sensors']`.

### Removed

- get_lutron_cert.py. Use lap-pair instead. See README.md for details.

### Fixed

- `async_pair` works on Windows.

## [0.13.1] - 2022-02-01

### Fixed

- No longer fails to initialize when no buttons are associated with the bridge.

## [0.13.0] - 2021-12-05

### Added

- Support for remotes that have multiple button groups (eg Serena RF 4-group Remote).

### Changed

- The `buttongroup` member of of a device has been replaced with `button_groups`.

## [0.12.1] - 2021-12-05

### Fixed

- No longer fails to initialize when a remote with multiple button groups (eg Serena RF 4-group Remote) is detected. Only the buttons in the first group are available until 0.13.0.

## [0.12.0] - 2021-12-04

### Added

- Pico Remote button status and event handlers.

## [0.11.0] - 2021-06-01

### Added

- Support for 15-AMP Plug-in Appliance Module (RR-15APS-1-XX).

## [0.10.0] - 2021-05-22

### Added

- Support for PD-15OUT outdoor switch.
- Support for RA2 Select fan controller.

## [0.9.0] - 2021-01-23

### Added

- `bridge.lip_devices` can be used to obtain information about paired Pico remotes (PRO and RASelect2 hubs only).

## [0.8.0] - 2021-01-17

### Added

- `pylutron_caseta.pairing.async_pair` can be used to generate the authentication certificates, similar to using the `get_lutron_cert.py` file. This enables software like Home Assistant to perform pairing from inside Home Assistant.

## [0.7.2] - 2020-11-10

### Changed

- Instances in the `areas` and `occupancy_groups` dictionaries are no longer replaced during reconnection, which can cause surprise issues after a network interruption or bridge restart in consuming software such as Home Assistant. This is consistent with the `devices` dictionary.

## [0.7.1] - 2020-11-01

### Fixed

- If the bridge does not return information about occupancy groups, pylutron_caseta will still initialize.
- Occupancy groups are now subscribed correctly.

## [0.7.0] - 2020-10-03

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

[unreleased]: https://github.com/gurumitts/pylutron-caseta/compare/v0.23.0...HEAD
[0.23.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.21.1...v0.22.0
[0.21.1]: https://github.com/gurumitts/pylutron-caseta/compare/v0.21.0...v0.21.1
[0.21.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.18.3...v0.19.0
[0.18.3]: https://github.com/gurumitts/pylutron-caseta/compare/v0.18.2...v0.18.3
[0.18.2]: https://github.com/gurumitts/pylutron-caseta/compare/v0.18.1...v0.18.2
[0.18.1]: https://github.com/gurumitts/pylutron-caseta/compare/v0.18.0...v0.18.1
[0.18.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.17.1...v0.18.0
[0.17.1]: https://github.com/gurumitts/pylutron-caseta/compare/v0.17.0...v0.17.1
[0.17.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.15.2...v0.16.0
[0.15.2]: https://github.com/gurumitts/pylutron-caseta/compare/v0.15.1...v0.15.2
[0.15.1]: https://github.com/gurumitts/pylutron-caseta/compare/v0.15.0...v0.15.1
[0.15.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.13.1...v0.14.0
[0.13.1]: https://github.com/gurumitts/pylutron-caseta/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/gurumitts/pylutron-caseta/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.7.2...v0.8.0
[0.7.2]: https://github.com/gurumitts/pylutron-caseta/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/gurumitts/pylutron-caseta/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/gurumitts/pylutron-caseta/compare/v0.6.1...v0.7.0
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
