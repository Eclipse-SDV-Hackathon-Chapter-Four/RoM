# Notices for RoM: Battery Thermal Guardian (Safety Evidence Factory)

This content is produced and maintained by the contributors of the Eclipse SDV Hackathon Chapter Four team RoM.

## Trademarks

Eclipse KUKSA, Eclipse uProtocol, Eclipse OpenSOVD, Eclipse Ankaios, Eclipse Zenoh, Eclipse Mosquitto, Eclipse ThreadX,
Eclipse iceoryx and Eclipse are trademarks of the Eclipse Foundation.

## Copyright

All content is the property of the respective authors or their employers.
For more information regarding authorship of content, please consult the listed source code repository logs.

## Declared Project Licenses

This program and the accompanying materials are made available under the terms of the Apache License, Version 2.0,
which is available at https://www.apache.org/licenses/LICENSE-2.0.

SPDX-License-Identifier: Apache-2.0

## Source Code

The project maintains the following source code repositories:

- https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/RoM

## Third-party Content

Dependencies are declared in `requirements.txt`, the `pyproject.toml` files, `services/dashboard/package-lock.json` and
the `Cargo.toml` / `Cargo.lock` files; each is used under its own license.

Vendored or bundled content under `MXChip/AZ3166/` (STM32Cube HAL / CMSIS, Eclipse ThreadX and NetX Duo
submodules) remains under the licenses stated in those files and directories. The WICED SDK (prebuilt Wi-Fi driver) is not
in this repository: the firmware build downloads it from https://github.com/eclipse-threadx/getting-started at a pinned
commit (`MXChip/AZ3166/lib/CMakeLists.txt`).

## Cryptography

Content may contain encryption software. The country in which you are currently may have restrictions on the import,
possession, and use, and/or re-export to another country, of encryption software. BEFORE using any encryption software,
please check the country's laws, regulations and policies concerning the import, possession, or use, and re-export of
encryption software, to see if this is permitted.
