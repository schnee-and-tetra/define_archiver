# Privacy Policy

## Overview

`define_archiver` is an open-source Dify Plugin that provides archive creation and archive inspection features.

This plugin processes user-provided content within the user's Dify environment. The plugin does not collect, sell, or transmit user data to external services.

## Data Processing

`define_archiver` processes only the data required to perform requested operations.

Depending on the tool being used, processed data may include:

* User-provided text content
* Archive file data provided for inspection
* File names and archive paths supplied by the workflow

The plugin uses this information only for generating or inspecting archives.

## Data Storage

During archive generation, temporary data may be stored in the Dify Plugin storage system.

Temporary stored data may include:

* Archive metadata
* Compressed temporary content chunks
* Hash values used for content identification and integrity checks

Temporary data is used only during the archive processing lifecycle.

## Data Retention

`define_archiver` does not intentionally retain user content after processing is completed.

Temporary data is automatically removed after successful archive finalization.

In case of execution failure, temporary data retention depends on the storage lifecycle and management settings of the user's Dify environment.

## External Communication

This plugin does not send processed data to:

* External servers
* Analytics services
* Tracking systems
* Third-party storage services

All archive processing is performed locally within the user's Dify deployment environment.

## Logging

The plugin may output technical logs required for debugging and operation.

Logs may include:

* Execution status
* Dify runtime identifiers
* Error messages

The plugin does not intentionally record:

* User document contents
* Archive binary contents
* Personal information contained in processed data

## User Responsibility

Users are responsible for ensuring that their Dify environment is properly configured for their security requirements.

This includes:

* Access control management
* Storage security
* Handling of generated archives
* Compliance with applicable privacy and data protection regulations

Users should verify that their workflow configuration is appropriate for the data they process.

## Open Source Software

`define_archiver` uses open-source libraries for archive processing and compression.

These libraries operate within the plugin execution environment and are subject to their respective licenses.

## Policy Updates

This Privacy Policy may be updated when plugin functionality changes.

The latest version is maintained together with the plugin source code.

## Contact

For questions, bug reports, or security concerns, please use the official project repository issue tracker.
- [@schnee-and-tetra on GitHub](https://github.com/schnee-and-tetra)
