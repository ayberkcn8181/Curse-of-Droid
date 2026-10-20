# Device support

Detection support is not installation support. The code parses ADB properties and fastboot variables;
fixtures describe Huawei ATU-L21 (A-only), OPPO CPH2801 (virtual A/B) and Pixel partition variables.
These fixtures do not certify flashing on those devices. No real device was attached for this audit.

Automated vendor unlock plans exist for Google, OnePlus, Nothing and Motorola; Xiaomi/Samsung/Sony
have guided procedures, and unsupported official methods are reported. Device/region/firmware-specific
eligibility still must be checked with the vendor. Huawei/OPPO profiles can report an already unlocked
bootloader without claiming a supported official unlock route.

ROM/recovery/GSI discovery is informational until exact device variant, firmware, artifact provenance,
partition layout and documented installation method are verified. See the P0 roadmap findings.
