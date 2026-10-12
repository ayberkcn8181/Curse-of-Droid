"""Per-vendor unlock procedures. Only official procedures are automated or described.

Sources are the vendors' own pages (linked in each entry). Model exceptions — carrier models, US Samsung
models, regional variants — are listed as notes: the tool reports them, the device state decides.
"""

from __future__ import annotations

from ..device.profile import DeviceProfile
from ..flash.plan import Command, Plan, Step
from .base import UnlockInfo, Vendor, _enable_oem_unlocking_step, fastboot_unlock_plan


class Google(Vendor):
    name = "Google"
    brands = ("google",)

    def info(self, profile):
        return UnlockInfo(self.name, True, "fastboot flashing unlock", [
            "Turn on 'OEM unlocking' in Developer options.",
            "Reboot to fastboot and run `fastboot flashing unlock`; confirm on the phone."],
            ["https://source.android.com/docs/core/architecture/bootloader/locking_unlocking"],
            ["Carrier-sold Pixels (e.g. some US carrier models) have 'OEM unlocking' greyed out."], automated=True)

    def unlock_plan(self, profile):
        return fastboot_unlock_plan(profile, self.name, ["flashing", "unlock"])


class OnePlus(Google):
    name = "OnePlus"
    brands = ("oneplus",)

    def info(self, profile):
        i = super().info(profile)
        i.vendor = self.name
        i.links = ["https://www.oneplus.com/"]
        i.notes = ["Very old models use `fastboot oem unlock`.",
                   "Carrier models (e.g. T-Mobile) need an unlock token from OnePlus first."]
        return i


class Nothing(Google):
    name = "Nothing"
    brands = ("nothing",)

    def info(self, profile):
        i = super().info(profile)
        i.vendor, i.notes, i.links = self.name, [], ["https://nothing.tech/"]
        return i


class Motorola(Vendor):
    name = "Motorola"
    brands = ("motorola", "lenovo")

    def info(self, profile):
        return UnlockInfo(self.name, True, "unlock code from Motorola", [
            "Turn on 'OEM unlocking' in Developer options.",
            "In fastboot run `fastboot oem get_unlock_data` and paste the result on Motorola's unlock page "
            "(Motorola account required); Motorola e-mails an unlock code.",
            "Run `fastboot oem unlock <code>` and confirm on the phone."],
            ["https://en-us.support.motorola.com/app/standalone/bootloader/unlock-your-device-a"],
            ["Not every model/carrier is eligible; Motorola's page says so after you submit the data."],
            automated=True)

    def unlock_plan(self, profile):
        steps = _enable_oem_unlocking_step(profile)
        if profile.mode in ("android", "recovery", "unknown"):
            steps.append(Step("Reboot to fastboot", "Nothing is changed.", "reboot",
                              [Command("adb", ["reboot", "bootloader"])], wait_for="fastboot"))
        steps.append(Step("Read the unlock data", "Motorola needs this text to issue a code; it is read-only.",
                          commands=[Command("fastboot", ["oem", "get_unlock_data"])], unlock=True,
                          show_output=True))
        steps.append(Step("Unlock with Motorola's code",
                          "Paste the printed lines (joined, without '(bootloader)') on Motorola's unlock page, "
                          "wait for the e-mail, then enter the code here. Unlocking ERASES EVERYTHING.",
                          "data-loss", [Command("fastboot", ["oem", "unlock", "{answer}"])], unlock=True,
                          ask="unlock code from Motorola's e-mail", manual="confirm the unlock on the phone"))
        return Plan(f"Unlock the bootloader of {profile.brand} {profile.model} (Motorola)", steps,
                    ["Back up everything first: unlocking wipes the phone."])


class Xiaomi(Vendor):
    name = "Xiaomi"
    brands = ("xiaomi", "redmi", "poco")

    def info(self, profile):
        return UnlockInfo(self.name, True, "Mi Unlock (Xiaomi's tool) after account binding", [
            "Sign in with a Xiaomi account on the phone and turn on 'OEM unlocking'.",
            "Developer options → 'Mi Unlock status' → bind the account (mobile data needed).",
            "Wait the period Xiaomi imposes (shown by Mi Unlock; often 7 days or more).",
            "Run Xiaomi's Mi Unlock on Windows with the phone in fastboot and the same account."],
            ["https://en.miui.com/unlock/"],
            ["HyperOS devices for mainland China have extra requirements set by Xiaomi.",
             "The unlock is authorised by Xiaomi's servers; this tool only guides through it."])


class Samsung(Vendor):
    name = "Samsung"
    brands = ("samsung",)

    def info(self, profile):
        return UnlockInfo(self.name, True, "OEM unlocking + Download mode", [
            "Turn on 'OEM unlocking' in Developer options (may appear only after the phone was online for a while).",
            "Power off, then hold Volume Up + Volume Down and connect USB to reach the warning screen.",
            "Long-press Volume Up to choose 'Device unlock mode' and confirm. The phone is wiped."],
            ["https://www.samsung.com/"],
            ["Samsung phones sold in the USA/Canada (Snapdragon models) have no unlock option.",
             "Unlocking permanently trips Knox (Samsung Pay, Secure Folder stop working).",
             "Samsung flashes with Odin/Heimdall, not fastboot."])


class OppoRealme(Vendor):
    name = "OPPO / realme"
    brands = ("oppo", "realme")

    def info(self, profile):
        return UnlockInfo(self.name, False, "no general official method", [
            "OPPO and realme ran a 'Deep Testing' unlock program only for selected models and regions; "
            "check the vendor's community/support pages for your exact model."],
            ["https://www.realme.com/", "https://www.oppo.com/"],
            ["If an official Deep Testing app exists for your model, follow it; the tool will detect the "
             "unlocked bootloader afterwards."])


class Huawei(Vendor):
    name = "Huawei / Honor"
    brands = ("huawei", "honor")

    def info(self, profile):
        return UnlockInfo(self.name, False, "no official method since 2018", [
            "Huawei stopped issuing bootloader unlock codes in 2018; Honor followed."],
            [], ["Phones unlocked before 2018 (or by other means) stay unlocked; the tool detects it."])


class Sony(Vendor):
    name = "Sony"
    brands = ("sony",)

    def info(self, profile):
        return UnlockInfo(self.name, True, "unlock code from Sony", [
            "Check *#*#7378423#*#* → Service info → Configuration: 'Bootloader unlock allowed: Yes'.",
            "Get the code from Sony's 'Unlock bootloader' developer page (needs the IMEI).",
            "In fastboot run `fastboot oem unlock 0x<code>`."],
            ["https://developer.sony.com/open-source/aosp-on-xperia-open-devices/get-started/unlock-bootloader"],
            ["Unlocking deletes the DRM keys (camera quality on some models)."])


class Generic(Vendor):
    name = "Other"

    def info(self, profile):
        return UnlockInfo(profile.brand or self.name, False, "unknown for this brand", [
            "Look for 'OEM unlocking' in Developer options. If it exists, `fastboot flashing unlock` "
            "(or `fastboot oem unlock`) is usually the official method — check the vendor's page."],
            [], ["The tool can run `fastboot flashing unlock` if you confirm it is your vendor's method."])

    def unlock_plan(self, profile):
        if profile.oem_unlock_allowed != "yes":
            return None
        return fastboot_unlock_plan(profile, profile.brand or "generic", ["flashing", "unlock"])


ALL = [Google, OnePlus, Nothing, Motorola, Xiaomi, Samsung, OppoRealme, Huawei, Sony]
