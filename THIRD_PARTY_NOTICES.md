# Licensing, sources, and third-party notices

## Project license

Solar Inverter Cloud Bridge source code is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with a source file, You
can obtain one at https://mozilla.org/MPL/2.0/. The complete text is in
[LICENSE](LICENSE). This notice applies to the project's source files unless a
file explicitly identifies a different license for its content.

## Inverter Local Bridge attribution

Parts of the protocol framing, register maps, telemetry, parameter handling and
project documentation were adapted from InverterLocalBridge. The original MIT
copyright and permission notice is retained in full below. It applies to those
inherited portions; project MPL-2.0 licensing does not remove that permission grant
or relicense unrelated third-party projects.

```text
MIT License

Copyright (c) 2026 Inverter Local Bridge contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Protocol references

- Local-Cloud-Bridge-for-Anenji-Easun-MPP-Solar-Inverters is GPL-3.0. Its protocol
  behavior was studied; its implementation was not copied into this integration.
- Binary and profile facts were reviewed against andronick83/powmr-eybond-proxy
  `b7a3ada` (MIT, copyright 2026 andronick83) and groove-max/ha-eybond-local
  `6ca2b23` (MPL-2.0). New adapters and selected maps are independently implemented;
  no external driver/schema file or private capture is bundled.
- Manufacturer documents located through PreK are cited by revision/hash. Their
  original files are not redistributed and no redistribution right is assumed.
- Synthetic fixtures are labeled as constructed examples, not hardware captures.

Detailed provenance and pinned references are in `docs/development/sources.md`
and the public protocol/profile guides in the source repository.

## Development tools and artwork

Home Assistant is the runtime environment. Playwright, pytest-HA and Pillow are
development/verification tools, not bundled runtime libraries. The project mark
is independently drawn by `tools/generate_brand.py`; HA Brands and Lucide sun/zap
were format and visual references, not copied artwork.

Product, platform and model names identify compatibility or sources, not endorsement.
Review the license and preserve notices whenever code or a dependency is actually reused.
